# langgraph-starter

A minimal LangGraph project scaffold: a tool-calling agent loop
(`agent` ⇄ `tools`), checkpointed to SQLite, with a CLI entry point and a
thin FastAPI + React shell around it. This is a fresh starting point — no
domain logic is baked in yet.

Don't touch code unless I say or imply specifically. Share plan beforehand.
If you need to make some architectural changes, ask me to pick giving me
alternatives while suggesting what's best.

Whenever I ask a question that clarifies how something in this codebase
works (architecture, control flow, why something is built a certain way),
append the question and answer to `CLARIFICATIONS.md` at the repo root —
don't just answer inline and drop it. Keep entries dated, newest at the
bottom. (Create the file if it doesn't exist yet.)

This project is being built milestone by milestone (see the video plan
context) so each stage is independently demoable. At the end of each
milestone, export the current graph structure with
`python scripts/export_graph.py <milestone-name>` (run from `backend/`)
and commit the resulting `backend/docs/<milestone-name>.md` alongside the
milestone's code, so `backend/docs/` accumulates a Mermaid diagram per
milestone showing how the graph grew.

## Architecture

```
backend/
  main.py                CLI entry point — builds the graph, runs a REPL
  app/
    config.py             env loading (.env), shared paths/constants
    schemas.py             structured-output Pydantic models (empty)
    tools.py                 LangChain tools available to the agent
    graph.py                  StateGraph: agent <-> tools loop,
                                AsyncSqliteSaver-checkpointed
  api/
    server.py                FastAPI wrapper exposing the same graph
                               (/health, /chat)
  scripts/
    export_graph.py           writes backend/docs/<milestone>.md, a
                                Mermaid diagram of the current graph
  docs/                   one Mermaid graph export per milestone
  data/                   SQLite checkpoints, gitignored
frontend/                React + Vite shell — calls backend GET /health
code_sample.ipynb        reference notebook from the previous project,
                           kept for MCP/tool-wiring examples
```

**Module dependency direction:**
```
backend/main.py ──→ app.config, app.graph
backend/api/server.py ──→ app.config, app.graph
app.graph ──→ app.tools
app.tools, app.config ──→ (no app.* deps)
```

There is one graph, built by `app.graph.build_graph(checkpointer)`, and one
checkpoint store (`backend/data/checkpoints.db`, opened once per process).
Extend the graph by adding nodes/edges in `app/graph.py`, tools in
`app/tools.py`, and structured-output models in `app/schemas.py`.
