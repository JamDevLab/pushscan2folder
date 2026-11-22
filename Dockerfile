FROM python:3.12-slim

# Non-root user; the mounted /scans directory must be writable by it
# (use `docker run --user` or chown the host directory).
RUN useradd --create-home --uid 1000 scanner \
    && mkdir /scans \
    && chown scanner:scanner /scans

WORKDIR /app
COPY src/ /app/src/

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PUSHSCAN_OUTPUT=/scans

VOLUME /scans
# Optional web page (PUSHSCAN_WEB=1)
EXPOSE 8080
USER scanner

ENTRYPOINT ["python", "-m", "pushscan2folder"]
CMD ["run"]
