FROM python:3.12-alpine

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
