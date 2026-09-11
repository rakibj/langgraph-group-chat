"""LangGraph group-chat agent, checkpointed to SQLite.

M2 (routing/turn-taking): a manager node reads the conversation and picks
which persona(s) should respond this turn — not all six every time. The
manager's decision is appended to the message list as a visible "manager"
message so the UI can show who was routed to and why.

M3 (inter-agent response + continuous router loop): the manager isn't a
one-shot batch-picker anymore — it's a router called after every single
message (human or persona) to decide exactly one next speaker. Personas run
one at a time, in order, instead of in parallel, so each one sees every
reply that came before it (including other personas') and can actually
react to it. Personas loop back through the manager instead of ending the
turn, so a turn can chain through several friends before control returns to
the human.

M3 exposed a real problem: the router alone never converges — it can ask
the human for "just one more number" forever with no way to land a final
call. Two candidate fixes for that, both implemented here as selectable
strategies so they can be compared side by side in the UI before picking
one:

- "confidence": the manager stays visible (routing lines shown), and can
  route to an explicit 'verdict' node once it judges the group has enough
  real information, instead of only ever routing to a persona or 'human'.
- "background": the manager's routing decisions are never shown — personas
  just talk to each other directly, like a real group chat — and a 'group'
  voice delivers the same kind of verdict once enough is known.

Both strategies guard against re-litigating a verdict that's already been
given (a `verdict_given` flag added to the manager's context once a verdict
fires), and against a silent, empty turn (the background manager can't hand
back to the human before at least one friend has spoken).
"""

from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph

from app.personas import PERSONA_MAX_TOKENS, PERSONAS
from app.schemas import RoutingDecision, SilentRoutingDecision

MAX_HOPS_PER_TURN = 6

STRATEGIES = ("confidence", "background")
DEFAULT_STRATEGY = "confidence"


class State(MessagesState):
    next_speaker: str
    hop_count: int
    verdict_given: bool


def _make_persona_node(persona_llm, name: str, system_prompt: str):
    async def persona_node(state: State):
        messages = [SystemMessage(content=system_prompt), *state["messages"]]
        response = await persona_llm.ainvoke(messages)
        response.name = name
        return {"messages": [response]}

    return persona_node


def _last_persona_speaker(messages) -> str | None:
    for m in reversed(messages):
        name = getattr(m, "name", None)
        if name in PERSONAS:
            return name
    return None


async def _route_avoiding_repeat(router, prompt: str, messages, last_speaker: str | None):
    """Ask the router for a decision; "never repeat the last speaker" is a
    hard rule in the prompt already, but LLM instruction-following on a
    "never" isn't reliable enough to trust alone — nudge once if it's
    ignored, then fall back to a deterministic rotation rather than risk a
    third repeat."""
    decision = await router.ainvoke([SystemMessage(content=prompt), *messages])

    if last_speaker and decision.next == last_speaker:
        retry_prompt = (
            prompt
            + f"\n\nYou just picked {last_speaker} again, but they replied "
            "last turn — the hard rule says pick someone else. Choose a "
            "different friend this time."
        )
        decision = await router.ainvoke([SystemMessage(content=retry_prompt), *messages])

    if last_speaker and decision.next == last_speaker:
        order = list(PERSONAS)
        decision.next = order[(order.index(last_speaker) + 1) % len(order)]

    return decision


# ---------------------------------------------------------------------------
# Strategy 1: visible manager, self-assessed confidence, explicit verdict node
# ---------------------------------------------------------------------------

CONFIDENCE_MANAGER_PROMPT = (
    "You're the quiet one in this friend group chat — you don't weigh in with "
    "your own opinion, you just decide who talks next. After every message, "
    "pick exactly one: a friend (" + ", ".join(PERSONAS) + "), 'human', or "
    "'verdict'.\n\n"
    "Route to a friend only if they'd add a genuinely fresh angle. Route to "
    "'human' when the group is missing a real, specific fact it needs (a "
    "number, a constraint, a confirmation) — ask for exactly that.\n\n"
    "This is six distinct friends with six distinct angles, not one expert "
    "the others defer to — hard rule: never route to the same friend two "
    "human-turns in a row. Whoever replied last turn is off the table now, "
    "no matter how relevant they seem, unless you've genuinely run out of "
    "other angles worth hearing (rare — feasibility, weak assumptions, the "
    "upside case, the numbers, the counter-case, and the human impact are "
    "almost never all exhausted after two or three exchanges). Pick "
    "whichever of the remaining five would react most naturally to what the "
    "human just said.\n\n"
    "Route to 'verdict' the moment you have enough concrete, verified "
    "information (not vibes) to render a clear, confident recommendation — "
    "don't keep fishing for more confirmation once the key facts are in. Be "
    "decisive: two or three solid rounds of back-and-forth should be enough "
    "for most decisions. Never ask the same question twice."
)

CONFIDENCE_VERDICT_REOPEN_NOTE = (
    "\n\nA verdict has already been given earlier in this chat — that's "
    "done, it's not a state the conversation needs to keep returning to. "
    "The chat should keep flowing at full strength between friends, same "
    "as before any verdict happened: default to routing to whichever "
    "friend would react most naturally to what the human just said. Only "
    "route to 'verdict' again if something genuinely significant has "
    "shifted since the last one — real new information that would change "
    "the call, or the group actually reaching a different conclusion after "
    "real back-and-forth — not just because the human sounds unsure, asks "
    "'are you sure?', or raises a follow-up question."
)

CONFIDENCE_VERDICT_PROMPT = (
    "You're synthesizing this friend group chat into one final, clear "
    "verdict for the human. Weigh what each friend actually said (cite them "
    "by name where it matters), state the single biggest risk and the "
    "single biggest reason for confidence, then give ONE explicit "
    "recommendation: go, don't go, or go-but-only-if-X. 4-6 sentences, plain "
    "and direct, no hedging into 'it depends on you.' Start with 'VERDICT:'."
)


async def _build_confidence_graph(checkpointer):
    llm = ChatOpenAI(model="gpt-5.6-luna", temperature=0, reasoning_effort="none")
    persona_llm = llm.bind(max_tokens=PERSONA_MAX_TOKENS)
    router = llm.with_structured_output(RoutingDecision)

    async def manager_node(state: State):
        prompt = CONFIDENCE_MANAGER_PROMPT
        if state.get("verdict_given"):
            prompt += CONFIDENCE_VERDICT_REOPEN_NOTE
        last_speaker = _last_persona_speaker(state["messages"])
        decision = await _route_avoiding_repeat(router, prompt, state["messages"], last_speaker)
        hop_count = state.get("hop_count", 0)

        next_speaker = decision.next
        if next_speaker not in PERSONAS and next_speaker not in ("human", "verdict"):
            next_speaker = "human"
        if next_speaker in PERSONAS and hop_count >= MAX_HOPS_PER_TURN:
            next_speaker = "verdict"

        if next_speaker == "human":
            content, kind = decision.note, "to_user"
        elif next_speaker == "verdict":
            content = decision.note or "Alright, I think we've got enough — let me sum it up."
            kind = "to_verdict"
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
        messages = [SystemMessage(content=CONFIDENCE_VERDICT_PROMPT), *state["messages"]]
        response = await llm.ainvoke(messages)
        response.name = "manager"
        response.additional_kwargs = {"kind": "verdict"}
        return {"messages": [response], "verdict_given": True}

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
        graph_builder.add_node(name, _make_persona_node(persona_llm, name, system_prompt))
        graph_builder.add_edge(name, "manager")

    graph_builder.add_conditional_edges(
        "manager", route_from_manager, list(PERSONAS) + ["verdict", END]
    )

    return graph_builder.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# Strategy 2: manager runs entirely in the background, friends talk directly
# ---------------------------------------------------------------------------

BACKGROUND_MANAGER_PROMPT = (
    "You silently referee a friend group chat — nobody sees you, you just "
    "pick who talks next. After every message, choose exactly one: a friend "
    "(" + ", ".join(PERSONAS) + "), 'human', or 'verdict'.\n\n"
    "Route to a friend only if they'd add a genuinely fresh angle. Route to "
    "'human' when the group is missing a real, specific fact (a number, a "
    "constraint, a confirmation).\n\n"
    "This is six distinct friends, not one expert the others defer to — "
    "hard rule: never route to the same friend two human-turns in a row. "
    "Whoever replied last turn is off the table now, no matter how "
    "relevant they seem, unless you've genuinely run out of other angles "
    "worth hearing (rare — feasibility, weak assumptions, the upside case, "
    "the numbers, the counter-case, and the human impact are almost never "
    "all exhausted after two or three exchanges). Pick whichever of the "
    "remaining five would react most naturally to what the human just "
    "said.\n\n"
    "Route to 'verdict' the moment there's enough concrete info for a "
    "confident recommendation — don't stall for more confirmation once the "
    "key facts are in. Be decisive."
)

BACKGROUND_VERDICT_REOPEN_NOTE = (
    "\n\nThe group already gave a verdict earlier in this chat — that's "
    "done, it's not a state the conversation needs to keep returning to. "
    "The chat should keep flowing at full strength between friends, same "
    "as before any verdict happened: default to routing to whichever "
    "friend would react most naturally to what the human just said. Only "
    "route to 'verdict' again if something genuinely significant has "
    "shifted since the last one — real new information that would change "
    "the call, or the group actually reaching a different conclusion after "
    "real back-and-forth — not just because the human sounds unsure, asks "
    "'are you sure?', or raises a follow-up question."
)

BACKGROUND_VERDICT_PROMPT = (
    "You're one more voice in this group chat, speaking for the whole group "
    "at once now that everyone's weighed in — casual, like 'okay, here's "
    "where we landed'. Reference what a couple of friends said by name, then "
    "give ONE clear, direct call: go, don't go, or go-but-only-if-X. 3-4 "
    "sentences, warm but not wishy-washy, no headers or lists."
)

# A friend to fall back on if the manager tries to hand the turn back to the
# human before anyone has actually said anything this turn — a silent
# handoff would just look like the app ate the message.
FALLBACK_PERSONA = next(iter(PERSONAS))


async def _build_background_graph(checkpointer):
    llm = ChatOpenAI(model="gpt-5.6-luna", temperature=0, reasoning_effort="none")
    persona_llm = llm.bind(max_tokens=PERSONA_MAX_TOKENS)
    router = llm.with_structured_output(SilentRoutingDecision)

    async def manager_node(state: State):
        prompt = BACKGROUND_MANAGER_PROMPT
        if state.get("verdict_given"):
            prompt += BACKGROUND_VERDICT_REOPEN_NOTE
        last_speaker = _last_persona_speaker(state["messages"])
        decision = await _route_avoiding_repeat(router, prompt, state["messages"], last_speaker)
        hop_count = state.get("hop_count", 0)

        next_speaker = decision.next
        if next_speaker not in PERSONAS and next_speaker not in ("human", "verdict"):
            next_speaker = "human"
        if next_speaker in PERSONAS and hop_count >= MAX_HOPS_PER_TURN:
            next_speaker = "verdict"
        if next_speaker == "human" and hop_count == 0:
            # Nobody has spoken yet this turn — never hand back in silence.
            next_speaker = FALLBACK_PERSONA if last_speaker != FALLBACK_PERSONA else next(
                p for p in PERSONAS if p != last_speaker
            )

        return {
            "next_speaker": next_speaker,
            "hop_count": hop_count + 1 if next_speaker in PERSONAS else 0,
        }

    async def verdict_node(state: State):
        messages = [SystemMessage(content=BACKGROUND_VERDICT_PROMPT), *state["messages"]]
        response = await llm.ainvoke(messages)
        response.name = "group"
        response.additional_kwargs = {"kind": "verdict"}
        return {"messages": [response], "verdict_given": True}

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
        graph_builder.add_node(name, _make_persona_node(persona_llm, name, system_prompt))
        graph_builder.add_edge(name, "manager")

    graph_builder.add_conditional_edges(
        "manager", route_from_manager, list(PERSONAS) + ["verdict", END]
    )

    return graph_builder.compile(checkpointer=checkpointer)


_BUILDERS = {
    "confidence": _build_confidence_graph,
    "background": _build_background_graph,
}


async def build_graph(checkpointer, strategy: str = DEFAULT_STRATEGY):
    if strategy not in _BUILDERS:
        raise ValueError(f"unknown strategy {strategy!r}, expected one of {STRATEGIES}")
    return await _BUILDERS[strategy](checkpointer)
