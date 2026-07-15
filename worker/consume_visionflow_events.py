"""Long-running VisionFlow Redis Streams consumer process."""

from __future__ import annotations

from redis import Redis

from worker.application.visionflow_render_dispatcher import VisionFlowRenderDispatcher
from worker.application.visionflow_render_workflow import VisionFlowRenderWorkflow
from worker.services.asset_service import AssetService
from worker.services.media_service import MediaService
from worker.services.visionflow_asset_preparer import VisionFlowAssetPreparer
from worker.services.visionflow_control_plane_client import VisionFlowControlPlaneClient, VisionFlowWorkerSettings
from worker.services.visionflow_event_consumer import VisionFlowEventConsumer, VisionFlowEventConsumerSettings
from worker.services.visionflow_object_storage import S3CompatibleObjectStorage, VisionFlowObjectStorageSettings
from worker.services.visionflow_render_assets import VisionFlowRenderAssetMaterializer
from worker.services.visionflow_tts import VisionFlowTts
from worker.services.visionflow_video_renderer import VisionFlowVideoRenderer


def main() -> None:
    consumer_settings = VisionFlowEventConsumerSettings.from_env()
    control_plane = VisionFlowControlPlaneClient(VisionFlowWorkerSettings.from_env())
    storage = S3CompatibleObjectStorage(VisionFlowObjectStorageSettings.from_env())
    render_workflow = VisionFlowRenderWorkflow(
        control_plane,
        VisionFlowAssetPreparer(AssetService(), storage),
        VisionFlowVideoRenderer(
            storage,
            VisionFlowRenderAssetMaterializer(storage),
            VisionFlowTts(),
            MediaService(),
            workspace_root="/tmp",
        ),
    )
    consumer = VisionFlowEventConsumer(
        Redis.from_url(consumer_settings.redis_url, decode_responses=True),
        consumer_settings,
        control_plane,
        render_dispatcher=VisionFlowRenderDispatcher(control_plane, render_workflow),
    )
    consumer.ensure_group()
    while True:
        consumer.consume_once()


if __name__ == "__main__":
    main()
