"""Steward — the root agent.

The conversational face of the fleet: what a judge meets in the ADK
playground, what Gemini Enterprise registers over A2A, and what the
Vertex console's Playground drives through the reasoning-engine adapter.

The root agent is an orchestrator in the strict sense: it holds no tools
of its own and answers nothing from memory that a worker owns. It routes
to the five workers (each scoped to one station, one facility, one
authority level — see fleet/agents/workers.py) and it inherits every
fence the fleet runs: the AuthorityPlugin checks each tool call, the
supervisor audits worker claims in the shift loop, and irreversible
actions do not execute without an operator-minted approval token.

The autonomous side of the same fleet — the long-lived shift loop that
Agent Runtime keeps alive for days — lives in fleet/shift.py and shares
these exact agent definitions and policies.
"""

import logging
import os

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from app.fleet.agents.workers import WORKERS
from app.fleet.authority import AuthorityPlugin

MODEL = "gemini-3.7-flash"

root_agent = Agent(
    name="steward",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    description=(
        "Steward runs a fleet of long-lived agents beside a part-time "
        "wastewater operator, forecasting permit exceedances before they "
        "happen and putting every irreversible decision back in his hands."
    ),
    instruction=(
        "You are Steward's orchestrator for a small municipal water "
        "reclamation facility. You coordinate five station agents — flow "
        "warden (headworks), aeration keeper (biology), permit sentinel "
        "(outfall), weather scout, notification clerk — and route each "
        "question to the agent whose station it lands on.\n\n"
        "House rules, absolute:\n"
        "- Plain, specific, unsentimental. State consequences; never "
        "editorialize; never thank the user. Say 'the plant', 'the "
        "watershed', 'the discharge'.\n"
        "- Numbers come from workers' cited sources, never from your own "
        "recall. If no worker can source a number, say so.\n"
        "- No agent — including you — executes an irreversible action. "
        "Those require the operator's explicit approval in the console. "
        "The certification of record is his, so the decision is too."
    ),
    sub_agents=list(WORKERS.values()),
)

# BigQuery Agent Analytics: every agent interaction lands in a queryable
# dataset next to the EPA corpus the fleet reasons over.
_plugins = [AuthorityPlugin()]
_project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
_dataset_id = os.environ.get("BQ_ANALYTICS_DATASET_ID", "adk_agent_analytics")
_location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

if _project_id:
    try:
        from google.adk.plugins.bigquery_agent_analytics_plugin import (
            BigQueryAgentAnalyticsPlugin,
            BigQueryLoggerConfig,
        )
        from google.cloud import bigquery

        bq = bigquery.Client(project=_project_id)
        bq.create_dataset(f"{_project_id}.{_dataset_id}", exists_ok=True)
        _plugins.append(
            BigQueryAgentAnalyticsPlugin(
                project_id=_project_id,
                dataset_id=_dataset_id,
                location=_location,
                config=BigQueryLoggerConfig(
                    gcs_bucket_name=os.environ.get("BQ_ANALYTICS_GCS_BUCKET"),
                    connection_id=os.environ.get("BQ_ANALYTICS_CONNECTION_ID"),
                ),
            )
        )
    except Exception as e:
        logging.warning(f"BigQuery Analytics not initialized: {e}")

app = App(
    root_agent=root_agent,
    name="app",
    plugins=_plugins,
)
