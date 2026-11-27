# ClipForge's TikTok token broker. Holds TikTok's client secret; keeps nothing else.
FROM python:3.12-slim
WORKDIR /broker
COPY requirements.txt app.py ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --system broker
USER broker
ENV PORT=8080
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT} --no-access-log"]
