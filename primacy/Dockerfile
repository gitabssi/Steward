# The state primacy agency's publisher — its own service, its own identity.
FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi uvicorn
COPY server.py /srv/server.py
EXPOSE 8091
CMD ["sh", "-c", "uvicorn server:app --app-dir /srv --host 0.0.0.0 --port ${PORT:-8091}"]
