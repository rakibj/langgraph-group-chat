"""EXPERIMENT (not wired into the app) — Strategy 1: manager self-assesses
confidence and routes to an explicit "verdict" step once it decides the group
has enough real info to render a final call, instead of asking forever.

Run from backend/: uv run python experiments/strategy_confidence.py
"""

import asyncio

from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import BaseModel, Field

from app import config  # noqa: F401  (loads .env)
from app.personas import GROUP_CHAT_STYLE, PERSONA_MAX_TOKENS, PERSONAS

MAX_HOPS_PER_TURN = 6


class ManagerDecision(BaseModel):
    next: str = Field(
        description="Exactly one persona name to speak next, the literal "
        "'human' if it's the human's turn, or the literal 'verdict' if the "
        "group now has enough real, verified information to render a "
        "confident final recommendation."
    )
    note: str = Field(
        description="Short casual line (<15 words) shown inline: why this "
        "friend is up, a quick question for the human, or blank if verdict."
    )


MANAGER_PROMPT = (
    "You're the quiet one in this friend group chat — you don't weigh in with "
    "your own opinion, you just decide who talks next. After every message, "
    "pick exactly one: a friend (" + ", ".join(PERSONAS) + "), 'human', or "
    "'verdict'.\n\n"
    "Route to a friend only if they'd add a genuinely fresh angle. Route to "
    "'human' when the group is missing a real, specific fact it needs (a "
    "number, a constraint, a confirmation) — ask for exactly that.\n\n"
    "Route to 'verdict' the moment you have enough concrete, verified "
    "information (not vibes) to render a clear, confident recommendation — "
    "don't keep fishing for more confirmation once the key facts are in. Be "
    "decisive: two or three solid rounds of back-and-forth should be enough "
    "for most decisions. Never ask the same question twice."
)

VERDICT_PROMPT = (
    "You're synthesizing this friend group chat into one final, clear "
    "verdict for the human. Weigh what each friend actually said (cite them "
    "by name where it matters), state the single biggest risk and the "
    "single biggest reason for confidence, then give ONE explicit "
    "recommendation: go, don't go, or go-but-only-if-X. 4-6 sentences, plain "
    "and direct, no hedging into 'it depends on you.' Start with 'VERDICT:'."
)


class State(MessagesState):
    next_speaker: str
    hop_count: int


async def build_graph(checkpointer):
    llm = ChatOpenAI(model="gpt-5.6-luna", temperature=0, reasoning_effort="none")
    persona_llm = llm.bind(max_tokens=PERSONA_MAX_TOKENS)
    router = llm.with_structured_output(ManagerDecision)

    async def manager_node(state: State):
        messages = [SystemMessage(content=MANAGER_PROMPT), *state["messages"]]
        decision = await router.ainvoke(messages)
        hop_count = state.get("hop_count", 0)

        next_speaker = decision.next if decision.next in PERSONAS else decision.next
        if next_speaker not in PERSONAS and next_speaker not in ("human", "verdict"):
            next_speaker = "human"
        if next_speaker in PERSONAS and hop_count >= MAX_HOPS_PER_TURN:
            next_speaker = "verdict"

        if next_speaker == "human":
            content, kind = decision.note, "to_user"
        elif next_speaker == "verdict":
            content, kind = "Alright, I think we've got enough — let me sum it up.", "to_verdict"
        else:
            label = next_speaker.replace("_", " ").title()
            content, kind = f"Routing to: {label} — {decision.note}", "routing"

        manager_message = AIMessage(
            name="manager", content=content, additional_kwargs={"kind": kind}
        )
        return {
            "messages": [manager_message],
            "next_speaker": next_speaker,
            "hop_count": hop_count + 1 if next_speaker in PERSONAS else 0,
        }

    async def verdict_node(state: State):
        messages = [SystemMessage(content=VERDICT_PROMPT), *state["messages"]]
        response = await llm.ainvoke(messages)
        response.name = "manager"
        response.additional_kwargs = {"kind": "verdict"}
        return {"messages": [response]}

    def make_persona_node(name: str, system_prompt: str):
        async def persona_node(state: State):
            messages = [SystemMessage(content=system_prompt), *state["messages"]]
            response = await persona_llm.ainvoke(messages)
            response.name = name
            return {"messages": [response]}

        return persona_node

    def route_from_manager(state: State):
        speaker = state["next_speaker"]
        if speaker in PERSONAS:
            return speaker
        if speaker == "verdict":
            return "verdict"
        return END

    graph_builder = StateGraph(State)
    graph_builder.add_node("manager", manager_node)
    graph_builder.add_node("verdict", verdict_node)
    graph_builder.add_edge(START, "manager")
    graph_builder.add_edge("verdict", END)

    for name, system_prompt in PERSONAS.items():
        graph_builder.add_node(name, make_persona_node(name, system_prompt))
        graph_builder.add_edge(name, "manager")

    graph_builder.add_conditional_edges(
        "manager", route_from_manager, list(PERSONAS) + ["verdict", END]
    )

    return graph_builder.compile(checkpointer=checkpointer)


async def main():
    checkpointer = MemorySaver()
    graph = await build_graph(checkpointer)
    config = {"configurable": {"thread_id": "cli-session"}}

    print("Strategy 1: confidence-assessing manager. Type a message, or 'exit'.")
    while True:
        user_input = input("\nyou> ").strip()
        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue

        before = len((await graph.aget_state(config)).values.get("messages", []))
        result = await graph.ainvoke(
            {"messages": [{"role": "user", "content": user_input}]}, config=config
        )
        for msg in result["messages"][before:]:
            name = msg.name or "agent"
            print(f"{name}> {msg.content}")


if __name__ == "__main__":
    asyncio.run(main())
