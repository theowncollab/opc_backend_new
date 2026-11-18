# OPC backend on Google Cloud Run (see DEPLOY.md).
# Cloud Run sets $PORT; locally:  docker build -t opc-backend . && docker run -p 8080:8080 --env-file .env opc-backend
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so code-only changes rebuild quickly.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Don't run as root.
RUN useradd --create-home --uid 10001 opc && chown -R opc /app
USER opc

# One process is right for Cloud Run: it scales by adding instances, and
# FastAPI handles many requests at once inside each one.
# --proxy-headers: requests arrive through Cloudflare and Google's front end.
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips="*"
