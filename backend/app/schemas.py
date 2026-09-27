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


class IntakeDecision(BaseModel):
    """Manager's call during the 'debate' mode's intake phase: keep asking
    the human questions, or hand a brief to the group."""

    ready: bool = Field(
        description="True once you know enough for six friends to argue about "
        "this meaningfully (the actual decision, the key numbers/constraints, "
        "and what's at stake). False if something important is still missing."
    )
    message: str = Field(
        description="If ready=false: your next message to the human — one or "
        "two short, specific questions, casual group-chat tone, an emoji is "
        "fine. If ready=true: a short hype line handing it to the group, e.g. "
        "'ok I've got enough — letting the group loose on this 🔥'."
    )
    brief: str = Field(
        description="If ready=true: a 2-4 sentence summary of the decision and "
        "every concrete fact the human gave (numbers, constraints, stakes, "
        "their gut lean). Empty if ready=false."
    )


class DebateDecision(BaseModel):
    """Hidden router's pick after every message in the 'debate' mode."""

    next: str = Field(
        description="Exactly one friend's name who should speak next, the "
        "literal string 'ask_user' if the group is stuck on a specific missing "
        "fact only the human can give, or the literal string 'vote' if the "
        "argument has run its course and it's time to call a vote."
    )
    question: str = Field(
        description="Only if next='ask_user': the manager's short message to "
        "the human interrupting the chat for that one missing fact, casual, "
        "e.g. 'hold up — nobody knows your monthly burn. what is it? 👀'. "
        "Empty otherwise."
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
