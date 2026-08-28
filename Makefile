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

.PHONY: install dev dev-console console test test-all data backtest deploy deploy-run deploy-all lint

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

# The aiplatform pin works around a version skew in agents-cli 1.4.1
# (it imports a pre-rename symbol; 2.0.1 renamed agent engines → runtimes).
deploy:
	uvx --with 'google-cloud-aiplatform==2.0.0' google-agents-cli deploy \
	  --project $(PROJECT) --region $(REGION) --agent-identity \
	  --update-env-vars "GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=$(PROJECT),GOOGLE_CLOUD_LOCATION=global,BQ_DATASET=steward_npdes"

deploy-run:
	gcloud run deploy steward-fleet --source . --region $(REGION) \
	  --project $(PROJECT) --allow-unauthenticated \
	  --memory 2Gi --set-env-vars \
	  "GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=$(PROJECT),GOOGLE_CLOUD_LOCATION=$(REGION),PRIMACY_AGENCY_ENDPOINT=$$(gcloud run services describe primacy-agency --region $(REGION) --project $(PROJECT) --format='value(status.url)' 2>/dev/null)"

deploy-all:
	gcloud run deploy primacy-agency --source primacy --region $(REGION) \
	  --project $(PROJECT) --allow-unauthenticated --memory 512Mi
	$(MAKE) deploy-run
	gcloud run deploy steward-edge --source edge --region $(REGION) \
	  --project $(PROJECT) --allow-unauthenticated \
	  --memory 16Gi --cpu 4 --min-instances 0 --timeout 600
