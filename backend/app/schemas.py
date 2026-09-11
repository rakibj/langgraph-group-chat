"""Pydantic schemas for structured LLM output."""

from pydantic import BaseModel, Field


class RoutingDecision(BaseModel):
    """Manager's choice of which personas should respond to the latest turn."""

    speakers: list[str] = Field(
        description="Names of the personas who should respond this turn, in the "
        "order they should speak. Pick only the ones who'd actually add something "
        "new — not all six every time."
    )
    reasoning: str = Field(
        description="A short, casual reason (under 10 words, no punctuation-heavy "
        "explanation) for why these personas were picked — this gets shown "
        "inline in the group chat, like 'this needs a reality check'."
    )
