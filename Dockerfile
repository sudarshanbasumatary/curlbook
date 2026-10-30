FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CURLBOOK_DATA_DIR=/data \
    CURLBOOK_LOCALHOST_ALIAS=host.docker.internal \
    PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN useradd --uid 1000 --create-home curlbook \
    && mkdir -p /data \
    && chown -R curlbook:curlbook /data \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

VOLUME ["/data"]
EXPOSE 8080

# The entrypoint fixes /data ownership on bind mounts, then drops to the 'curlbook' user.
ENTRYPOINT ["docker-entrypoint.sh"]
# Single worker so the in-process file lock serialises writes to store.json;
# threads give concurrency for slow upstream requests.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 8 --timeout 300 --access-logfile - server:app"]
