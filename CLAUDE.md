# Steward — orientation for coding agents

**What this is.** A fleet of long-lived agents that works beside a
part-time municipal wastewater operator: it forecasts permit exceedances
against the real EPA NPDES record, argues with itself in the open when
no fix is free, and hands every irreversible decision back to the human
whose certification is on the line. Read [README.md](README.md) first —
it carries the finding, the folder map, and the design rules.

**The five rules this codebase will not bend.** Break any of them and
the project stops being what it is:

1. **No agent takes an irreversible action.** Authority is enforced per
   tool call (`app/fleet/authority.py`); irreversible tools need a
   single-use token minted only by the operator's confirmed decision.
2. **Every number an agent asserts cites a source.** The supervisor
   (`app/fleet/supervisor.py`) reads cited sensors itself; no source or
   a contradiction means quarantine, and the claim never reaches the
   operator.
3. **Seeds contain world facts, never agent behaviour.**
   `fixtures/seeds/*.json` may describe a poisoned lab report arriving;
   it may never say "quarantine the worker". A test enforces this.
4. **Gemma at the edge is self-hosted, never a Vertex API call.** The
   whole point of `edge/` is that raw plant data does not cross the OT
   boundary; an API call would defeat it.
5. **Aggregate reporting only, and no facility is ever named.** See
   "Why the facility is de-identified" in the README. The demo facility
   is a composite; the backtest is national and anonymous.

**Voice.** Product copy is plain, specific, unsentimental: state
consequences, never editorialize, never thank the user. Say *the plant*,
*the watershed*, *the discharge*.

**Numbers in the README, the video, and the Devpost text come from
`data/sql/03_finding.sql`.** Never hand-type one; re-run `make backtest`
and quote the `finding` table.

**Local loop:** `make dev` (console at http://localhost:8000/console/),
`make test` (22 policy tests, no cloud), `make lint`.

---

# Coding Agent Guide

## Prerequisites

Install the CLI (one-time):
```bash
uv tool install google-agents-cli
```

---

## Development Phases

### Phase 1: Understand Requirements
Before writing any code, understand the project's requirements, constraints, and success criteria.

### Phase 2: Build and Implement
Implement agent logic in `app/`. Use `agents-cli playground` for interactive testing. Iterate based on user feedback.

### Phase 3: The Evaluation Loop (Main Iteration Phase)
Start with 1-2 eval cases, run `agents-cli eval run`, iterate by making changes and rerunning it until satisfied. Expect 5-10+ iterations. Once you have a baseline, reach for `agents-cli eval compare` (regression diffs), `agents-cli eval analyze` (cluster failure modes), and `agents-cli eval optimize` (auto-tune prompts). See the **Evaluation Guide** for metrics, dataset schema, LLM-as-judge config, and common gotchas.

### Phase 4: Pre-Deployment Tests
Run `uv run pytest tests/unit tests/integration`. Fix issues until all tests pass.

### Phase 5: Deploy to Dev
**Requires explicit human approval.** Run `agents-cli deploy` only after user confirms. See the **Deployment Guide** for details.

### Phase 6: Production Deployment
Ask the user: Option A (simple single-project) or Option B (full CI/CD pipeline with `agents-cli infra cicd`).

## Development Commands

| Command | Purpose |
|---------|---------|
| `agents-cli playground` | Interactive local testing |
| `uv run pytest tests/unit tests/integration` | Run unit and integration tests |
| `agents-cli eval dataset synthesize` | Synthesize multi-turn eval scenarios for your agent |
| `agents-cli eval run` | Run the agent over the eval dataset and grade the traces |
| `agents-cli eval generate` / `agents-cli eval grade` | Decoupled form: produce traces, then grade them |
| `agents-cli eval compare` | Compare two grade-results files (regression check) |
| `agents-cli eval analyze` | Cluster failure modes from grade results |
| `agents-cli eval metric list` | List built-in metrics available in the SDK |
| `agents-cli eval optimize` | Auto-tune agent prompts using eval data |
| `agents-cli lint` | Check code quality |
| `agents-cli infra single-project` | Set up project infrastructure (Terraform) |
| `agents-cli deploy` | Deploy to dev |
| `agents-cli scaffold enhance` | Add deployment target or CI/CD to project |
| `agents-cli scaffold upgrade` | Upgrade project to latest version |

---

## Operational Guidelines for Coding Agents

- **Code preservation**: Only modify code directly targeted by the user's request. Preserve all surrounding code, config values (e.g., `model`), comments, and formatting.
- **NEVER change the model** unless explicitly asked.
- **Model 404 errors**: Fix `GOOGLE_CLOUD_LOCATION` (e.g., `global` instead of `us-central1`), not the model name.
- **ADK tool imports**: Import the tool instance, not the module: `from google.adk.tools.load_web_page import load_web_page`
- **Run Python with `uv`**: `uv run python script.py`. Run `agents-cli install` first.
- **Stop on repeated errors**: If the same error appears 3+ times, fix the root cause instead of retrying.
- **Terraform conflicts** (Error 409): Use `terraform import` instead of retrying creation.
