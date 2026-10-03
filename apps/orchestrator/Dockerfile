# Agentmetry recorder in one image: the orchestrator API, serving the dashboard's
# static export. Build from the repository root:
#
#   docker build -f apps/orchestrator/Dockerfile -t agentmetry .
#
# It used to start `uvicorn api.main:app`, a module path that has not existed
# since the package became `agentmetry`, so the image could not boot. It also
# installed gcc and libpq for a Postgres the recorder no longer uses.

FROM node:20-alpine AS dashboard
WORKDIR /dashboard
COPY apps/dashboard/package.json apps/dashboard/package-lock.json ./
RUN npm ci
COPY apps/dashboard/ ./
# Same-origin build: the dashboard talks to the API that serves it. No API key
# is baked into the bundle.
ENV NEXT_PUBLIC_SAME_ORIGIN=true
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

COPY apps/orchestrator/ ./
RUN pip install --no-cache-dir . \
    && useradd --system --uid 10001 --home-dir /data agentmetry \
    && mkdir -p /data && chown agentmetry /data

# agentmetry/api/main.py serves <three levels up>/dashboard/out.
COPY --from=dashboard /dashboard/out /dashboard/out

ENV AGENTMETRY_AUDIT_EXPORT_PATH=/data/audit-forward.jsonl \
    AGENTMETRY_AUDIT_DB_PATH=/data/audit.db \
    AGENTMETRY_DETECTION_LIVE_DB_PATH=/data/detection_live.db \
    AGENTMETRY_DETECTION_DISPOSITION_DB_PATH=/data/detection_dispositions.db

USER agentmetry
VOLUME ["/data"]
EXPOSE 8000

# 0.0.0.0 inside the container is required for port publishing to work; the
# compose file publishes it on the host's loopback only.
CMD ["uvicorn", "agentmetry.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
