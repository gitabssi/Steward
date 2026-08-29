# Steward — one command to run, one command to deploy.
#
#   make install      dependencies (fleet + console)
#   make dev          the whole product locally: fleet API :8000,
#                     primacy publisher :8091, console :5173
#   make test         unit + policy tests
#   make data         pull the EPA record, prepare, load to BigQuery
#   make backtest     run the three-step backtest (writes `finding`)
#   make deploy       fleet → Agent Runtime via agents-cli
#   make deploy-run   fleet (console included) → Cloud Run
#   make deploy-all   fleet + primacy publisher + Gemma edge → Cloud Run
#
# Every cloud command uses Application Default Credentials — no keys.

PROJECT ?= $(shell gcloud config get-value project 2>/dev/null)
REGION ?= us-central1
BQ_DATASET ?= steward_npdes
MODEL_ARMOR_TEMPLATE ?= steward-inbound
# The Memory Bank partition key. Identical on Agent Runtime and Cloud Run
# or the two surfaces keep separate banks and nothing carries across.
MEMORY_SCOPE ?= cedar-ridge-operator
# Set ENGINE=projects/…/reasoningEngines/N to bind Memory Bank; see
# `make memory-bank`, which resolves it for you after the first deploy.
ENGINE ?=

.PHONY: install dev dev-console console replay test test-all data backtest deploy deploy-run deploy-all lint

install:
	uv sync --all-groups --extra lint
	cd console && npm install --no-fund --no-audit

# One command, one URL: the fleet serves the built console at
# http://localhost:8000/console/ alongside /api, /a2a and ADK's dev UI.
# The state primacy agency runs as its own service on :8091, so the
# cross-department registry resolve is a real network call.
dev: console
	@trap 'kill 0' EXIT; \
	uv run --no-project --with fastapi,uvicorn uvicorn server:app \
	  --app-dir primacy --port 8091 & \
	sleep 2; \
	echo "→ console  http://localhost:8000/console/"; \
	echo "→ ledger   http://localhost:8000/api/events"; \
	PRIMACY_AGENCY_ENDPOINT=http://localhost:8091 \
	  STEWARD_FAULT_INJECTION=stale_lab_context \
	  uv run uvicorn app.fast_api_app:app --port 8000

console:
	cd console && npm install --no-fund --no-audit --silent && npm run build

# Replay a shift from the top. `make replay SPEED=fast|demo|real`.
replay: console
	scripts/replay.sh $(SPEED)

# Hot-reloading console against a running `make dev` (Vite on :5173).
dev-console:
	cd console && npm run dev

# The fences, verified with no cloud project and no credentials.
test:
	uv run pytest tests/unit -q

# Adds the live-agent checks; needs ADC and a project.
test-all:
	uv run pytest tests/unit -q
	GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_LOCATION=global \
	  uv run pytest tests/integration -q

lint:
	uv run ruff check app fixtures data edge primacy

data:
	python3 data/pull_epa.py
	python3 data/prepare_dmrs.py
	python3 data/prepare_permits.py
	uv run --with google-cloud-bigquery python data/load_bigquery.py

backtest:
	bq --project_id=$(PROJECT) query --use_legacy_sql=false < data/sql/01_series.sql
	bq --project_id=$(PROJECT) query --use_legacy_sql=false < data/sql/02_forecast.sql
	bq --project_id=$(PROJECT) query --use_legacy_sql=false < data/sql/03_finding.sql

# Every deploy target passes the same environment, because a deploy
# command that does not reproduce the system it documents is worse than
# no command at all. Two values here are load-bearing and easy to get
# wrong:
#   GOOGLE_CLOUD_LOCATION=global   Gemini 3.x serves from `global`, not
#                                  from $(REGION). Setting it regionally
#                                  makes every model call 404.
#   MODEL_ARMOR_LOCATION=$(REGION) Model Armor is regional and has its
#                                  own endpoint. Without its own
#                                  variable it would inherit `global`
#                                  above and quietly fall back to the
#                                  local screener.
#   STEWARD_MEMORY_BANK_LOCATION   third instance of the same trap: Memory
#                                  Bank is regional too, so it cannot
#                                  inherit `global` either.
FLEET_ENV = GOOGLE_GENAI_USE_VERTEXAI=true \
  GOOGLE_CLOUD_PROJECT=$(PROJECT) \
  GOOGLE_CLOUD_LOCATION=global \
  MODEL_ARMOR_LOCATION=$(REGION) \
  MODEL_ARMOR_TEMPLATE=$(MODEL_ARMOR_TEMPLATE) \
  STEWARD_MEMORY_BANK_LOCATION=$(REGION) \
  STEWARD_MEMORY_SCOPE=$(MEMORY_SCOPE) \
  BQ_DATASET=$(BQ_DATASET) \
  OTEL_SERVICE_NAME=steward \
  GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true

comma := ,
space := $(subst ,, )
env_csv = $(subst $(space),$(comma),$(strip $1))

primacy_url = $$(gcloud run services describe primacy-agency --region $(REGION) \
  --project $(PROJECT) --format='value(status.url)' 2>/dev/null)

# The aiplatform pin works around a version skew in agents-cli 1.4.1
# (it imports a pre-rename symbol; 2.0.1 renamed agent engines → runtimes).
# Memory Bank is scoped to the engine itself, so its id is only known
# after the first deploy; `make memory-bank` wires it on the second.
deploy:
	uvx --with 'google-cloud-aiplatform==2.0.0' google-agents-cli deploy \
	  --project $(PROJECT) --region $(REGION) --agent-identity \
	  --update-env-vars "$(call env_csv,$(FLEET_ENV)),PRIMACY_AGENCY_ENDPOINT=$(primacy_url)$(if $(ENGINE),$(comma)AGENT_ENGINE_MEMORY_BANK=$(ENGINE))"

deploy-run:
	gcloud run deploy steward-fleet --source . --region $(REGION) \
	  --project $(PROJECT) --allow-unauthenticated \
	  --memory 2Gi --cpu 2 --set-env-vars \
	  "$(call env_csv,$(FLEET_ENV)),PRIMACY_AGENCY_ENDPOINT=$(primacy_url)$(if $(ENGINE),$(comma)AGENT_ENGINE_MEMORY_BANK=$(ENGINE))"

# The primacy agency publishes an A2A card that names its own address;
# without PUBLIC_URL it advertises localhost and no registry can reach it.
# Memory Bank lives on the reasoning engine, so its id exists only after
# the engine does. This resolves it and rebinds the fleet to it.
memory-bank:
	@ENGINE=$$(curl -s -H "Authorization: Bearer $$(gcloud auth print-access-token)" \
	  "https://$(REGION)-aiplatform.googleapis.com/v1/projects/$(PROJECT)/locations/$(REGION)/reasoningEngines" \
	  | python3 -c "import json,sys; e=json.load(sys.stdin).get('reasoningEngines',[]); print(e[0]['name'] if e else '')"); \
	if [ -z "$$ENGINE" ]; then echo "No reasoning engine yet — run 'make deploy' first."; exit 1; fi; \
	echo "Binding Memory Bank to $$ENGINE"; \
	$(MAKE) deploy-run ENGINE=$$ENGINE

deploy-all:
	gcloud run deploy primacy-agency --source primacy --region $(REGION) \
	  --project $(PROJECT) --allow-unauthenticated --memory 512Mi
	gcloud run services update primacy-agency --region $(REGION) \
	  --project $(PROJECT) --update-env-vars \
	  "PUBLIC_URL=$$(gcloud run services describe primacy-agency --region $(REGION) --project $(PROJECT) --format='value(status.url)')"
	$(MAKE) deploy-run
	gcloud run deploy steward-edge --source edge --region $(REGION) \
	  --project $(PROJECT) --allow-unauthenticated \
	  --memory 16Gi --cpu 8 --min-instances 0 --timeout 900
