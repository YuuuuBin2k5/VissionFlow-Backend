"""Scoped human review edits; never runs research, script generation or publishing."""
from contextlib import contextmanager
from production.contracts import ManualInterventionRecord, InterventionSource, ProductionRunStatus
from production.repositories.run_repository import run_repository


def guard_review_transaction(db, run_id):
    from sqlalchemy import text
    if not db.scalar(text('SELECT pg_try_advisory_xact_lock(hashtextextended(:run_id, 0))'), {'run_id': run_id}):
        raise ValueError('Một thao tác khác đang cập nhật run. Vui lòng thử lại.')


@contextmanager
def edit_run(run_id, invalidate=False):
    from production.remote_render import remote_render_enabled
    from production.production_controller import _handle_get_run
    db = job = None
    try:
        if remote_render_enabled():
            from sqlalchemy import select
            from sqlalchemy.orm import Session
            from app.infrastructure.database import get_engine
            from app.infrastructure.models import RenderJob
            db = Session(get_engine())
            guard_review_transaction(db, run_id)
            job = db.scalar(select(RenderJob).where(RenderJob.run_id == run_id).order_by(RenderJob.created_at.desc()).limit(1).with_for_update())
            if job and job.status in {'CLAIMED', 'DOWNLOADING', 'RENDERING', 'UPLOADING'}:
                raise ValueError('Worker đang xử lý. Chờ render hoàn tất trước khi sửa visual/voice.')
        run = _handle_get_run(run_id).model_copy(deep=True)
        yield run
        if invalidate:
            run.review_revision += 1
            run.render_artifact = None
            run.output_video_url = None
            run.quality_report = None
            run.human_review = None
            run.status = ProductionRunStatus.EDITOR_PLAN_READY
            run.error_message = None
            run.quality_score = None
            run.current_stage = 'editor_plan'
            if job and job.status in {'WAITING_FOR_WORKER', 'QUEUED', 'RETRYING'}:
                job.status = 'CANCELLED'
                job.retryable = False
        if job:
            job.render_spec_json = {**job.render_spec_json, 'run_snapshot': run.model_dump(mode='json')}
            db.commit()
        run_repository.update(run)
    finally:
        if db:
            db.close()


def intervention(run, kind, description):
    run.manual_interventions.append(ManualInterventionRecord(run_id=run.id, intervention_type=kind,
        intervention_source=InterventionSource.REAL_OPERATOR, description=description, operator_id='operator'))


def resolution_for(run, scene_id, shot_order):
    result = next((r for r in run.resolved_assets.resolutions if r.scene_id == scene_id and r.shot_order == shot_order), None) if run.resolved_assets else None
    if not result:
        raise ValueError('Không tìm thấy shot')
    return result


def plan_shot(run, scene_id, shot_order):
    if not run.editor_plan:
        return None
    scene = next((s for s in run.editor_plan.scenes if s.scene_id == scene_id), None)
    if not scene:
        raise ValueError('Shot không có trong timeline hiện tại')
    if any(s.resolution_shot_order is not None for s in scene.shots):
        shot = next((s for s in scene.shots if s.resolution_shot_order == shot_order), None)
    else:
        # Legacy snapshots have positional mapping only. Refuse ambiguous condensed plans.
        count = sum(r.scene_id == scene_id for r in run.resolved_assets.resolutions)
        shot = scene.shots[shot_order - 1] if count == len(scene.shots) and 0 < shot_order <= len(scene.shots) else None
    if shot is None:
        raise ValueError('Shot đã được gộp trong timeline cũ. Tạo lại voice/timing để cập nhật mapping trước khi đổi.')
    return shot


def apply_selection(run, resolution):
    candidate = resolution.selected_candidate
    if not candidate:
        return
    from production.review_media import review_candidate
    candidate = review_candidate(candidate)
    if not candidate.renderable:
        raise ValueError('Visual không có media/preview hợp lệ')
    resolution.selected_candidate = candidate
    if run.editor_plan:
        shot = plan_shot(run, resolution.scene_id, resolution.shot_order)
        if shot:
            if candidate.asset_type != 'GRAPHIC' and candidate.duration_sec < shot.duration_sec:
                raise ValueError('Visual ngắn hơn thời lượng shot; chọn candidate khác')
            shot.asset_id, shot.source_id, shot.provider = candidate.asset_id, candidate.source_id, candidate.provider
            shot.media_url, shot.thumbnail_url, shot.asset_file_path = candidate.media_url, candidate.preview_url, None
            shot.resolved_asset = candidate.model_copy(deep=True)
            shot.is_locked = candidate.is_locked
            shot.is_graphic_fallback = candidate.provider == 'graphic_fallback'
            shot.fallback_policy = None
            shot.match_score = candidate.composite_score
            shot.asset_trim_start = shot.asset_start_sec = candidate.start_sec
            shot.asset_trim_end = shot.asset_end_sec = candidate.start_sec + shot.duration_sec


def swap(run_id, scene_id, shot_order, asset_id):
    with edit_run(run_id, invalidate=True) as run:
        result = resolution_for(run, scene_id, shot_order)
        if result.selected_candidate and result.selected_candidate.is_locked:
            raise ValueError('Mở khóa visual trước khi đổi')
        selected = next((c for c in result.alternate_candidates if c.asset_id == asset_id), None)
        if not selected:
            raise ValueError('Candidate không còn khả dụng; hãy tìm lại')
        old = result.selected_candidate
        result.selected_candidate = selected.model_copy(deep=True)
        result.alternate_candidates = [c for c in result.alternate_candidates if c.asset_id != asset_id]
        if old:
            result.alternate_candidates.insert(0, old)
        apply_selection(run, result)
        intervention(run, 'visual_changed', f'Selected visual for {scene_id}/{shot_order}')
    return result


def lock(run_id, scene_id, shot_order, locked):
    with edit_run(run_id) as run:
        result = resolution_for(run, scene_id, shot_order)
        if not result.selected_candidate:
            raise ValueError('Shot chưa có visual để khóa')
        result.selected_candidate.is_locked = locked
        if run.editor_plan:
            shot = plan_shot(run, scene_id, shot_order)
            if shot:
                shot.is_locked = locked
                if shot.resolved_asset:
                    shot.resolved_asset.is_locked = locked
        intervention(run, 'asset_locked', f'Visual lock={locked} for {scene_id}/{shot_order}')
    return result


async def resolve_shot(run_id, scene_id, shot_order):
    from production.asset_resolver import asset_resolver
    with edit_run(run_id) as run:
        result = resolution_for(run, scene_id, shot_order)
        if result.selected_candidate and result.selected_candidate.is_locked:
            raise ValueError('Mở khóa visual trước khi tìm lại')
        if not run.visual_plan:
            raise ValueError('Chưa có VisualPlan')
        plan = run.visual_plan.model_copy(deep=True)
        plan.intents = [v for v in plan.intents if v.scene_id == scene_id and v.shot_order == shot_order]
        if not plan.intents:
            raise ValueError('Không tìm thấy VisualIntent')
        # Refresh search cache only for this query; do not regenerate upstream plans.
        query = plan.intents[0].search_query_en.lower()
        for key in list(asset_resolver.stock_adapter._cache):
            if key.startswith(f'pex:{query}:'):
                asset_resolver.stock_adapter._cache.pop(key, None)
        fresh = await asset_resolver.resolve_visual_plan(plan, user_sources=run.request.sources, run_id=run_id)
        found = fresh.resolutions[0]
        candidates = ([found.selected_candidate] if found.selected_candidate else []) + found.alternate_candidates
        result.alternate_candidates = [c for c in candidates if not result.selected_candidate or c.asset_id != result.selected_candidate.asset_id]
        result.warnings, result.retrieval_diagnostics = found.warnings, found.retrieval_diagnostics
        intervention(run, 'visual_changed', f'Resolved replacement candidates for {scene_id}/{shot_order}')
    return result


async def voices():
    import asyncio
    import edge_tts
    entries = await asyncio.wait_for(edge_tts.list_voices(), timeout=20)
    return [{'code': v['ShortName'], 'label': v.get('FriendlyName', v['ShortName']), 'locale': v['Locale']}
            for v in entries if v.get('Locale', '').startswith('vi-')]


async def change_voice(run_id, voice_code):
    from production.tts_service import tts_service, measure_audio_duration_ffprobe
    from production.editor_planner import editor_planner
    available = await voices()
    if voice_code not in {v['code'] for v in available}:
        raise ValueError('Voice không khả dụng từ TTS provider')
    with edit_run(run_id, invalidate=True) as run:
        if not run.script_plan or not run.resolved_assets:
            raise ValueError('Chưa có script/visual để tạo voice')
        results = await tts_service.synthesize_script(scenes=run.script_plan.scenes, voice_code=voice_code, run_id=run_id)
        if any(r.provider != 'edge_tts' for r in results):
            raise ValueError('TTS provider không trả audio thật')
        for result in results:
            result.actual_duration_seconds = measure_audio_duration_ffprobe(result.audio_file_path)
        # Preserve asset choices/locks through duration-based downstream rebuild.
        old_music = run.editor_plan.audio_track.music_clip if run.editor_plan and run.editor_plan.audio_track else None
        run.editor_plan = editor_planner.build_final_editor_plan(script_plan=run.script_plan,
            resolved_assets=run.resolved_assets, tts_results=results, visual_plan=run.visual_plan, run_id=run_id,
            bgm_asset_url=old_music.file_path if old_music else None, preserve_visual_choices=True)
        if old_music and run.editor_plan.audio_track and run.editor_plan.audio_track.music_clip:
            run.editor_plan.audio_track.music_clip.volume = old_music.volume
            run.editor_plan.audio_track.music_clip.ducking_factor = old_music.ducking_factor
        run.request.overrides = {**run.request.overrides, 'voice_code': voice_code}
        intervention(run, 'voice_regenerated', f'Selected TTS voice {voice_code}')
    return run.editor_plan


def render_review(run_id):
    """Explicit operator render of the saved timeline, never an upstream re-run."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from app.infrastructure.database import get_engine
    from app.infrastructure.models import RenderJob
    from production.production_controller import _handle_get_run
    from production.remote_render import remote_render_enabled, enqueue_remote_render
    if not remote_render_enabled():
        raise ValueError('Remote local renderer chưa được cấu hình')
    with Session(get_engine()) as db:
        guard_review_transaction(db, run_id)
        latest = db.scalar(select(RenderJob).where(RenderJob.run_id == run_id).order_by(RenderJob.created_at.desc()).limit(1).with_for_update())
        if latest and latest.status in {'WAITING_FOR_WORKER', 'QUEUED', 'RETRYING', 'CLAIMED', 'DOWNLOADING', 'RENDERING', 'UPLOADING'}:
            return {'job_id': str(latest.id), 'status': latest.status}
        run = _handle_get_run(run_id).model_copy(deep=True)
        if run.render_artifact:
            raise ValueError('Bản render đã tồn tại. Chỉ render lại sau khi sửa timeline.')
        if not run.editor_plan or not run.editor_plan.is_render_ready:
            raise ValueError('Timeline chưa sẵn sàng. Chọn visual và tạo audio thật trước.')
        job = enqueue_remote_render(run, session=db)
        return {'job_id': str(job.id), 'status': job.status}
