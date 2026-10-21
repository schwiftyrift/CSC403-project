# Build context is the repo root (see docker-compose.yml).
FROM python:3.12-slim
WORKDIR /srv
COPY Main/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY Main/main.py .
COPY Main/service ./service
COPY Main/static ./static
RUN useradd -u 1000 -m appuser && mkdir /data && chown appuser /data
USER appuser
ENV DATA_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
