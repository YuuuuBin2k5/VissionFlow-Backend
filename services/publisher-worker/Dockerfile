FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN addgroup --system visionflow && adduser --system --ingroup visionflow visionflow
COPY services/publisher-worker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/publisher-worker ./publisher-worker
USER visionflow
CMD ["python", "publisher-worker/consumer.py"]
