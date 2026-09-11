"""Export the current graph structure as a Mermaid diagram.

Usage (from backend/, with the venv active):
    python scripts/export_graph.py <milestone-name>

Writes docs/<milestone-name>.md with the graph's Mermaid source, so each
milestone's structure is captured as it's built.
"""

import asyncio
import sys
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402,F401  (loads .env as a side effect)
from app.graph import build_graph  # noqa: E402

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"


async def main(milestone: str):
    checkpointer = MemorySaver()
    graph = await build_graph(checkpointer)
    mermaid = graph.get_graph().draw_mermaid()

    DOCS_DIR.mkdir(exist_ok=True)
    out_path = DOCS_DIR / f"{milestone}.md"
    out_path.write_text(f"# {milestone} graph\n\n```mermaid\n{mermaid}```\n", encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/export_graph.py <milestone-name>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
