import os
import sys
import uuid
from typing import Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.infrastructure.models import Organization, VideoProject, WorkflowRun, MediaAsset


def sync_dubbing_job_to_control_plane(
    job_id: int,
    title: str,
    metadata: dict,
    state: str = "AI_PROCESSING",
    r2_object_key: Optional[str] = None,
    byte_size: int = 0
) -> str:
    """
    Synchronizes a legacy MySQL dubbing job into the Control Plane PostgreSQL database
    (VideoProject + WorkflowRun + MediaAsset).

    This bridges AI Dubbing jobs so they automatically appear across:
      - Control Tower (Workflows API)
      - Review Queue (/review-queue)
      - Publication Queue (/publication-queue)
      - Content Scheduler (Calendar / List)
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url and os.path.exists("services/control-plane/.env"):
        with open("services/control-plane/.env") as f:
            for line in f:
                if line.startswith("DATABASE_URL="):
                    db_url = line.strip().split("=", 1)[1].strip("'\"")

    if not db_url:
        return ""

    engine = create_engine(db_url)
    with Session(engine) as session:
        org = session.scalars(select(Organization)).first()
        if not org:
            return ""

        legacy_key = f"dub-{job_id}"
        wf = session.scalars(select(WorkflowRun).where(WorkflowRun.legacy_job_id == legacy_key)).first()

        clean_title = (title or metadata.get("original_video_title") or "Video Lồng Tiếng AI")[:240]
        if "#Shorts" not in clean_title and "#shorts" not in clean_title:
            clean_title = (clean_title[:230] + " #Shorts") if len(clean_title) > 230 else (clean_title + " #Shorts")

        if not wf:
            proj = VideoProject(
                organization_id=org.id,
                title=clean_title,
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
