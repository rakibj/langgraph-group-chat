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

CHECKPOINT_DB_PATH = str(DATA_DIR / "checkpoints.db")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as checkpointer:
        app.state.graph = await build_graph(checkpointer)
        yield


app = FastAPI(title="langgraph-starter API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": req.message}]},
        config=config,
    )
    new_messages = result["messages"][prior_count + 1 :]
    return ChatResponse(
        replies=[PersonaReply(persona=m.name, content=m.content) for m in new_messages]
    )
