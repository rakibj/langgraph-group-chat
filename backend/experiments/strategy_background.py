"""EXPERIMENT (not wired into the app) — Strategy 2: manager runs entirely in
the background. No "Routing to X" lines, no visible manager turn — the user
just sees friends talking directly, like a real group chat, and a final
"group" message when the manager decides enough is known.

Run from backend/: uv run python experiments/strategy_background.py
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
        description="Exactly one persona name to speak next, 'human' if it's "
        "the human's turn, or 'verdict' if the group has enough real, "
        "verified information to land on a confident final call."
    )


MANAGER_PROMPT = (
    "You silently referee a friend group chat — nobody sees you, you just "
    "pick who talks next. After every message, choose exactly one: a friend "
    "(" + ", ".join(PERSONAS) + "), 'human', or 'verdict'.\n\n"
    "Route to a friend only if they'd add a genuinely fresh angle. Route to "
    "'human' when the group is missing a real, specific fact (a number, a "
    "constraint, a confirmation). Route to 'verdict' the moment there's "
    "enough concrete info for a confident recommendation — don't stall for "
    "more confirmation once the key facts are in. Be decisive."
)

VERDICT_PROMPT = (
    "You're one more voice in this group chat, speaking for the whole group "
    "at once now that everyone's weighed in — casual, like 'okay, here's "
    "where we landed'. Reference what a couple of friends said by name, then "
    "give ONE clear, direct call: go, don't go, or go-but-only-if-X. 3-4 "
    "sentences, warm but not wishy-washy, no headers or lists."
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

        next_speaker = decision.next
        if next_speaker not in PERSONAS and next_speaker not in ("human", "verdict"):
            next_speaker = "human"
        if next_speaker in PERSONAS and hop_count >= MAX_HOPS_PER_TURN:
            next_speaker = "verdict"

        return {
            "next_speaker": next_speaker,
            "hop_count": hop_count + 1 if next_speaker in PERSONAS else 0,
        }

    async def verdict_node(state: State):
        messages = [SystemMessage(content=VERDICT_PROMPT), *state["messages"]]
        response = await llm.ainvoke(messages)
        response.name = "group"
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

    print("Strategy 2: background manager, friends talk directly. Type a message, or 'exit'.")
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
