"""Pydantic schemas for structured LLM output."""

from pydantic import BaseModel, Field


class RoutingDecision(BaseModel):
    """Manager's choice of exactly one next speaker, made after every message."""

    next: str = Field(
        description="Exactly one persona name who should speak next, or the "
        "literal string 'human' if it's the human's turn — either because the "
        "conversation needs their input right now, or because the friends have "
        "said enough for the moment."
    )
    note: str = Field(
        description="A short, casual line shown inline in the group chat (under "
        "15 words). If routing to a persona: why they're up next, e.g. 'this "
        "needs a reality check'. If next='human': either a quick question for "
        "them, or just a light 'over to you' if nothing needs asking."
    )
