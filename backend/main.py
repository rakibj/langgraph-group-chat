"""CLI entrypoint: builds the graph and runs a simple REPL against it."""

import asyncio

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config import DATA_DIR
from app.graph import build_graph

CHECKPOINT_DB_PATH = str(DATA_DIR / "checkpoints.db")


async def main():
    async with AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB_PATH) as checkpointer:
        graph = await build_graph(checkpointer)
        config = {"configurable": {"thread_id": "cli-session"}}

        print("LangGraph starter REPL. Type a message, or 'exit' to quit.")
        while True:
            user_input = input("\nyou> ").strip()
            if user_input.lower() in {"exit", "quit"}:
                break
            if not user_input:
                continue

            result = await graph.ainvoke(
                {"messages": [{"role": "user", "content": user_input}]},
                config=config,
            )
            print(f"agent> {result['messages'][-1].content}")


if __name__ == "__main__":
    asyncio.run(main())
