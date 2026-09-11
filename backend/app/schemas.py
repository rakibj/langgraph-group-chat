"""Pydantic schemas for structured LLM output."""

from pydantic import BaseModel, Field


class RoutingDecision(BaseModel):
    """Manager's choice of exactly one next speaker, made after every message."""

    next: str = Field(
        description="Exactly one persona name who should speak next, the "
        "literal string 'human' if it's the human's turn, or the literal "
        "string 'verdict' if the group now has enough real, verified "
        "information to render a confident final recommendation."
    )
    note: str = Field(
        description="A short, casual line shown inline in the group chat (under "
        "15 words). If routing to a persona: why they're up next, e.g. 'this "
        "needs a reality check'. If next='human': either a quick question for "
        "them, or just a light 'over to you' if nothing needs asking. If "
        "next='verdict': leave blank or a short 'let me sum this up'."
    )


class SilentRoutingDecision(BaseModel):
    """Same choice as RoutingDecision, but for a manager that stays invisible
    — no note is ever shown, so there's nothing to generate for one."""

    next: str = Field(
        description="Exactly one persona name who should speak next, the "
        "literal string 'human' if it's the human's turn, or the literal "
        "string 'verdict' if the group now has enough real, verified "
        "information to render a confident final recommendation."
    )
