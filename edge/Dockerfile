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

# E2B is the default because this container runs on Cloud Run's CPU,
# where E4B's first token exceeds a request's lifetime. Both are Gemma 4
# edge models with native audio, and the property this service exists to
# demonstrate — that raw plant data never crosses the OT boundary — is
# identical either way. A real appliance carries an accelerator and runs
# E4B: build with --build-arg EDGE_MODEL=gemma4:e4b.
ARG EDGE_MODEL=gemma4:e2b
ENV EDGE_MODEL=${EDGE_MODEL}

# Bake the weights into the image so cold starts don't pull gigabytes.
RUN ollama serve & sleep 4 && ollama pull ${EDGE_MODEL} && pkill ollama

COPY server.py /srv/server.py

ENV OLLAMA_HOST=http://localhost:11434
EXPOSE 8090

# The base image sets ENTRYPOINT ["/bin/ollama"], which would swallow the
# command below — reset it so the edge appliance boots both processes.
ENTRYPOINT []
CMD ["/bin/sh", "-c", "ollama serve & sleep 3 && uvicorn server:app --app-dir /srv --host 0.0.0.0 --port ${PORT:-8090}"]
