"""FastAPI wrapper around the LangGraph agent (app/graph.py).

Run with: uv run uvicorn api.server:app --reload --port 8000
(from the backend/ directory, same cwd assumption as main.py.)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

from app.config import DATA_DIR
from app.graph import build_graph
from app.threads import init_threads_table, list_threads, touch_thread

CHECKPOINT_DB_PATH = str(DATA_DIR / "checkpoints.db")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_threads_table(CHECKPOINT_DB_PATH)
    async with AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as checkpointer:
        app.state.graph = await build_graph(checkpointer)
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


class PersonaReply(BaseModel):
    persona: str
    content: str


class ChatResponse(BaseModel):
    replies: list[PersonaReply]


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    graph = app.state.graph
    config = {"configurable": {"thread_id": req.thread_id}}
    prior_count = len((await graph.aget_state(config)).values.get("messages", []))
    touch_thread(CHECKPOINT_DB_PATH, req.thread_id, req.message)
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": req.message}]},
        config=config,
    )
    new_messages = result["messages"][prior_count + 1 :]
    return ChatResponse(
        replies=[PersonaReply(persona=m.name, content=m.content) for m in new_messages]
    )


class ThreadSummary(BaseModel):
    thread_id: str
    title: str
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


class ThreadMessagesResponse(BaseModel):
    messages: list[ThreadMessage]


@app.get("/threads/{thread_id}/messages", response_model=ThreadMessagesResponse)
async def thread_messages(thread_id: str):
    graph = app.state.graph
    config = {"configurable": {"thread_id": thread_id}}
    state = await graph.aget_state(config)
    messages = state.values.get("messages", [])
    return ThreadMessagesResponse(
        messages=[
            ThreadMessage(
                role="user" if m.type == "human" else "assistant",
                persona=getattr(m, "name", None),
                content=m.content,
            )
            for m in messages
        ]
    )
