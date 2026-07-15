# Use official Python lightweight slim runtime base image
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install system dependencies including ffmpeg for MoviePy video processing
# and clean up apt package cache to keep image footprint minimal
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set internal active working directory context
WORKDIR /app

RUN addgroup --system visionflow && adduser --system --ingroup visionflow visionflow

# Copy dependency manifest file
COPY worker/requirements.txt ./requirements.txt

# Install python dependencies matching package configurations without cache saving
RUN pip install --no-cache-dir -r requirements.txt

# Copy complete bot-worker codebase layouts into the worker subdirectory
COPY worker ./worker

RUN chown -R visionflow:visionflow /app
USER visionflow

# Execute video rendering orchestrator main entrypoint
CMD ["python", "worker/consume_visionflow_events.py"]
