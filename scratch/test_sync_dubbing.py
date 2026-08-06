import sys, os, uuid
sys.path.insert(0, "services/control-plane")

env_path = "services/control-plane/.env"
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip("'\"")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.infrastructure.models import Organization, VideoProject, WorkflowRun, MediaAsset

def sync_dubbing_job_to_control_plane(
    job_id: int,
    title: str,
    metadata: dict,
    state: str = "AI_PROCESSING",
    r2_object_key: str | None = None,
    byte_size: int = 0
) -> str:
    engine = create_engine(os.environ["DATABASE_URL"])
    with Session(engine) as session:
        org = session.scalars(select(Organization)).first()
        if not org:
            raise RuntimeError("No Organization found in Control Plane DB")

        # Check existing workflow run by legacy_job_id
        legacy_key = f"dub-{job_id}"
        wf = session.scalars(select(WorkflowRun).where(WorkflowRun.legacy_job_id == legacy_key)).first()

        if not wf:
            proj = VideoProject(
                organization_id=org.id,
                title=title[:240],
                brief=metadata.get("dub_source_url") or metadata.get("dub_source_path") or "AI Dubbing Video",
                format_profile="short_vertical",
                timezone="Asia/Bangkok"
            )
            session.add(proj)
            session.flush()

            wf = WorkflowRun(
                id=uuid.uuid4(),
                project_id=proj.id,
                state=state,
                idempotency_key=f"dub-idem-{job_id}-{uuid.uuid4().hex[:6]}",
                legacy_job_id=legacy_key,
                prompt_manifest=metadata,
                input_payload=metadata
            )
            session.add(wf)
            session.flush()
        else:
            wf.state = state
            wf.prompt_manifest = metadata

        if r2_object_key:
            asset = session.scalars(
                select(MediaAsset).where(
                    (MediaAsset.workflow_run_id == wf.id) | (MediaAsset.object_key == r2_object_key)
                )
            ).first()
            if not asset:
                asset = MediaAsset(
                    organization_id=org.id,
                    workflow_run_id=wf.id,
                    object_key=r2_object_key,
                    media_kind="final_export",
                    content_type="video/mp4",
                    byte_size=byte_size or 1048576,
                    checksum_sha256="0" * 64,
                    metadata_json={"source": "dubbing_strategy"}
                )
                session.add(asset)
            else:
                asset.workflow_run_id = wf.id
                asset.object_key = r2_object_key
                asset.byte_size = byte_size or asset.byte_size
            
            wf.state = "APPROVED"

        session.commit()
        return str(wf.id)

if __name__ == "__main__":
    test_wf_id = sync_dubbing_job_to_control_plane(
        job_id=999,
        title="[DUB] Test Video Lồng Tiếng AI",
        metadata={"dub_source_url": "https://v.douyin.com/test"},
        state="APPROVED",
        r2_object_key="visionflow/9897b8e6-2d1d-48da-b9d0-87384cc1f58d/exports/final.mp4",
        byte_size=64082504
    )
    print("Synced Dubbing Job to Control Plane Workflow ID:", test_wf_id)
