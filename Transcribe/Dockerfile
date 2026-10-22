# Build context is the repo root (see docker-compose.yml).
# CPU build. For an NVIDIA GPU, switch the base to an nvidia/cuda ...-cudnn9-runtime image.
FROM python:3.12-slim
WORKDIR /srv

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models \
    DATA_DIR=/data

COPY Transcribe/requirements.txt .
RUN pip install -r requirements.txt

COPY Transcribe/worker.py .

RUN useradd -u 1000 -m appuser && mkdir /data /models && chown appuser /data /models
USER appuser

CMD ["python", "worker.py"]
