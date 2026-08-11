FROM python:3.12-alpine

# image.source is what makes the GHCR package inherit the repository's
# visibility instead of staying private on its own.
LABEL org.opencontainers.image.source="https://github.com/Tom-Joad/wol-relay-container" \
      org.opencontainers.image.title="wol-relay-container" \
      org.opencontainers.image.description="HTTP relay that sends Wake-on-LAN magic packets" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WOL_LISTEN_PORT=8099

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

COPY app.py logging_setup.py wol.py ./

# Broadcasting a UDP datagram needs no elevated privileges.
RUN adduser -D -H -u 10001 relay
USER relay

EXPOSE 8099

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ['WOL_LISTEN_PORT']+'/health', timeout=3).status == 200 else 1)"

CMD ["python", "app.py"]
