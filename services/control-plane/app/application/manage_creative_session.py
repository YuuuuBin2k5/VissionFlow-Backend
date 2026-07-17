from __future__ import annotations

import uuid
import logging
import hashlib
import json
from datetime import datetime, timedelta, UTC
from typing import Tuple, List, Dict, Optional, Any, Literal

from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import select, func, text
from pydantic import BaseModel, Field, ConfigDict

from app.infrastructure.models import (
    CreativeSession,
    CreativeMessage,
    CreativeProposal,
    CreativeTurn,
    CreativeCommandReceipt,
    ProviderCredential,
    PromptTemplate,
    PromptVersion,
    WorkflowRun,
    VideoProject,
)
from app.infrastructure.creative_session_repository import SqlAlchemyCreativeSessionRepository
from app.infrastructure.repositories import SqlAlchemyShortFormWorkflowRepository
from app.infrastructure.creative_document_repository import SqlAlchemyCreativeDocumentRepository
from app.application.ports.creative_planning_provider import CreativePlanningProvider
from app.application.create_short_form import CreateShortFormCommand
from app.core.credential_cipher import ProviderCredentialCipher

logger = logging.getLogger(__name__)


# Pydantic schemas for strict validation
class CreationSpecSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    brief: str = Field(min_length=1, max_length=50000)
    format_profile: Literal["short_vertical"] = Field(default="short_vertical")
    timezone: str = Field(min_length=1, max_length=100)
    language: Literal["vi", "en"] = Field(default="vi")
    voice: str = Field(min_length=1, max_length=100)
    caption_preset: str = Field(min_length=1, max_length=100)
    visual_preset: str = Field(min_length=1, max_length=100)
    duration_seconds: int = Field(ge=15, le=90)


# Custom Exceptions
class CreativeSessionError(Exception):
    pass

class CreativeSessionConflict(CreativeSessionError):
    pass

class CreativeSessionAlreadyBound(CreativeSessionError):
    pass

class ProviderUnavailable(CreativeSessionError):
    pass

class ProviderRateLimited(CreativeSessionError):
    pass

class PromptBaselineUnavailable(CreativeSessionError):
    pass

class IdempotencyPayloadMismatch(CreativeSessionError):
    pass


class ManageCreativeSession:
    def __init__(
        self,
        session_maker: sessionmaker[Session],
        provider_adapter: CreativePlanningProvider,
        env_fallback_enabled: bool = False,
        env_fallback_key: str | None = None,
    ) -> None:
        self._session_maker = session_maker
        self._adapter = provider_adapter
        self._env_fallback_enabled = env_fallback_enabled
        self._env_fallback_key = env_fallback_key

    def create_session(
        self,
        *,
        organization_id: uuid.UUID,
        creation_spec_dict: dict,
        idempotency_key: str,
    ) -> uuid.UUID:
        # Pydantic validate creation spec
        spec = CreationSpecSchema(**creation_spec_dict).model_dump()
        fingerprint = hashlib.sha256(json_dump_canonical(spec).encode()).hexdigest()

        with self._session_maker() as db_session:
            repo = SqlAlchemyCreativeSessionRepository(db_session)

            # Check idempotency command receipt
            receipt = repo.get_command_receipt(organization_id, "create_session", idempotency_key)
            if receipt:
                if receipt.request_fingerprint != fingerprint:
                    raise IdempotencyPayloadMismatch("Creation payload fingerprint mismatch for same key.")
                return uuid.UUID(receipt.result_payload["session_id"])

            # Create Session
            sess = repo.create_session(organization_id, spec)

            # Save receipt
            receipt = CreativeCommandReceipt(
                organization_id=organization_id,
                session_id=sess.id,
                operation_type="create_session",
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                result_payload={"session_id": str(sess.id)},
            )
            repo.save_command_receipt(receipt)
            db_session.commit()
            return sess.id

    def update_creation_spec(
        self,
        *,
        session_id: uuid.UUID,
        organization_id: uuid.UUID,
        creation_spec_dict: dict,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict:
        spec = CreationSpecSchema(**creation_spec_dict).model_dump()
        fingerprint = hashlib.sha256(json_dump_canonical(spec).encode()).hexdigest()

        with self._session_maker() as db_session:
            repo = SqlAlchemyCreativeSessionRepository(db_session)
            sess = repo.get_session(session_id, lock=True)
            if not sess:
                raise CreativeSessionError("Creative session not found.")
            if sess.organization_id != organization_id:
                raise CreativeSessionError("Unauthorized session tenant access.")

            # Check idempotency command receipt
            receipt = repo.get_command_receipt(organization_id, "update_creation_spec", idempotency_key)
            if receipt:
                if receipt.request_fingerprint != fingerprint:
                    raise IdempotencyPayloadMismatch("Payload fingerprint mismatch for spec update.")
                return receipt.result_payload

            # Validate modifications allowed
            if sess.workflow_run_id is not None:
                raise CreativeSessionConflict("Cannot update creation spec on bound session.")

            active_turn = repo.get_active_generating_turn(session_id)
            if active_turn and active_turn.lease_expires_at > datetime.now(UTC):
                raise CreativeSessionConflict("Cannot update creation spec while turn is generating.")

            if sess.revision != expected_revision:
                raise CreativeSessionConflict("Creative session revision conflict. Please reload.")

            # Apply Update
            sess.creation_spec = spec
            sess.revision += 1

            # Save receipt
            result = {
                "session_id": str(sess.id),
                "revision": sess.revision,
                "creation_spec": sess.creation_spec,
            }
            receipt = CreativeCommandReceipt(
                organization_id=organization_id,
                session_id=sess.id,
                operation_type="update_creation_spec",
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                result_payload=result,
            )
            repo.save_command_receipt(receipt)
            db_session.commit()
            return result

    def get_session_details(
        self,
        session_id: uuid.UUID,
        organization_id: uuid.UUID,
        message_limit: int,
        message_offset: int,
        proposal_limit: int,
        proposal_offset: int,
    ) -> dict:
        with self._session_maker() as db_session:
            repo = SqlAlchemyCreativeSessionRepository(db_session)
            sess, messages, m_count, proposals, p_count = repo.get_session_with_messages_and_proposals(
                session_id, message_limit, message_offset, proposal_limit, proposal_offset
            )
            if not sess:
                raise CreativeSessionError("Creative session not found.")
            if sess.organization_id != organization_id:
                raise CreativeSessionError("Unauthorized session tenant access.")

            return {
                "id": str(sess.id),
                "organization_id": str(sess.organization_id),
                "workflow_run_id": str(sess.workflow_run_id) if sess.workflow_run_id else None,
                "revision": sess.revision,
                "creation_spec": sess.creation_spec,
                "messages": {
                    "items": [{"id": str(m.id), "actor": m.actor, "content": m.content, "created_at": m.created_at.isoformat()} for m in messages],
                    "limit": message_limit,
                    "offset": message_offset,
                    "total": m_count,
                },
                "proposals": {
                    "items": [{
                        "id": str(p.id),
                        "message_id": str(p.message_id),
                        "parent_proposal_id": str(p.parent_proposal_id) if p.parent_proposal_id else None,
                        "state": p.state,
                        "title": p.title,
                        "brief": p.brief,
                        "script": p.script,
                        "scenes": p.scenes,
                        "version": p.version,
                        "trace_id": p.trace_id,
                        "created_at": p.created_at.isoformat(),
                    } for p in proposals],
                    "limit": proposal_limit,
                    "offset": proposal_offset,
                    "total": p_count,
                }
            }

    def get_proposal_details(self, session_id: uuid.UUID, proposal_id: uuid.UUID, organization_id: uuid.UUID) -> dict:
        with self._session_maker() as db_session:
            repo = SqlAlchemyCreativeSessionRepository(db_session)
            sess = repo.get_session(session_id)
            if not sess:
                raise CreativeSessionError("Creative session not found.")
            if sess.organization_id != organization_id:
                raise CreativeSessionError("Unauthorized session tenant access.")

            proposal = repo.get_proposal(proposal_id)
            if not proposal or proposal.session_id != session_id:
                raise CreativeSessionError("Proposal not found.")

            return {
                "id": str(proposal.id),
                "session_id": str(proposal.session_id),
                "message_id": str(proposal.message_id),
                "parent_proposal_id": str(proposal.parent_proposal_id) if proposal.parent_proposal_id else None,
                "state": proposal.state,
                "title": proposal.title,
                "brief": proposal.brief,
                "script": proposal.script,
                "scenes": proposal.scenes,
                "version": proposal.version,
                "trace_id": proposal.trace_id,
                "created_at": proposal.created_at.isoformat(),
                "generation_manifest": proposal.generation_manifest,
            }

    def create_manual_proposal(
        self,
        *,
        session_id: uuid.UUID,
        organization_id: uuid.UUID,
        expected_session_revision: int,
        idempotency_key: str,
        title: str,
        brief: str,
        script: str,
        scenes: list[dict],
    ) -> uuid.UUID:
        if len(script) < 40:
            raise CreativeSessionError("Script must be at least 40 characters long.")
        if not (3 <= len(scenes) <= 20):
            raise CreativeSessionError("Scenes count must be between 3 and 20.")

        fingerprint_payload = {
            "title": title,
            "brief": brief,
            "script": script,
            "scenes": scenes,
        }
        fingerprint = hashlib.sha256(json_dump_canonical(fingerprint_payload).encode()).hexdigest()

        with self._session_maker() as db_session:
            repo = SqlAlchemyCreativeSessionRepository(db_session)
            sess = repo.get_session(session_id, lock=True)
            if not sess:
                raise CreativeSessionError("Creative session not found.")
            if sess.organization_id != organization_id:
                raise CreativeSessionError("Unauthorized session tenant access.")

            # Check generic receipt
            receipt = repo.get_command_receipt(organization_id, "create_manual_proposal", idempotency_key)
            if receipt:
                if receipt.request_fingerprint != fingerprint:
                    raise IdempotencyPayloadMismatch("Fingerprint mismatch for same idempotency key.")
                return uuid.UUID(receipt.result_payload["proposal_id"])

            if sess.workflow_run_id is not None:
                raise CreativeSessionConflict("Cannot create proposal on bound session.")
            if sess.revision != expected_session_revision:
                raise CreativeSessionConflict("Session revision conflict. Please reload.")

            # 1. Create User message summarizing manual project creation
            summary_content = f"[Manual script creation] Title: {title}. Script length: {len(script)} chars."
            msg = repo.save_message(session_id, "user", summary_content)

            # Sequential sequential proposal version count
            prop_count = db_session.scalar(
                select(func.count()).select_from(CreativeProposal).where(CreativeProposal.session_id == session_id)
            ) or 0
            next_version = prop_count + 1

            # 2. Save Proposal
            manifest = {
                "source": "manual",
                "provider": None,
                "model": None,
                "provider_credential_id": None,
                "prompt_templates": {},
                "schema_version": 1,
                "trace_id": str(uuid.uuid4()),
            }
            proposal = repo.save_proposal(
                session_id=session_id,
                message_id=msg.id,
                parent_proposal_id=None,
                state="proposed",
                title=title,
                brief=brief,
                script=script,
                scenes=scenes,
                version=next_version,
                trace_id=manifest["trace_id"],
                generation_manifest=manifest,
            )

            # Update Session Revision
            sess.revision += 1

            # Save Command Receipt
            receipt = CreativeCommandReceipt(
                organization_id=organization_id,
                session_id=session_id,
                operation_type="create_manual_proposal",
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                result_payload={"proposal_id": str(proposal.id), "revision": sess.revision},
            )
            repo.save_command_receipt(receipt)
            db_session.commit()
            return proposal.id

    def create_proposal_revision(
        self,
        *,
        session_id: uuid.UUID,
        parent_proposal_id: uuid.UUID,
        organization_id: uuid.UUID,
        expected_session_revision: int,
        idempotency_key: str,
        title: str,
        brief: str,
        script: str,
        scenes: list[dict],
    ) -> uuid.UUID:
        if len(script) < 40:
            raise CreativeSessionError("Script must be at least 40 characters long.")
        if not (3 <= len(scenes) <= 20):
            raise CreativeSessionError("Scenes count must be between 3 and 20.")

        fingerprint_payload = {
            "parent_proposal_id": str(parent_proposal_id),
            "title": title,
            "brief": brief,
            "script": script,
            "scenes": scenes,
        }
        fingerprint = hashlib.sha256(json_dump_canonical(fingerprint_payload).encode()).hexdigest()

        with self._session_maker() as db_session:
            repo = SqlAlchemyCreativeSessionRepository(db_session)
            sess = repo.get_session(session_id, lock=True)
            if not sess:
                raise CreativeSessionError("Creative session not found.")
            if sess.organization_id != organization_id:
                raise CreativeSessionError("Unauthorized session tenant access.")

            # Check receipt
            receipt = repo.get_command_receipt(organization_id, "create_proposal_revision", idempotency_key)
            if receipt:
                if receipt.request_fingerprint != fingerprint:
                    raise IdempotencyPayloadMismatch("Fingerprint mismatch for same revision key.")
                return uuid.UUID(receipt.result_payload["proposal_id"])

            if sess.workflow_run_id is not None:
                raise CreativeSessionConflict("Cannot edit proposal on bound session.")
            if sess.revision != expected_session_revision:
                raise CreativeSessionConflict("Session revision conflict. Please reload.")

            parent = repo.get_proposal(parent_proposal_id)
            if not parent or parent.session_id != session_id:
                raise CreativeSessionError("Parent proposal not found in this session.")

            prop_count = db_session.scalar(
                select(func.count()).select_from(CreativeProposal).where(CreativeProposal.session_id == session_id)
            ) or 0
            next_version = prop_count + 1

            # Revision inherits the parent's message_id to maintain connection to original turn conversation
            manifest = {
                "source": "operator_edit",
                "provider": None,
                "model": None,
                "provider_credential_id": None,
                "prompt_templates": {},
                "schema_version": 1,
                "trace_id": parent.trace_id,
            }
            proposal = repo.save_proposal(
                session_id=session_id,
                message_id=parent.message_id,
                parent_proposal_id=parent.id,
                state="proposed",
                title=title,
                brief=brief,
                script=script,
                scenes=scenes,
                version=next_version,
                trace_id=parent.trace_id,
                generation_manifest=manifest,
            )

            sess.revision += 1

            receipt = CreativeCommandReceipt(
                organization_id=organization_id,
                session_id=session_id,
                operation_type="create_proposal_revision",
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                result_payload={"proposal_id": str(proposal.id), "revision": sess.revision},
            )
            repo.save_command_receipt(receipt)
            db_session.commit()
            return proposal.id

    def accept_proposal(
        self,
        *,
        session_id: uuid.UUID,
        proposal_id: uuid.UUID,
        organization_id: uuid.UUID,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict:
        fingerprint = hashlib.sha256(f"{proposal_id}:{expected_revision}".encode()).hexdigest()

        with self._session_maker() as db_session:
            repo = SqlAlchemyCreativeSessionRepository(db_session)
            sess = repo.get_session(session_id, lock=True)
            if not sess:
                raise CreativeSessionError("Creative session not found.")
            if sess.organization_id != organization_id:
                raise CreativeSessionError("Unauthorized session tenant access.")

            receipt = repo.get_command_receipt(organization_id, "accept_proposal", idempotency_key)
            if receipt:
                if receipt.request_fingerprint != fingerprint:
                    raise IdempotencyPayloadMismatch("Idempotency fingerprint mismatch.")
                return receipt.result_payload

            if sess.workflow_run_id is not None:
                raise CreativeSessionConflict("Cannot accept proposal on bound session.")
            if sess.revision != expected_revision:
                raise CreativeSessionConflict("Session revision conflict. Please reload.")

            proposal = repo.get_proposal(proposal_id)
            if not proposal or proposal.session_id != session_id:
                raise CreativeSessionError("Proposal not found in this session.")

            # Mark all previous accepted proposals in this session as superseded
            db_session.execute(
                text(
                    "UPDATE creative_proposals SET state = 'superseded' "
                    "WHERE session_id = :sess_id AND state = 'accepted'"
                ).bindparams(sess_id=session_id)
            )

            # Mark target proposal as accepted
            proposal.state = "accepted"
            sess.revision += 1

            result = {
                "session_id": str(sess.id),
                "accepted_proposal_id": str(proposal.id),
                "revision": sess.revision,
            }
            receipt = CreativeCommandReceipt(
                organization_id=organization_id,
                session_id=session_id,
                operation_type="accept_proposal",
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                result_payload=result,
            )
            repo.save_command_receipt(receipt)
            db_session.commit()
            return result

    def send_creative_session_message(
        self,
        *,
        session_id: uuid.UUID,
        organization_id: uuid.UUID,
        message: str,
        expected_session_revision: int,
        idempotency_key: str,
    ) -> dict:
        fingerprint = hashlib.sha256(f"{message}:{expected_session_revision}".encode()).hexdigest()

        # Step 1: Lock and validate in Transaction 1
        with self._session_maker() as db_session:
            repo = SqlAlchemyCreativeSessionRepository(db_session)
            sess = repo.get_session(session_id, lock=True)
            if not sess:
                raise CreativeSessionError("Creative session not found.")
            if sess.organization_id != organization_id:
                raise CreativeSessionError("Unauthorized session tenant access.")

            creation_spec_val = dict(sess.creation_spec)

            if sess.workflow_run_id is not None:
                raise CreativeSessionConflict("Session already finalized and bound to workflow run.")

            # Check generic receipt
            receipt = repo.get_command_receipt(organization_id, "send_message", idempotency_key)
            if receipt:
                if receipt.request_fingerprint != fingerprint:
                    raise IdempotencyPayloadMismatch("Payload mismatch for same message idempotency key.")
                return receipt.result_payload

            # Check existing turn
            existing_turn = repo.get_turn_by_idempotency_key(session_id, idempotency_key)
            if existing_turn:
                if existing_turn.status == "completed":
                    # Fetch completed turn details
                    res_payload = self._build_turn_completed_payload(db_session, existing_turn)
                    # Cache result payload in command receipt for quick future replays
                    self._save_completed_message_receipt(db_session, organization_id, session_id, idempotency_key, fingerprint, res_payload)
                    db_session.commit()
                    return res_payload

                # Active turn exists
                if existing_turn.status == "generating":
                    if existing_turn.lease_expires_at > datetime.now(UTC):
                        raise CreativeSessionConflict("Generation already in progress for this turn lease.")

                    # Expired: Reclaim in place
                    existing_turn.lease_token = uuid.uuid4()
                    existing_turn.lease_expires_at = datetime.now(UTC) + timedelta(seconds=150)
                    existing_turn.generation_attempt_count += 1
                    existing_turn.failure_code = None
                    active_turn_id = existing_turn.id
                    active_lease_token = existing_turn.lease_token
                    user_msg_id = existing_turn.user_message_id
                    db_session.commit()

                    # Run generation using reclaimed properties
                    return self._execute_planning_generation(
                        session_id=session_id,
                        organization_id=organization_id,
                        turn_id=active_turn_id,
                        lease_token=active_lease_token,
                        user_message_id=user_msg_id,
                        user_message_text=message,
                        expected_revision=expected_session_revision,
                        idempotency_key=idempotency_key,
                        fingerprint=fingerprint,
                        creation_spec=creation_spec_val,
                    )

            # Check other active generating turn in this session to free index
            active_gen_turn = repo.get_active_generating_turn(session_id, lock=True)
            if active_gen_turn:
                if active_gen_turn.lease_expires_at > datetime.now(UTC):
                    raise CreativeSessionConflict("Another generation turn is currently active in this session.")
                # Mark expired active turn as failed
                active_gen_turn.status = "failed"
                active_gen_turn.failure_code = "lease_expired"
                db_session.flush()

            # Verify revision
            if sess.revision != expected_session_revision:
                raise CreativeSessionConflict("Creative session revision conflict. Please reload.")

            # Create User message
            user_msg = repo.save_message(session_id, "user", message)

            # Insert new Turn
            new_turn = CreativeTurn(
                session_id=session_id,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                status="generating",
                lease_token=uuid.uuid4(),
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=150),
                expected_revision=expected_session_revision,
                user_message_id=user_msg.id,
            )
            repo.save_turn(new_turn)
            db_session.commit()

            active_turn_id = new_turn.id
            active_lease_token = new_turn.lease_token
            user_msg_id = user_msg.id

        # Step 2: Trigger external LLM Call (Outside Db Transactions)
        return self._execute_planning_generation(
            session_id=session_id,
            organization_id=organization_id,
            turn_id=active_turn_id,
            lease_token=active_lease_token,
            user_message_id=user_msg_id,
            user_message_text=message,
            expected_revision=expected_session_revision,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            creation_spec=creation_spec_val,
        )

    def _execute_planning_generation(
        self,
        session_id: uuid.UUID,
        organization_id: uuid.UUID,
        turn_id: uuid.UUID,
        lease_token: uuid.UUID,
        user_message_id: uuid.UUID,
        user_message_text: str,
        expected_revision: int,
        idempotency_key: str,
        fingerprint: str,
        creation_spec: dict,
    ) -> dict:
        # Load active prompts & provider credential
        credential_id, secret, model_name = self._resolve_credentials(organization_id)
        planner_tmpl, planner_version, director_tmpl, director_version = self._resolve_prompts(organization_id)

        # Build prompt history
        history = []
        with self._session_maker() as db_session:
            # Query messages history
            msgs = db_session.scalars(
                select(CreativeMessage)
                .where(CreativeMessage.session_id == session_id, CreativeMessage.id != user_message_id)
                .order_by(CreativeMessage.created_at.asc())
            ).all()
            for m in msgs:
                history.append({"actor": m.actor, "content": m.content})

        # Run provider API call
        try:
            assistant_msg, proposal_dict = self._adapter.generate_proposal(
                prompt=user_message_text,
                history=history,
                creation_spec=creation_spec,
                planner_prompt_template=planner_tmpl,
                director_prompt_template=director_tmpl,
                provider_credential_secret=secret,
                model_name=model_name,
            )
            # Update key usage in safe independent session
            self._update_credential_usage(credential_id, failure_code=None)
        except Exception as exc:
            # Update error code
            failure_code = type(exc).__name__
            self._update_credential_usage(credential_id, failure_code=failure_code)

            # Map exceptions
            error_mapping = {
                "GeminiRateLimitError": ProviderRateLimited,
                "GeminiTimeoutError": ProviderUnavailable,
                "GeminiConnectionError": ProviderUnavailable,
                "GeminiServerError": ProviderUnavailable,
            }
            error_cls = error_mapping.get(failure_code, CreativeSessionError)

            # Mark turn as failed
            self._mark_turn_failed(turn_id, lease_token, failure_code)
            raise error_cls(f"Upstream planning generator error: {exc}") from exc

        # Step 3: Persist results in Transaction 2
        with self._session_maker() as db_session:
            repo = SqlAlchemyCreativeSessionRepository(db_session)
            sess = repo.get_session(session_id, lock=True)
            turn = db_session.scalar(
                select(CreativeTurn).where(CreativeTurn.id == turn_id).with_for_update()
            )

            # Lease compare-and-set verification
            if not turn or turn.lease_token != lease_token or turn.status != "generating":
                logger.warning(f"Late response discarded for turn {turn_id} lease mismatch.")
                raise CreativeSessionConflict("Late provider response discarded due to turn lease expiration.")

            if sess.revision != expected_revision:
                turn.status = "failed"
                turn.failure_code = "session_revision_mismatch"
                db_session.commit()
                raise CreativeSessionConflict("Creative session revision changed during generation. Turn failed.")

            # Save assistant message
            assistant_message = repo.save_message(session_id, "assistant", assistant_msg)

            # Generate version Sequential count
            prop_count = db_session.scalar(
                select(func.count()).select_from(CreativeProposal).where(CreativeProposal.session_id == session_id)
            ) or 0
            next_version = prop_count + 1

            # Pin baseline configuration versions in proposal generation manifest
            manifest = {
                "source": "gemini",
                "provider": "gemini",
                "model": model_name or "gemini-2.5-flash",
                "provider_credential_id": str(credential_id) if isinstance(credential_id, uuid.UUID) else credential_id,
                "prompt_templates": {
                    "short_video_scene_planner": {
                        "template_id": planner_tmpl if planner_tmpl else None,
                        "version": planner_version,
                    },
                    "short_video_visual_art_director": {
                        "template_id": director_tmpl if director_tmpl else None,
                        "version": director_version,
                    }
                },
                "schema_version": 1,
                "trace_id": str(uuid.uuid4()),
            }

            # Save Proposal
            proposal = repo.save_proposal(
                session_id=session_id,
                message_id=assistant_message.id,
                parent_proposal_id=None,
                state="proposed",
                title=proposal_dict["title"],
                brief=proposal_dict["brief"],
                script=proposal_dict["script"],
                scenes=proposal_dict["scenes"],
                version=next_version,
                trace_id=manifest["trace_id"],
                generation_manifest=manifest,
            )

            # Mark turn as completed
            turn.status = "completed"
            turn.assistant_message_id = assistant_message.id
            turn.proposal_id = proposal.id

            # Increment revision
            sess.revision += 1
            db_session.flush()

            # Compile payload response
            res_payload = {
                "session_id": str(sess.id),
                "revision": sess.revision,
                "assistant_message": assistant_message.content,
                "proposal": {
                    "id": str(proposal.id),
                    "state": proposal.state,
                    "title": proposal.title,
                    "brief": proposal.brief,
                    "script": proposal.script,
                    "scenes": proposal.scenes,
                    "version": proposal.version,
                    "trace_id": proposal.trace_id,
                }
            }

            # Save Command Receipt
            self._save_completed_message_receipt(db_session, organization_id, session_id, idempotency_key, fingerprint, res_payload)
            db_session.commit()
            return res_payload

    def create_workflow_draft_from_session(
        self,
        *,
        session_id: uuid.UUID,
        organization_id: uuid.UUID,
        accepted_proposal_id: uuid.UUID,
        client_idempotency_key: str,
    ) -> dict:
        # Canonical Bounded Idempotency Keys derivation
        derived_receipt_key = f"draft:{hashlib.sha256((str(session_id) + ':' + client_idempotency_key).encode()).hexdigest()}"
        derived_wf_run_key = f"wf:{hashlib.sha256((str(session_id) + ':' + str(accepted_proposal_id)).encode()).hexdigest()}"

        with self._session_maker() as db_session:
            repo = SqlAlchemyCreativeSessionRepository(db_session)
            wf_repo = SqlAlchemyShortFormWorkflowRepository(db_session)
            doc_repo = SqlAlchemyCreativeDocumentRepository(db_session)

            # Lock session FOR UPDATE
            sess = repo.get_session(session_id, lock=True)
            if not sess:
                raise CreativeSessionError("Creative session not found.")
            if sess.organization_id != organization_id:
                raise CreativeSessionError("Unauthorized session tenant access.")

            # Validate accepted proposal
            proposal = repo.get_proposal(accepted_proposal_id)
            if not proposal or proposal.session_id != session_id or proposal.state != "accepted":
                raise CreativeSessionError("Invalid accepted proposal selected.")

            # One-session-one-workflow-run invariant validation
            if sess.workflow_run_id is not None:
                # Resolve active receipt to verify replay
                receipt = db_session.scalar(
                    select(CreativeCommandReceipt).where(
                        CreativeCommandReceipt.organization_id == organization_id,
                        CreativeCommandReceipt.operation_type == "create_workflow_draft",
                        CreativeCommandReceipt.idempotency_key == derived_receipt_key,
                    )
                )
                if receipt:
                    # Match replay specs
                    if receipt.result_payload["accepted_proposal_id"] == str(accepted_proposal_id):
                        return {
                            "workflow_run_id": receipt.result_payload["workflow_run_id"],
                            "creative_document_version_id": receipt.result_payload["creative_document_version_id"],
                            "idempotent_replay": True,
                        }
                # Mismatch key / proposal attempts trigger already bound conflict block
                raise CreativeSessionAlreadyBound("Creative session has already been finalized and bound to a workflow run.")

            # Check generic receipt
            receipt = db_session.scalar(
                select(CreativeCommandReceipt).where(
                    CreativeCommandReceipt.organization_id == organization_id,
                    CreativeCommandReceipt.operation_type == "create_workflow_draft",
                    CreativeCommandReceipt.idempotency_key == derived_receipt_key,
                )
            )
            if receipt:
                return {
                    "workflow_run_id": receipt.result_payload["workflow_run_id"],
                    "creative_document_version_id": receipt.result_payload["creative_document_version_id"],
                    "idempotent_replay": True,
                }

            # Map CreationSpec properties to CreateShortFormCommand
            creation_spec = sess.creation_spec

            # Map input payload
            input_payload = {
                "format_profile": creation_spec["format_profile"],
                "aspect_ratio": "9:16",
                "target_language": creation_spec["language"],
                "duration_seconds": creation_spec["duration_seconds"],
                "voice_code": creation_spec["voice"],
                "subtitle_preset": creation_spec["caption_preset"],
                "visual_preset": creation_spec["visual_preset"],
                "target_platforms": ["tiktok", "youtube_shorts", "reels"],
                "session_id": str(session_id),
                "accepted_proposal_id": str(accepted_proposal_id),
            }

            command = CreateShortFormCommand(
                organization_id=organization_id,
                title=creation_spec["title"],
                brief=creation_spec["brief"],
                idempotency_key=derived_wf_run_key,
                format_profile=creation_spec["format_profile"],
                timezone=creation_spec["timezone"],
                prompt_manifest=proposal.generation_manifest,
                input_payload=input_payload,
                trace_id=proposal.trace_id,
            )

            # Atomic transaction-aware creations
            # 1. WorkflowRun and VideoProject setup (Perform only queries/add/flush, NO COMMITS)
            wf_run, _ = wf_repo._create_or_get_initial_run_in_transaction(command)

            # 2. Save creative document content (Perform only queries/add/flush, NO COMMITS)
            # Transform scenes dictionary keys to match expected types
            transformed_scenes = []
            for sc in proposal.scenes:
                transformed_scenes.append({
                    "narration": sc["narration"],
                    "visual_prompt": sc["visual_prompt"],
                    "duration_seconds": sc["duration_seconds"],
                    "transition": sc.get("transition", "cut"),
                    "caption": sc.get("caption"),
                })

            doc, doc_version = doc_repo._save_in_transaction(
                organization_id=organization_id,
                workflow_run_id=wf_run.id,
                expected_revision=0,
                script=proposal.script,
                scenes=transformed_scenes,
                actor_subject="creative_session_finalizer",
            )

            # 3. Bind workflow run to session
            sess.workflow_run_id = wf_run.id
            sess.revision += 1

            # Save Command Receipt
            result = {
                "workflow_run_id": str(wf_run.id),
                "creative_document_version_id": str(doc_version.id),
                "accepted_proposal_id": str(accepted_proposal_id),
            }
            receipt = CreativeCommandReceipt(
                organization_id=organization_id,
                session_id=session_id,
                operation_type="create_workflow_draft",
                idempotency_key=derived_receipt_key,
                request_fingerprint=hashlib.sha256(derived_receipt_key.encode()).hexdigest(),
                result_payload=result,
            )
            db_session.add(receipt)
            db_session.commit()

            return {
                "workflow_run_id": str(wf_run.id),
                "creative_document_version_id": str(doc_version.id),
                "idempotent_replay": False,
            }

    def _resolve_credentials(self, organization_id: uuid.UUID) -> Tuple[uuid.UUID | str, str, str]:
        """Resolves active vault credential priority or env fallbacks."""
        with self._session_maker() as db_session:
            # Query active credentials matching tenant org
            creds = db_session.scalars(
                select(ProviderCredential)
                .where(
                    ProviderCredential.organization_id == organization_id,
                    ProviderCredential.provider == "gemini",
                    ProviderCredential.status == "active",
                )
                .order_by(ProviderCredential.priority.asc())
            ).all()

            for c in creds:
                # Decrypt ciphertext
                try:
                    decrypted_secret = ProviderCredentialCipher.from_env().decrypt(c.secret_ciphertext)
                    # Resolve model name from credentials capabilities
                    model = c.capabilities.get("model") if c.capabilities else "gemini-2.5-flash"
                    return c.id, decrypted_secret, model
                except Exception as exc:
                    logger.error(f"Failed to decrypt credential {c.id}: {exc}")

            # Safe Env Fallbacks resolution check
            if self._env_fallback_enabled and self._env_fallback_key:
                logger.info("Credentials vault empty. Falling back to env credential.")
                return "env_fallback", self._env_fallback_key, "gemini-2.5-flash"

            raise ProviderUnavailable("No active provider key configuration details resolved.")

    def _resolve_prompts(self, organization_id: uuid.UUID) -> Tuple[str, int, str, int]:
        """Loads planner and director prompt instructions for the given organization."""
        with self._session_maker() as db_session:
            planner = db_session.scalar(
                select(PromptTemplate).where(
                    PromptTemplate.organization_id == organization_id,
                    PromptTemplate.prompt_key == "short_video_scene_planner",
                )
            )
            director = db_session.scalar(
                select(PromptTemplate).where(
                    PromptTemplate.organization_id == organization_id,
                    PromptTemplate.prompt_key == "short_video_visual_art_director",
                )
            )

            if not planner or not director:
                raise PromptBaselineUnavailable("Prompts baseline templates not configured in system.")

            # Fetch promoted versions
            planner_ver = db_session.scalar(
                select(PromptVersion).where(
                    PromptVersion.prompt_template_id == planner.id,
                    PromptVersion.version == planner.production_version,
                )
            )
            director_ver = db_session.scalar(
                select(PromptVersion).where(
                    PromptVersion.prompt_template_id == director.id,
                    PromptVersion.version == director.production_version,
                )
            )

            if not planner_ver or not director_ver:
                raise PromptBaselineUnavailable("Prompts production baseline version templates unpromoted.")

            return (
                planner_ver.content,
                planner_ver.version,
                director_ver.content,
                director_ver.version,
            )

    def _update_credential_usage(self, credential_id: uuid.UUID | str, failure_code: str | None) -> None:
        """Saves usage audits in a clean independent transaction."""
        if not isinstance(credential_id, uuid.UUID):
            return
        try:
            with self._session_maker() as audit_session:
                c = audit_session.get(ProviderCredential, credential_id)
                if c:
                    c.last_used_at = datetime.now(UTC)
                    c.last_failure_code = failure_code
                    audit_session.commit()
        except Exception as exc:
            logger.error(f"Failed to record usage audit for credential {credential_id}: {exc}")

    def _mark_turn_failed(self, turn_id: uuid.UUID, lease_token: uuid.UUID, failure_code: str) -> None:
        """Safely transitions active turns to failed state."""
        try:
            with self._session_maker() as db_session:
                turn = db_session.get(CreativeTurn, turn_id)
                if turn and turn.lease_token == lease_token and turn.status == "generating":
                    turn.status = "failed"
                    turn.failure_code = failure_code
                    db_session.commit()
        except Exception as exc:
            logger.error(f"Failed to mark turn {turn_id} as failed: {exc}")

    def _build_turn_completed_payload(self, session: Session, turn: CreativeTurn) -> dict:
        sess = session.get(CreativeSession, turn.session_id)
        msg = session.get(CreativeMessage, turn.assistant_message_id)
        proposal = session.get(CreativeProposal, turn.proposal_id)
        return {
            "session_id": str(sess.id),
            "revision": sess.revision,
            "assistant_message": msg.content if msg else "",
            "proposal": {
                "id": str(proposal.id),
                "state": proposal.state,
                "title": proposal.title,
                "brief": proposal.brief,
                "script": proposal.script,
                "scenes": proposal.scenes,
                "version": proposal.version,
                "trace_id": proposal.trace_id,
            }
        }

    def _save_completed_message_receipt(
        self,
        session: Session,
        organization_id: uuid.UUID,
        session_id: uuid.UUID,
        idempotency_key: str,
        fingerprint: str,
        payload: dict,
    ) -> None:
        receipt = CreativeCommandReceipt(
            organization_id=organization_id,
            session_id=session_id,
            operation_type="send_message",
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            result_payload=payload,
        )
        session.add(receipt)


def json_dump_canonical(obj: Any) -> str:
    """Produces sorted deterministic JSON keys string."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))
