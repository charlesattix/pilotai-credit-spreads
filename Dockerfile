# Build from repo root:
#   docker build -f web_dashboard/Dockerfile -t pilotai-dashboard .
#
# Run locally (reads local DB files):
#   docker run -p 8000:8000 \
#     -v ~/projects/pilotai-credit-spreads:/app \
#     -e PILOTAI_ROOT=/app \
#     pilotai-dashboard
#
# Railway deployment: set PILOTAI_ROOT to wherever data is synced

FROM python:3.11-slim
# Cache bust: v3

WORKDIR /app

# Install system deps (sqlite3 built-in to python:slim)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer cache)
COPY web_dashboard/requirements.txt /app/web_dashboard/requirements.txt
RUN pip install --no-cache-dir -r web_dashboard/requirements.txt

# Copy the whole repo (web_dashboard + experiments/ + configs/ + data/)
# For Railway: mount or sync data/ separately
COPY . /app

# Non-root user
RUN useradd -m -u 1000 pilotai
RUN chown -R pilotai:pilotai /app
USER pilotai

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV PORT=8000

EXPOSE 8000

HEALTHCHECK NONE

CMD sh -c "exec uvicorn web_dashboard.app:app --host 0.0.0.0 --port ${PORT:-8000}"
