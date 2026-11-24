FROM node:22-bookworm-slim AS frontend
WORKDIR /app/orbit
COPY orbit/package*.json ./
RUN npm ci --omit=dev
COPY orbit/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM python:3.11-slim-bookworm
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY orbit_backend/requirements.txt /tmp/orbit-requirements.txt
RUN pip install --no-cache-dir -r /tmp/orbit-requirements.txt \
    && useradd --create-home orbit \
    && mkdir /data /models && chown orbit:orbit /data /models
COPY --from=frontend /app/orbit /app/orbit
COPY orbit_backend/ /app/orbit_backend/
COPY scripts/input_rgb_quality.py /app/scripts/input_rgb_quality.py
COPY LICENSE NOTICE start-container.sh /app/
ENV ORBIT_DATA_DIR=/data U2NET_HOME=/models ORBIT_ENABLE_GPU_JOBS=0 PYTHONUNBUFFERED=1 NEXT_TELEMETRY_DISABLED=1
USER orbit
EXPOSE 3000
ENTRYPOINT ["/bin/bash", "/app/start-container.sh"]
