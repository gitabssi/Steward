# steward-edge: self-hosted Gemma inside the OT boundary.
#
# The weights live in this container (Ollama), not behind an API — the
# entire justification is that raw SCADA data cannot leave the plant's
# network boundary, and an API call would defeat the property this
# service exists to demonstrate. Deployed as its own Cloud Run service
# (min-instances=0) representing the plant-side appliance.

FROM ollama/ollama:latest AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --break-system-packages fastapi uvicorn pydantic

ARG EDGE_MODEL=gemma4:e4b
ENV EDGE_MODEL=${EDGE_MODEL}

# Bake the weights into the image so cold starts don't pull gigabytes.
RUN ollama serve & sleep 4 && ollama pull ${EDGE_MODEL} && pkill ollama

COPY server.py /srv/server.py

ENV OLLAMA_HOST=http://localhost:11434
EXPOSE 8090

CMD ["sh", "-c", "ollama serve & sleep 3 && uvicorn server:app --app-dir /srv --host 0.0.0.0 --port ${PORT:-8090}"]
