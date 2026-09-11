# langgraph-starter

A minimal [LangGraph](https://langchain-ai.github.io/langgraph/) agent
scaffold: a tool-calling agent loop, checkpointed to SQLite, with a CLI
entry point and a thin FastAPI + React shell around it. Meant as a starting
point for a new LangGraph project.

## Architecture

```
backend/
  main.py            CLI entry point (REPL)
  app/
    config.py         env loading + shared paths
    schemas.py         structured-output models (empty — add your own)
    tools.py            LangChain tools available to the agent
    graph.py             StateGraph: agent <-> tools loop, SQLite-checkpointed
  api/
    server.py            FastAPI wrapper over the same graph
  data/                SQLite checkpoints (gitignored)
frontend/              React + Vite shell (calls backend /health)
code_sample.ipynb      reference notebook, kept from the previous project
```

## Requirements

- Python 3.12+ and [`uv`](https://docs.astral.sh/uv/)
- Node 20+ (for the frontend)
- An OpenAI API key

## Setup

```bash
# 1. Secrets
cp backend/.env.example backend/.env
#    then edit backend/.env with real values

# 2. Backend deps
cd backend
uv sync

# 3. Frontend deps
cd ../frontend
npm install
```

## Running

### CLI

```bash
cd backend
uv run main.py
```

### Web UI

```bash
# terminal 1 — API
cd backend
uv run uvicorn api.server:app --reload --port 8000

# terminal 2 — frontend
cd frontend
npm run dev               # http://localhost:5173
```

The API expects to run with `backend/` as the working directory (the
`data/` path is cwd-relative).

## Security

Never commit `backend/.env` or real credentials.
