"""Local contract/regression tests; these are NOT production UX acceptance."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_remote_render_integration import http_runtime, remote_pg_engine
from production.contracts import (AssetCandidate, AssetResolutionResult, SceneAssetResolution, VisualIntent,
    ProductionRun, AutoVideoRequest, EditorPlan, ScenePlan, ShotPlan)
from production.review_media import http_media, materialize_graphic, review_candidate, review_resolution


class Storage:
    def __init__(self): self.objects = {}
    def put_file(self, ref, path, mime): self.objects[ref] = (path.read_bytes(), mime)
    def presigned_download(self, ref): return 'https://media.example.test/' + ref


def candidate(name='asset', **values):
    return AssetCandidate(asset_id=name, source_id=name, provider='pexels_stock', duration_sec=10,
        media_url=f'https://media.example.test/{name}.mp4', thumbnail_url=f'https://media.example.test/{name}.jpg', **values)


@pytest.mark.parametrize('url', ['gfx_id', 'D:\\image.png', '/tmp/foo.png', 'file:///tmp/x', '/static/thumb.png'])
def test_never_expose_local_or_logical_preview(url):
    assert http_media(url) is None
    c = candidate(); c.thumbnail_url = url
    assert review_candidate(c).preview_url is None


def test_graphic_is_real_png_and_identical_render_source():
    storage = Storage()
    c = AssetCandidate(asset_id='gfx', source_id='gfx', provider='graphic_fallback', composite_score=.75)
    result = materialize_graphic(c, VisualIntent(scene_id='scene_1', description='Organize the desk into three work zones'), storage)
    assert result.renderable and result.graphic_spec
    assert result.media_url == result.preview_url == result.thumbnail_url
    data, mime = storage.objects[result.storage_ref]
    assert data.startswith(b'\x89PNG\r\n\x1a\n') and mime == 'image/png'
    assert result.composite_score == 0 and result.score_source is None


def test_graphic_failure_not_counted_as_covered():
    c = AssetCandidate(asset_id='gfx', source_id='gfx', provider='graphic_fallback', thumbnail_url='/static/missing.jpg', composite_score=.75)
    resolution = AssetResolutionResult(run_id='run_test', resolutions=[SceneAssetResolution(scene_id='scene_1', intent_id='vi', selected_candidate=c)])
    result = review_resolution(resolution)
    assert result.visual_coverage_ratio == 0
    assert result.resolutions[0].selected_candidate.composite_score == 0
    assert result.resolutions[0].selected_candidate.preview_error


@pytest.fixture
def review_run(tmp_path, monkeypatch):
    import importlib
    runs = importlib.import_module('production.repositories.run_repository')
    import production.remote_render as remote
    monkeypatch.setattr(runs, 'STORAGE_DIR', tmp_path)
    monkeypatch.setattr(runs.run_repository, '_runs', {})
    monkeypatch.setattr(remote, 'remote_render_enabled', lambda: False)
    first, alternate = candidate('first'), candidate('alternate')
    resolution = SceneAssetResolution(scene_id='scene_1', intent_id='vi', selected_candidate=first, alternate_candidates=[alternate])
    plan = EditorPlan(plan_id='plan', scenes=[ScenePlan(scene_id='scene_1', narration='Desk', shots=[
        ShotPlan(shot_id='shot_1', resolution_shot_order=1, asset_id='first', duration_sec=2), ShotPlan(shot_id='shot_2', resolution_shot_order=2, asset_id='unchanged', duration_sec=2)])])
    run = ProductionRun(id='run_review', request=AutoVideoRequest(request_id='test', instruction='Local regression'),
        resolved_assets=AssetResolutionResult(run_id='run_review', resolutions=[resolution]), editor_plan=plan)
    runs.run_repository.create(run)
    return run, runs.run_repository


def test_swap_and_lock_survive_repository_reload(review_run):
    from production.review_actions import swap, lock
    run, repo = review_run
    original = run.editor_plan.scenes[0].shots[1].model_dump()
    swap(run.id, 'scene_1', 1, 'alternate')
    lock(run.id, 'scene_1', 1, True)
    repo._runs.clear()
    saved = repo.get(run.id)
    assert saved.resolved_assets.resolutions[0].selected_candidate.asset_id == 'alternate'
    assert saved.editor_plan.scenes[0].shots[0].asset_id == 'alternate'
    assert saved.editor_plan.scenes[0].shots[0].is_locked
    assert saved.editor_plan.scenes[0].shots[1].model_dump() == original
    assert saved.manual_interventions[-1].intervention_source.value == 'REAL_OPERATOR'
    with pytest.raises(ValueError, match='khóa'): swap(run.id, 'scene_1', 1, 'first')
    lock(run.id, 'scene_1', 1, False)
    repo._runs.clear()
    assert not repo.get(run.id).resolved_assets.resolutions[0].selected_candidate.is_locked


def test_playback_requires_real_artifact(review_run):
    from production.production_controller import _handle_playback
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error: _handle_playback(review_run[0].id)
    assert error.value.status_code == 409


def test_pexels_missing_key_cannot_return_catalog(monkeypatch):
    from production.asset_resolver import PexelsStockAdapter
    adapter = PexelsStockAdapter(); adapter.api_key = ''
    monkeypatch.setattr(adapter, '_match_thematic_catalog', lambda *a: pytest.fail('No fabricated stock'))
    with pytest.raises(RuntimeError, match='PEXELS_NOT_CONFIGURED'):
        asyncio.run(adapter._fetch_pexels_or_fallback('desk', 5, True))


def test_live_tts_failure_never_fabricates_audio(tmp_path, monkeypatch):
    from production.tts_service import EdgeTTSVoiceProvider
    monkeypatch.delenv('VISIONFLOW_ALLOW_TEST_TTS', raising=False)
    provider = EdgeTTSVoiceProvider()
    async def fail(**kwargs): raise RuntimeError('provider unavailable')
    monkeypatch.setattr(provider._provider, 'synthesize', fail)
    with pytest.raises(RuntimeError, match='TTS_PROVIDER_UNAVAILABLE'):
        asyncio.run(provider.synthesize_narration('scene', 'test', 'vi-VN-HoaiMyNeural', 1, tmp_path))
    assert not list(tmp_path.iterdir())


def test_voice_retiming_preserves_all_choices_and_locks():
    from production.contracts import ScriptPlan, SceneNarration
    from production.editor_planner import editor_planner
    from production.tts_service import SceneTTSResult
    resolutions = [SceneAssetResolution(scene_id='scene', shot_order=i, intent_id=f'vi{i}',
        selected_candidate=candidate(f'choice{i}', is_locked=(i == 2))) for i in range(1, 4)]
    plan = editor_planner.build_final_editor_plan(
        ScriptPlan(title='Test', full_script='Test', scenes=[SceneNarration(scene_id='scene', scene_index=1, narration='Test')]),
        AssetResolutionResult(run_id='test', resolutions=resolutions),
        [SceneTTSResult(scene_id='scene', audio_asset_id='audio', audio_file_path='test-only.wav', actual_duration_seconds=1.5,
            provider='test-only', voice_code='test-only', voice_rate=1)], preserve_visual_choices=True)
    assert [s.asset_id for s in plan.scenes[0].shots] == ['choice1', 'choice2', 'choice3']
    assert plan.scenes[0].shots[1].is_locked
    assert plan.duration_seconds == 1.5


def test_render_saved_timeline_idempotent_and_new_revision(http_runtime):
    from test_remote_render_integration import make_run
    from production.review_actions import render_review, edit_run
    from production.production_controller import _handle_get_run
    from sqlalchemy import select, func
    from sqlalchemy.orm import Session
    from app.infrastructure.models import RenderJob
    run, initial, _, _ = make_run(http_runtime)
    assert render_review(run.id)['job_id'] == str(initial)
    with edit_run(run.id, invalidate=True): pass
    assert _handle_get_run(run.id).review_revision == 1
    first = render_review(run.id)
    assert first['job_id'] != str(initial)
    assert render_review(run.id)['job_id'] == first['job_id']
    with Session(http_runtime.engine) as db:
        assert db.scalar(select(func.count()).select_from(RenderJob).where(RenderJob.run_id == run.id)) == 2


def test_review_run_sanitizes_visual_paths_without_changing_internal_plan(review_run):
    from production.production_controller import _handle_review_run
    run, repo = review_run
    run.editor_plan.scenes[0].shots[0].asset_file_path = 'D:/private/image.png'
    run.editor_plan.scenes[0].shots[0].thumbnail_url = '/tmp/image.png'
    response = _handle_review_run(run.id)
    assert response.editor_plan.scenes[0].shots[0].asset_file_path is None
    assert response.editor_plan.scenes[0].shots[0].thumbnail_url is None
    assert repo.get(run.id).editor_plan.scenes[0].shots[0].asset_file_path == 'D:/private/image.png'


def test_condensed_plan_mapping_never_edits_the_wrong_shot(review_run):
    from production.review_actions import plan_shot
    run, _ = review_run
    run.editor_plan.scenes[0].shots[1].resolution_shot_order = 3
    assert plan_shot(run, 'scene_1', 3).asset_id == 'unchanged'
    with pytest.raises(ValueError, match='gộp'):
        plan_shot(run, 'scene_1', 2)


def test_browser_real_local_http_review_and_playback(http_runtime, monkeypatch):
    import os, subprocess, json
    if os.getenv('VISIONFLOW_RUN_BROWSER_TESTS') != '1':
        pytest.skip('Opt-in real Chrome integration; not production acceptance')
    from test_remote_render_integration import make_run, config
    from production.production_controller import router, _handle_get_run
    from production.review_actions import edit_run
    from production.remote_render import enqueue_remote_render
    from production.render_handoff import render_handoff
    from worker.remote_render_worker import RemoteRenderWorker
    from fastapi.responses import HTMLResponse, Response
    from sqlalchemy.orm import Session
    runtime = http_runtime
    run, _, source, _ = make_run(runtime)
    graphic = materialize_graphic(AssetCandidate(asset_id='graphic_preview', source_id='graphic', provider='graphic_fallback', duration_sec=2),
        VisualIntent(scene_id='scene_1', description='Local integration: a desk organized into three zones'), runtime.storage)
    ref = 'visionflow/production/review/local-source.mp4'
    runtime.storage.put_file(ref, source, 'video/mp4')
    first = candidate('first'); first.storage_ref = ref; first.thumbnail_url = graphic.preview_url
    with edit_run(run.id) as editable:
        editable.resolved_assets = AssetResolutionResult(run_id=run.id, resolutions=[SceneAssetResolution(
            scene_id='scene_1', intent_id='vi', selected_candidate=first, alternate_candidates=[graphic])])
    runtime.app.router.routes[:] = [r for r in runtime.app.router.routes if getattr(r, 'path', '') not in {
        '/api/v1/production/runs/{run_id}', '/api/v1/production/runs/{run_id}/video'}]
    runtime.app.include_router(router, prefix='/api/v1')
    frontend = Path(__file__).resolve().parents[2] / 'VisionFlow_Client'
    bundle = runtime.tmp / 'review.js'
    subprocess.run(['node', str(frontend / 'node_modules/esbuild/bin/esbuild'), str(frontend / 'tests/review-harness.tsx'),
        '--bundle', '--format=esm', '--loader:.tsx=tsx', '--outfile=' + str(bundle),
        '--define:import.meta.env=' + json.dumps({'VITE_VISIONFLOW_API_URL': runtime.base + '/api/v1'})],
        cwd=frontend, check=True, capture_output=True)
    @runtime.app.get('/review.js')
    def javascript(): return Response(bundle.read_bytes(), media_type='text/javascript')
    @runtime.app.get('/review-test')
    def html(): return HTMLResponse('<div id="root"></div><script type="module" src="/review.js"></script>')
    command = ['node', str(frontend / 'tests/review-browser.mjs'), runtime.base + '/review-test?run_id=' + run.id]
    result = subprocess.run(command + ['review'], cwd=frontend, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)
    if os.getenv('VISIONFLOW_TEST_LIVE_TTS') == '1':
        from production.contracts import ScriptPlan, SceneNarration
        monkeypatch.delenv('VISIONFLOW_ALLOW_TEST_TTS', raising=False)
        with edit_run(run.id) as editable:
            editable.script_plan = ScriptPlan(title='Local voice integration', full_script='Sắp xếp bàn làm việc gọn gàng.',
                scenes=[SceneNarration(scene_id='scene_1', scene_index=1, narration='Sắp xếp bàn làm việc gọn gàng.')])
        result = subprocess.run(command + ['voice'], cwd=frontend, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        print(result.stdout)
        saved = _handle_get_run(run.id)
        assert saved.request.overrides['voice_code'].startswith('vi-')
        assert saved.editor_plan.scenes[0].actual_duration_seconds > 0
        assert saved.resolved_assets.resolutions[0].selected_candidate.is_locked
    edited = _handle_get_run(run.id)
    spec = render_handoff.build_spec(edited.editor_plan, run.id, strict_inputs=True)
    # Loopback URLs are deliberately rejected by production SSRF guards.
    # Materialize the identical test-store raster, without weakening those guards.
    raster = runtime.tmp / 'selected-graphic.png'
    runtime.storage.download_to(edited.resolved_assets.resolutions[0].selected_candidate.storage_ref, raster)
    spec.video_sources[0]['file_path'] = str(raster)
    spec.width, spec.height = 360, 640
    with Session(runtime.engine) as db:
        enqueue_remote_render(edited, session=db, storage=runtime.storage, spec=spec)
    worker = RemoteRenderWorker(config(runtime))
    try: assert worker.run_once()
    finally: worker.shutdown()
    result = subprocess.run(command + ['play'], cwd=frontend, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)
