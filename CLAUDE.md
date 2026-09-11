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

## Video plan

This build is being filmed milestone by milestone for a YouTube video.

**Core open loop:** Can six conflicting AI perspectives actually produce a
better decision than one powerful model?

**Title options:**
- Primary: "I Made 6 AI Agents Debate My Next Business Decision"
- Backup: "I Made 6 AI Agents Disagree Before I Made a Decision"
- Wildcard: "I Built an AI Group Chat That Argues With Itself"

**Thumbnail:** group chat UI, visible disagreement (green YES vs red "Too
risky"), real reaction face. Text: "THEY DISAGREED". To fix: remove chat
bubble timestamps (illegible at phone size).

**Target length:** 6-8 min.

**Structure:**
- 0:00-0:15 — Proof/payoff tease: real question, agents disagree, manager
  flags need for more info, flash final verdict without explaining it
- 0:15-0:45 — Premise: one AI answer vs six agents with different thinking
  styles; reveal the six personas
- 0:45-1:10 — Failure/tension: naive version (all 6 reply every time) is
  noisy, repetitive, expensive, fake-feeling
- Middle — escalating build problems, each with a before → after demo:
  who speaks? how do agents respond to each other? when does the manager
  ask the user? when is the conversation "finished"? Engineer visible
  disagreements deliberately (agent challenges another, manager interrupts,
  user gets questioned, majority is wrong, verdict changes with new
  information) — these are the entertainment beats, and map to upcoming
  milestones (routing/turn-taking, inter-agent response, manager-asks-user,
  termination condition).
- Final ~90s — Payoff: run one real decision end-to-end, reveal verdict,
  compare vs a single-AI answer. Open question to resolve before shooting:
  the real decision run needs to visibly beat/differ from a single ChatGPT
  answer, or the payoff undersells the open loop.

**CTA:** ~1:00 mark — DIY path (code/resources) + "book a call, I'll build
it for you"; restate both at close.

**Editing rules:** keep implementation visual (architecture diagrams, state
changes, routing decisions); cut API setup/code walkthroughs unless they
explain a break; don't reveal the "Six Thinking Hats" inspiration until
after the system is understood; if a segment doesn't move the story or
explain an important engineering decision, it goes to description/GitHub
instead of the video.

**Milestone progress:**
- M0 — done (iMessage-style chat UI restyle, markdown rendering for
  assistant bubbles, model switched to gpt-5.6-luna).
