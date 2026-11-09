# Pinned by digest (a multi-arch index); Dependabot proposes new digests.
FROM python:3.14-alpine@sha256:a18b20ad69e74df6cf6d2e1b1a260d7a1ecf5380fd83b310f83ba88c461cf894

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
# stay read-only. The upgrade picks up Alpine fixes newer than the pinned
# image.
RUN apk upgrade --no-cache \
 && apk add --no-cache tzdata su-exec

WORKDIR /app

# pip is only needed to install the requirements. Removing it keeps the
# libraries it bundles (urllib3, msgpack, ...) out of the image and out of
# vulnerability scans.
COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt \
 && pip uninstall --yes pip

COPY app.py healthcheck.py logging_setup.py wol.py ./
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# The container starts as root only so the entrypoint can switch to PUID:PGID
# before the relay runs. Broadcasting a UDP datagram needs no privileges, and
# the relay never runs as root.

EXPOSE 8099

# Asks on the address and port the relay really listens on (WOL_LISTEN_HOST,
# empty settings falling back to the defaults).
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "healthcheck.py"]

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "app.py"]
