"""Custom (non-MCP) LangChain tools available to the agent."""

from langchain_core.tools import tool


@tool
def echo(text: str) -> str:
    """Echo the given text back. Placeholder tool — replace with real ones."""
    return text
