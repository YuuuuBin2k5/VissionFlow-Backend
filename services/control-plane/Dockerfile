FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system visionflow && adduser --system --ingroup visionflow visionflow

COPY services/control-plane/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/control-plane/alembic.ini ./alembic.ini
COPY services/control-plane/alembic ./alembic
COPY services/control-plane/app ./app
COPY worker/domain ./worker/domain
COPY worker/__init__.py ./worker/__init__.py
# Keep operational commands in the production image.  Render runs the outbox
# relay as a separate worker from this same immutable image.
COPY services/control-plane/scripts ./scripts
COPY services/control-plane/entrypoint.sh ./entrypoint.sh

USER visionflow

EXPOSE 8000
CMD ["sh", "entrypoint.sh"]
