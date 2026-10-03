# Pinned by digest (a multi-arch index); Dependabot proposes new digests.
FROM python:3.12-alpine@sha256:0687a6bc9716edc2a6ee0fbfb0f87e7ee358b262b67c9215de91bc9b2d38ba71

# image.source is what makes the GHCR package inherit the repository's
# visibility instead of staying private on its own.
LABEL org.opencontainers.image.source="https://github.com/Tom-Joad/wol-relay-container" \
      org.opencontainers.image.title="wol-relay-container" \
      org.opencontainers.image.description="HTTP relay that sends Wake-on-LAN magic packets" \
      org.opencontainers.image.licenses="MIT"

# PUID/PGID/TZ follow the linuxserver.io parameter names. Every setting here
# can be overridden at runtime.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WOL_LISTEN_PORT=8099 \
    PUID=1000 \
    PGID=1000 \
    TZ=Etc/UTC

# tzdata makes TZ work (log time stamps follow it); su-exec drops privileges
# to PUID:PGID. Numeric IDs need no passwd entry, so the root filesystem can
# stay read-only.
RUN apk add --no-cache tzdata su-exec

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

COPY app.py logging_setup.py wol.py ./
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# The container starts as root only so the entrypoint can switch to PUID:PGID
# before the relay runs. Broadcasting a UDP datagram needs no privileges, and
# the relay never runs as root.

EXPOSE 8099

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ['WOL_LISTEN_PORT']+'/health', timeout=3).status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "app.py"]
