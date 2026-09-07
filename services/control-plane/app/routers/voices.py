"""Organization-scoped voice settings and bounded audition jobs."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import tempfile
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.application.authorize_organization import AuthorizeOrganization
from app.core.oidc import VerifiedIdentity
from app.domain.authorization import Permission
from app.infrastructure.database import get_engine, get_session
from app.infrastructure.membership_repository import SqlAlchemyOrganizationMembershipRepository
from app.infrastructure.models import VoiceSettings, VoiceLabSample, WorkflowRun, VideoProject
from app.routers.auth import require_identity
from worker.voice_system.adapters import ADAPTERS, VoiceCatalog, capabilities
from worker.voice_system.contracts import PRESETS, VoiceError, VoiceProfile, VoiceRequest, resolve_delivery
from worker.voice_system.service import VoiceService
from worker.voice_system.settings import validate_settings

router = APIRouter(tags=['voices'])
catalog = VoiceCatalog()
BENCHMARK = ('Ngày 16 tháng 6 năm 2023, lúc 3 giờ 22 phút 39 giây chiều, máy dò LUX-ZEPLIN ghi nhận một tín hiệu.\n\n'
             'Nhưng chưa. Kết quả mới đạt 2,6 sigma. WIMP có thực sự tồn tại?\n\n'
             'Từ South Dakota đến kính Hubble, từ năm 1980 đến năm 2026, chúng ta vẫn tìm kiếm. '
             'Trên Sao Thổ, gió đạt 116 mét mỗi giây. Quãng đường dài 16.800 kilomet. Decagon nghĩa là gì?\n\n'
             'Điều kỳ lạ nhất không phải thứ ta nhìn thấy, mà là câu hỏi chưa có lời giải.')


def authorize(identity, org, session, write=False):
    if os.getenv('VISIONFLOW_VOICE_SYSTEM_ENABLED', 'false').lower() != 'true':
        raise HTTPException(503, 'Voice System is not enabled')
    if identity.subject == 'local|anonymous':
        raise HTTPException(401, 'Authentication required')
    try:
        AuthorizeOrganization(SqlAlchemyOrganizationMembershipRepository(session)).require(
            identity.subject, org, Permission.WORKFLOW_CREATE if write else Permission.WORKFLOW_VIEW, identity.email)
    except PermissionError:
        raise HTTPException(403, 'Organization access denied') from None


class SettingsRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0)
    config: dict


def settings_row(session, org):
    session.execute(insert(VoiceSettings).values(organization_id=org, revision=0, config={}).on_conflict_do_nothing())
    return session.scalar(select(VoiceSettings).where(VoiceSettings.organization_id == org).with_for_update())


@router.get('/organizations/{org}/voices')
def get_settings(org: uuid.UUID, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)):
    authorize(identity, org, session)
    row = session.get(VoiceSettings, org)
    return dict(revision=row.revision if row else 0, config=row.config if row else {}, presets=PRESETS, benchmark=BENCHMARK,
                providers=[{'provider': name, 'status': cls().config_status()} for name, cls in ADAPTERS.items()])


@router.put('/organizations/{org}/voices')
def save_settings(org: uuid.UUID, payload: SettingsRequest, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)):
    authorize(identity, org, session, True)
    try:
        config = validate_settings(payload.config)
    except (VoiceError, TypeError, KeyError, AttributeError):
        raise HTTPException(422, 'Invalid voice settings or unsupported fields') from None
    row = settings_row(session, org)
    if row.revision != payload.revision:
        raise HTTPException(409, 'Settings changed; reload before saving')
    row.config, row.revision = config, row.revision + 1
    session.commit()
    return {'revision': row.revision, 'config': row.config}


@router.get('/organizations/{org}/voices/catalog/{provider}')
def discover(org: uuid.UUID, provider: str, language: str = 'vi-VN', identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)):
    authorize(identity, org, session)
    if len(language) > 20:
        raise HTTPException(422, 'Invalid language')
    try:
        return {'voices': catalog.list_voices(provider, language), 'status': 'Connected'}
    except VoiceError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception:
        raise HTTPException(503, 'Voice catalog unavailable') from None


class SampleRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: uuid.UUID
    profile_id: str = Field(min_length=1, max_length=240)
    text: str = Field(min_length=1, max_length=1500)
    preset: str = 'neutral_documentary'
    delivery: dict = Field(default_factory=dict)


def storage():
    from worker.services.visionflow_object_storage import S3CompatibleObjectStorage, VisionFlowObjectStorageSettings
    return S3CompatibleObjectStorage(VisionFlowObjectStorageSettings.from_env())


def generate_sample(sample_id):
    # V1: bounded background work, no automatic retry of billable synthesis.
    # Expired jobs are surfaced as FAILED by read endpoint after process loss.
    with Session(get_engine()) as session:
        row = session.get(VoiceLabSample, sample_id)
        if row is None or row.state != 'QUEUED':
            return
        row.state = 'GENERATING'
        request = row.request
        org = row.organization_id
        session.commit()
    try:
        with tempfile.TemporaryDirectory(prefix='vf-voice-') as work:
            profile = VoiceProfile(**request['profile'])
            voice_request = VoiceRequest(request['text'], profile, request['delivery'], request['preset'],
                                         pronunciation=request['pronunciation'], request_id=str(sample_id))
            result = asyncio.run(VoiceService().synthesize(voice_request, str(Path(work) / 'sample.mp3')))
            asset = storage().upload_voice(str(org), str(sample_id), result.pop('local_path'))
            result.update(asset)
            result.pop('boundaries', None)
        state = 'READY'
    except VoiceError as exc:
        state, result = 'FAILED', {'error': str(exc)}
    except Exception:
        state, result = 'FAILED', {'error': 'Sample synthesis or artifact storage failed'}
    with Session(get_engine()) as session:
        row = session.get(VoiceLabSample, sample_id)
        if row and row.state == 'GENERATING':
            row.state, row.result = state, result
            session.commit()


@router.post('/organizations/{org}/voices/samples', status_code=202)
def create_sample(org: uuid.UUID, payload: SampleRequest, background: BackgroundTasks,
                  identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)):
    authorize(identity, org, session, True)
    settings = settings_row(session, org)  # Serializes per-organization quota checks.
    existing = session.get(VoiceLabSample, payload.id)
    original = payload.model_dump(mode='json')
    if existing:
        if existing.organization_id != org or existing.request.get('original') != original:
            raise HTTPException(409, 'Sample ID already used with different input')
        return {'id': str(existing.id), 'state': existing.state}
    config = settings.config or {}
    try:
        profile = next((VoiceProfile(**p) for p in config.get('profiles', []) if p['id'] == payload.profile_id), None)
        if profile is None:
            raise VoiceError('Profile not found in this organization')
        preset, delivery = resolve_delivery(profile, {'preset': payload.preset, 'delivery': payload.delivery}, presets=config.get('presets'))
        VoiceRequest(payload.text, profile, delivery, pronunciation=config.get('pronunciation', []))
        if ADAPTERS[profile.provider]().config_status() != 'Configured':
            raise VoiceError('Provider credentials are missing')
        storage()  # Do not bill synthesis when artifact storage is not configured.
    except (VoiceError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None
    since = datetime.now(timezone.utc) - timedelta(days=1)
    recent = session.scalars(select(VoiceLabSample).where(VoiceLabSample.organization_id == org, VoiceLabSample.created_at >= since)).all()
    active = sum(row.state in ('QUEUED', 'GENERATING') and row.updated_at > datetime.now(timezone.utc) - timedelta(minutes=10) for row in recent)
    used = sum(len(row.request.get('text', '')) for row in recent)
    if active >= 4 or used + len(payload.text) > int(os.getenv('VISIONFLOW_VOICE_LAB_DAILY_CHARACTERS', '12000')):
        raise HTTPException(429, 'Voice Lab concurrency or daily character limit reached')
    row = VoiceLabSample(id=payload.id, organization_id=org, state='QUEUED', request={
        'original': original, 'profile': profile.to_dict(), 'text': payload.text,
        'preset': preset, 'delivery': delivery, 'pronunciation': config.get('pronunciation', [])}, result={})
    session.add(row)
    session.commit()
    background.add_task(generate_sample, row.id)
    return {'id': str(row.id), 'state': row.state}


@router.get('/organizations/{org}/voices/samples/{sample_id}')
def get_sample(org: uuid.UUID, sample_id: uuid.UUID, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)):
    authorize(identity, org, session)
    row = session.get(VoiceLabSample, sample_id)
    if row is None or row.organization_id != org:
        raise HTTPException(404, 'Sample not found')
    if row.state in ('QUEUED', 'GENERATING') and row.updated_at < datetime.now(timezone.utc) - timedelta(minutes=10):
        row.state, row.result = 'FAILED', {'error': 'Generation interrupted; no automatic billable retry'}
        session.commit()
    result = dict(row.result)
    if row.state == 'READY':
        result['download_url'] = storage().generate_presigned_download_url(result['object_key'], expires_in_seconds=300)
    return {'id': str(row.id), 'state': row.state, 'result': result, 'profile': row.request['profile']}


class WinnerRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0)
    channel_id: str = Field(min_length=1, max_length=160)


@router.post('/organizations/{org}/voices/samples/{sample_id}/select')
def select_winner(org: uuid.UUID, sample_id: uuid.UUID, payload: WinnerRequest,
                  identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)):
    authorize(identity, org, session, True)
    row = session.get(VoiceLabSample, sample_id)
    if row is None or row.organization_id != org or row.state != 'READY':
        raise HTTPException(404, 'Ready sample not found')
    settings = settings_row(session, org)
    if settings.revision != payload.revision:
        raise HTTPException(409, 'Settings changed; reload before selecting winner')
    config = dict(settings.config)
    profile = dict(row.request['profile'])
    profiles = list(config.get('profiles', []))
    # Preserve the auditioned identity, even if the original profile changed.
    if not any(p == profile for p in profiles):
        profile['id'] = str(uuid.uuid4())
        profiles.append(profile)
    preset_id = row.request['preset']
    # Freeze the winning delivery as a named editable preset.
    winner_preset = 'audition-' + str(sample_id)
    config['presets'] = {**config.get('presets', {}), winner_preset: row.request['delivery']}
    config['profiles'] = profiles
    config['channels'] = {**config.get('channels', {}), payload.channel_id.strip(): {
        'voice_profile_id': profile['id'], 'default_preset_id': winner_preset}}
    try:
        settings.config = validate_settings(config)
    except VoiceError as exc:
        raise HTTPException(422, str(exc)) from None
    settings.revision += 1
    row.result = {**row.result, 'selected_for_channel': payload.channel_id.strip()}
    session.commit()
    return {'revision': settings.revision, 'config': settings.config}


class RatingRequest(BaseModel):
    ratings: dict[str, int]


@router.post('/organizations/{org}/voices/render/{workflow_id}', status_code=202)
def dispatch_render(org: uuid.UUID, workflow_id: uuid.UUID, identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)):
    authorize(identity, org, session, True)
    from worker.voice_system.dispatch import sign_dispatch
    from worker.voice_system.adapters import _http
    row = session.scalar(select(WorkflowRun).join(VideoProject, WorkflowRun.project_id == VideoProject.id).where(
        WorkflowRun.id == workflow_id, VideoProject.organization_id == org).with_for_update())
    if row is None:
        raise HTTPException(404, 'Workflow not found')
    payload = dict(row.input_payload or {})
    if not payload.get('voice_context'):
        raise HTTPException(422, 'Workflow has no canonical voice configuration')
    if payload.get('voice_dispatch_started'):
        raise HTTPException(409, 'Voice render was already dispatched; inspect workflow before retrying')
    if row.state not in ('READY', 'QUEUED', 'RENDERING'):
        raise HTTPException(409, 'Submit workflow before rendering')
    endpoint = os.getenv('VISIONFLOW_MODAL_VOICE_ENDPOINT', '')
    from urllib.parse import urlparse
    parsed = urlparse(endpoint)
    if parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.modal.run') or parsed.username or parsed.password or parsed.query:
        raise HTTPException(503, 'Modal voice endpoint is not configured')
    try:
        signed = sign_dispatch({**payload, 'workflow_run_id': str(workflow_id)})
    except VoiceError as exc:
        raise HTTPException(503, str(exc)) from None
    # Commit before network dispatch: uncertain responses must not double-charge.
    row.input_payload = {**payload, 'voice_dispatch_started': True}
    session.commit()
    try:
        _http('POST', endpoint, json=signed)
    except VoiceError:
        raise HTTPException(503, 'Dispatch failed or outcome unknown; inspect Modal before retrying') from None
    return {'state': 'QUEUED', 'workflow_run_id': str(workflow_id)}


@router.put('/organizations/{org}/voices/samples/{sample_id}/rating')
def rate_sample(org: uuid.UUID, sample_id: uuid.UUID, payload: RatingRequest,
                identity: VerifiedIdentity = Depends(require_identity), session: Session = Depends(get_session)):
    authorize(identity, org, session, True)
    if set(payload.ratings) - {'naturalness', 'pronunciation', 'storytelling', 'emotion', 'consistency'} or any(not 1 <= n <= 5 for n in payload.ratings.values()):
        raise HTTPException(422, 'Ratings must be 1 to 5')
    row = session.scalar(select(VoiceLabSample).where(VoiceLabSample.id == sample_id, VoiceLabSample.organization_id == org).with_for_update())
    if row is None or row.state != 'READY':
        raise HTTPException(404, 'Ready sample not found')
    row.result = {**row.result, 'ratings': payload.ratings}
    session.commit()
    return {'saved': True}
