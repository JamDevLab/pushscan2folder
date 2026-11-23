FROM python:3.12-slim

# Non-root user; the mounted /scans directory must be writable by it
# (use `docker run --user` or chown the host directory).
RUN useradd --create-home --uid 1000 scanner \
    && mkdir /scans \
    && chown scanner:scanner /scans

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ /app/src/

ENV PYTHONPATH=/app/src \
    PUSHSCAN_WEB_BIND=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    PUSHSCAN_OUTPUT=/scans \
    PUSHSCAN_WEB_PORT=8080 \
    PUSHSCAN_HEARTBEAT_FILE=/tmp/pushscan2folder.alive

VOLUME /scans
# Optional web page (PUSHSCAN_WEB=1)
EXPOSE 8080
USER scanner

# Healthy while the program reaches the printer (heartbeat file, see `health`).
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["python", "-m", "pushscan2folder", "health"]

ENTRYPOINT ["python", "-m", "pushscan2folder"]
CMD ["run"]
