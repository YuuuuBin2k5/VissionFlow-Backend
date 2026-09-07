FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system visionflow && adduser --system --ingroup visionflow visionflow

COPY services/control-plane/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core && rm -rf /var/lib/apt/lists/*

COPY services/control-plane/alembic.ini ./alembic.ini
COPY services/control-plane/alembic ./alembic
COPY services/control-plane/app ./app
COPY worker/domain ./worker/domain
COPY worker/__init__.py ./worker/__init__.py
COPY worker/voice_system ./worker/voice_system
COPY worker/services ./worker/services
COPY production ./production
COPY worker/config ./worker/config
# Keep operational commands in the production image.  Render runs the outbox
# relay as a separate worker from this same immutable image.
COPY services/control-plane/scripts ./scripts
COPY services/control-plane/entrypoint.sh ./entrypoint.sh

# Production compatibility repositories/media caches create local directories.
# Remote job snapshots and artifacts remain PostgreSQL/R2 authoritative.
RUN chown -R visionflow:visionflow /app

USER visionflow

EXPOSE 8000
CMD ["sh", "entrypoint.sh"]
