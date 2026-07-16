"""Long-running VisionFlow Redis Streams consumer process."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from redis import Redis

# The Docker command invokes this file by path (``python
# worker/consume_visionflow_events.py``).  Make the repository root importable
# before loading ``worker.*`` modules so the same entrypoint works locally,
# inside the image, and in the bounded GitHub Actions runner.
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Consume VisionFlow short-form workflow events from Redis Streams."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Handle one bounded Redis read and exit; intended for the free GitHub Actions runner.",
    )
    parser.add_argument(
        "--block-ms",
        type=int,
        default=5_000,
        help="Maximum Redis blocking-read duration in milliseconds (default: 5000).",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Maximum stream messages read per iteration (default: 10).",
    )
    arguments = parser.parse_args()
    if arguments.block_ms < 0:
        parser.error("--block-ms must be zero or greater")
    if arguments.count < 1 or arguments.count > 50:
        parser.error("--count must be between 1 and 50")

    # Keep ``--help`` and argument validation independent of the media stack.
    # The actual consumer still fails closed if a required runtime dependency is
    # absent when it is asked to process work.
    from worker.application.visionflow_render_dispatcher import VisionFlowRenderDispatcher
    from worker.application.visionflow_render_workflow import VisionFlowRenderWorkflow
    from worker.application.visionflow_quality_assurance import VisionFlowQualityAssurance
    from worker.services.asset_service import AssetService
    from worker.services.media_service import MediaService
    from worker.services.visionflow_asset_preparer import VisionFlowAssetPreparer
    from worker.services.visionflow_control_plane_client import VisionFlowControlPlaneClient, VisionFlowWorkerSettings
    from worker.services.visionflow_event_consumer import VisionFlowEventConsumer, VisionFlowEventConsumerSettings
    from worker.services.visionflow_media_inspector import FfprobeMediaInspector
    from worker.services.visionflow_object_storage import S3CompatibleObjectStorage, VisionFlowObjectStorageSettings
    from worker.services.visionflow_render_assets import VisionFlowRenderAssetMaterializer
    from worker.services.visionflow_tts import VisionFlowTts
    from worker.services.visionflow_video_renderer import VisionFlowVideoRenderer

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
        render_dispatcher=VisionFlowRenderDispatcher(
            control_plane,
            render_workflow,
            VisionFlowQualityAssurance(control_plane, FfprobeMediaInspector(storage)),
        ),
    )
    consumer.ensure_group()
    if arguments.once:
        handled = consumer.consume_once(block_ms=arguments.block_ms, count=arguments.count)
        print(f"Handled {handled} VisionFlow stream event(s).")
        return
    while True:
        consumer.consume_once(block_ms=arguments.block_ms, count=arguments.count)


if __name__ == "__main__":
    main()
