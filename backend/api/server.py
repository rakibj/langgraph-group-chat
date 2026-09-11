"""FastAPI wrapper around the LangGraph agent (app/graph.py).

Run with: uv run uvicorn api.server:app --reload --port 8000
(from the backend/ directory, same cwd assumption as main.py.)
"""

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

from app.config import DATA_DIR
from app.graph import DEFAULT_STRATEGY, STRATEGIES, build_graph
from app.threads import get_thread_strategy, init_threads_table, list_threads, touch_thread

CHECKPOINT_DB_PATH = str(DATA_DIR / "checkpoints.db")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_threads_table(CHECKPOINT_DB_PATH)
    async with AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as checkpointer:
        app.state.graphs = {
            strategy: await build_graph(checkpointer, strategy) for strategy in STRATEGIES
        }
        yield


app = FastAPI(title="langgraph-starter API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


class ChatRequest(BaseModel):
    thread_id: str
    message: str
    strategy: str = DEFAULT_STRATEGY


@app.post("/chat")
async def chat(req: ChatRequest):
    # The strategy is fixed the first time a thread is touched; later
    # messages on the same thread ignore req.strategy and keep using it,
    # so a chat can't switch routing strategy mid-conversation.
    strategy = get_thread_strategy(CHECKPOINT_DB_PATH, req.thread_id) or req.strategy
    if strategy not in STRATEGIES:
        raise HTTPException(400, f"unknown strategy {strategy!r}")

    graph = app.state.graphs[strategy]
    config = {"configurable": {"thread_id": req.thread_id}}
    touch_thread(CHECKPOINT_DB_PATH, req.thread_id, req.message, strategy)

    async def event_stream():
        async for update in graph.astream(
            {"messages": [{"role": "user", "content": req.message}]},
            config=config,
            stream_mode="updates",
        ):
            for node_output in update.values():
                for message in node_output.get("messages", []):
                    payload = {
                        "persona": message.name,
                        "content": message.content,
                        "kind": message.additional_kwargs.get("kind"),
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class ThreadSummary(BaseModel):
    thread_id: str
    title: str
    strategy: str
    updated_at: str


class ThreadListResponse(BaseModel):
    threads: list[ThreadSummary]


@app.get("/threads", response_model=ThreadListResponse)
async def threads():
    return ThreadListResponse(
        threads=[ThreadSummary(**row) for row in list_threads(CHECKPOINT_DB_PATH)]
    )


class ThreadMessage(BaseModel):
    role: str
    persona: str | None = None
    content: str
    kind: str | None = None


class ThreadMessagesResponse(BaseModel):
    messages: list[ThreadMessage]


@app.get("/threads/{thread_id}/messages", response_model=ThreadMessagesResponse)
async def thread_messages(thread_id: str):
    strategy = get_thread_strategy(CHECKPOINT_DB_PATH, thread_id) or DEFAULT_STRATEGY
    graph = app.state.graphs[strategy]
    config = {"configurable": {"thread_id": thread_id}}
    state = await graph.aget_state(config)
    messages = state.values.get("messages", [])
    return ThreadMessagesResponse(
        messages=[
            ThreadMessage(
                role="user" if m.type == "human" else "assistant",
                persona=getattr(m, "name", None),
                content=m.content,
                kind=getattr(m, "additional_kwargs", {}).get("kind"),
            )
            for m in messages
        ]
    )
