FROM python:3.12-alpine

# iputils gives a ping that works with the NET_RAW capability Docker grants by
# default; busybox ping is fine too but this one reports failures more clearly.
RUN apk add --no-cache iputils

WORKDIR /app
COPY app/ /app/

ENV WOL_WEB_PORT=8055 \
    WOL_CONFIG_DIR=/config \
    PYTHONUNBUFFERED=1

VOLUME ["/config"]
EXPOSE 8055

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python3 -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('WOL_WEB_PORT','8055'),timeout=4)"

CMD ["python3", "server.py"]
