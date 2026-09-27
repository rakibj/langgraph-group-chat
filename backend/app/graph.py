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

M5 ("debate" strategy): the first two strategies still make every friend
answer the human. This one splits the chat into two phases: an intake where
only the manager talks, asking the human questions until it has a real
brief, then a debate where the friends argue with *each other* (tagging,
roasting, changing their minds) behind a hidden router. The router can
pause the debate to ask the human for one missing fact, and ends it by
calling a vote; the manager then weighs the arguments (not just the
headcount) into a verdict.
"""

import asyncio

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph

from app.personas import (
    DEBATE_PERSONA_MAX_TOKENS,
    DEBATE_PERSONAS,
    DEBATE_VOTE_INSTRUCTION,
    PERSONA_MAX_TOKENS,
    PERSONAS,
)
from app.schemas import DebateDecision, IntakeDecision, RoutingDecision, SilentRoutingDecision

MAX_HOPS_PER_TURN = 12

STRATEGIES = ("confidence", "background", "debate")
DEFAULT_STRATEGY = "confidence"


class State(MessagesState):
    next_speaker: str
    hop_count: int
    verdict_given: bool
    # "debate" strategy only
    phase: str  # "intake" until the manager hands the brief over, then "debate"
    debate_hops: int  # friend messages since the brief / the last verdict
    pending_question: str


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
    "Once the human has given the group what it needs to actually reason "
    "about this, stop routing back to them just to check in, paraphrase, or "
    "ask if they're sure — keep the turn inside the group instead. If two "
    "friends are actively disagreeing, route to whichever of them (or a "
    "third friend) would push the argument forward, and let that play out "
    "for several exchanges before you even consider a verdict or the human "
    "again. Only interrupt the group to go back to the human for a real, "
    "specific missing fact — never to manage the pace of the conversation.\n\n"
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
    "Once the human has given the group what it needs to actually reason "
    "about this, stop routing back to them just to check in or paraphrase — "
    "keep the turn inside the group instead. If two friends are actively "
    "disagreeing, route to whichever of them (or a third friend) would push "
    "the argument forward, and let that play out for several exchanges "
    "before considering a verdict or the human again. Only interrupt the "
    "group to go back to the human for a real, specific missing fact.\n\n"
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


# ---------------------------------------------------------------------------
# Strategy 3: manager briefing first, then the friends debate each other
# ---------------------------------------------------------------------------

INTAKE_MAX_QUESTIONS = 3  # manager question messages before it must hand off
DEBATE_MIN_HOPS = 8  # friend messages before a vote is allowed
DEBATE_REOPEN_MIN_HOPS = 3  # same, when re-debating after a verdict
DEBATE_MIN_HOPS_AFTER_USER = 3  # friends who react to new info from the human before a vote
DEBATE_MAX_HOPS_PER_TURN = 16

INTAKE_PROMPT = (
    "You're the manager of a group chat of six friends — a pragmatist, a "
    "skeptic, an optimist, an analyst, a contrarian, and a people person — "
    "who are about to debate a decision for the human. Before you let them "
    "loose, get the brief right. Ask about what actually matters for this "
    "specific decision: the concrete options, the key numbers (money, time, "
    "runway), hard constraints, what's at stake if it goes wrong, and their "
    "gut lean. One or two short questions per message, never repeat a "
    "question, casual and friendly (an emoji is fine). Don't share your own "
    "opinion.\n\n"
    "As soon as you have enough for a real argument, set ready=true — don't "
    "interrogate them. Two or three rounds of questions is usually plenty, "
    "and if their first message is already detailed you can go straight to "
    "ready. If they say they want to skip the questions, ask at most one "
    "round covering only what the group truly can't argue without."
)

INTAKE_WRAP_UP_NOTE = (
    "\n\nYou've asked enough questions — set ready=true now and write the "
    "brief from what you have."
)

DEBATE_ROUTER_PROMPT = (
    "You silently run a friend group chat that's debating a decision the "
    "human briefed you on — nobody sees you. After every message pick "
    "exactly one: a friend (" + ", ".join(PERSONAS) + "), 'ask_user', or "
    "'vote'.\n\n"
    "Your goal is a real argument that goes somewhere. Pick whoever would "
    "react most naturally and sharply to the last message: the friend who "
    "was just tagged or challenged, the one who'd most disagree, or an angle "
    "nobody has covered yet. Let disagreements play out across several "
    "back-and-forths — a quick two-person exchange is fun — but spread turns "
    "around so all six get a real say over the course of the debate.\n\n"
    "Pick 'ask_user' only when the argument is genuinely stuck on a specific "
    "fact only the human knows (a number, a constraint) and guessing would "
    "make the debate pointless — then write the question. Never ask for "
    "something the human already said or that's in the brief.\n\n"
    "If everyone is agreeing too easily, don't vote yet — bring in whoever "
    "is most likely to break the consensus (usually the contrarian or the "
    "skeptic) and let the group defend it. Pick 'vote' once positions have "
    "been stress-tested and the argument is starting to repeat itself."
)

DEBATE_REOPEN_NOTE = (
    "\n\nThe group already voted and the manager gave a verdict earlier. "
    "Let a few friends react to what the human just said. If it's new "
    "information that could change the call, let them argue it out and "
    "'vote' again; if it's just a follow-up or a thanks, keep it short and "
    "use 'ask_user' to hand the chat back (the question can be a light "
    "'anything else?')."
)

DEBATE_VOTE_CALL = "⏱️ ok time's up — everyone vote. ✅ do it, ❌ don't, 🤔 only if…"

DEBATE_VERDICT_PROMPT = (
    "You're the manager of this group chat. The friends just argued it out "
    "and voted. Now post the final verdict to the human. Start with "
    "'🧾 VERDICT:', then give one clear call: do it, don't, or do it only "
    "if X. Give the vote tally, name the one or two points from the debate "
    "that actually decided it (credit friends by @name), and the single "
    "biggest risk to watch. If you side against the majority, say so and "
    "why — you weigh arguments, you don't count heads. 4-6 sentences, "
    "casual and direct, an emoji or two is fine, no headers or bullet lists."
)


def _mentioned_personas(message) -> list[str]:
    text = message.content.lower() if isinstance(message.content, str) else ""
    return [
        p
        for p in PERSONAS
        if any(f"@{alias}" in text for alias in (p, p.replace("_", " "), p.replace("_", "")))
    ]


def _speakers_since_kickoff(messages) -> set[str]:
    speakers = set()
    for m in reversed(messages):
        if m.additional_kwargs.get("kind") == "kickoff":
            break
        if getattr(m, "name", None) in PERSONAS and m.additional_kwargs.get("kind") != "vote":
            speakers.add(m.name)
    return speakers


def _as_seen_by(name: str, messages) -> list:
    """The chat from one friend's point of view. Every friend's reply is an
    AIMessage, so passed through as-is each friend would read the whole
    group's messages as things *it* said (and start moderating, or tagging
    itself). Only its own messages stay as its turns; everyone else's become
    labelled lines, the way a group chat actually reads."""
    seen = []
    for m in messages:
        speaker = getattr(m, "name", None)
        if m.type == "ai" and speaker == name:
            seen.append(AIMessage(content=m.content))
        elif m.type == "human":
            seen.append(HumanMessage(content=f"human (the one deciding): {m.content}"))
        else:
            seen.append(HumanMessage(content=f"{speaker}: {m.content}"))
    return seen


def _next_in_rotation(last_speaker: str | None) -> str:
    order = list(PERSONAS)
    if last_speaker not in order:
        return order[0]
    return order[(order.index(last_speaker) + 1) % len(order)]


async def _build_debate_graph(checkpointer):
    llm = ChatOpenAI(model="gpt-5.6-luna", temperature=0, reasoning_effort="none")
    # Banter needs some variety — at temperature 0 every friend's jokes land
    # the same way every time.
    persona_llm = ChatOpenAI(
        model="gpt-5.6-luna", temperature=0.9, reasoning_effort="none"
    ).bind(max_tokens=DEBATE_PERSONA_MAX_TOKENS)
    intake_llm = llm.with_structured_output(IntakeDecision)
    router = llm.with_structured_output(DebateDecision)

    def route_by_phase(state: State):
        return "router" if state.get("phase") == "debate" else "intake"

    async def intake_node(state: State):
        asked = sum(
            1
            for m in state["messages"]
            if getattr(m, "name", None) == "manager"
            and m.additional_kwargs.get("kind") == "to_user"
        )
        prompt = INTAKE_PROMPT
        if asked >= INTAKE_MAX_QUESTIONS:
            prompt += INTAKE_WRAP_UP_NOTE
        decision = await intake_llm.ainvoke([SystemMessage(content=prompt), *state["messages"]])

        if not decision.ready and asked < INTAKE_MAX_QUESTIONS:
            question = AIMessage(
                name="manager", content=decision.message, additional_kwargs={"kind": "to_user"}
            )
            return {"messages": [question], "phase": "intake"}

        brief = decision.brief.strip()
        content = f"{decision.message}\n\n**The brief:** {brief}" if brief else decision.message
        kickoff = AIMessage(name="manager", content=content, additional_kwargs={"kind": "kickoff"})
        return {"messages": [kickoff], "phase": "debate", "hop_count": 0, "debate_hops": 0}

    def route_from_intake(state: State):
        return "router" if state.get("phase") == "debate" else END

    async def router_node(state: State):
        messages = state["messages"]
        last_speaker = _last_persona_speaker(messages)
        hop_count = state.get("hop_count", 0)
        debate_hops = state.get("debate_hops", 0)
        min_hops = DEBATE_REOPEN_MIN_HOPS if state.get("verdict_given") else DEBATE_MIN_HOPS

        called_out = []
        if getattr(messages[-1], "name", None) in PERSONAS:
            called_out = [p for p in _mentioned_personas(messages[-1]) if p != last_speaker]

        prompt = DEBATE_ROUTER_PROMPT
        if state.get("verdict_given"):
            prompt += DEBATE_REOPEN_NOTE
        if called_out:
            prompt += (
                f"\n\n{last_speaker} just tagged {', '.join(called_out)} — unless "
                "the group is stuck on a missing fact, let them clap back next."
            )
        # Too early to vote until the debate has had real room — and until a
        # few friends have reacted to whatever the human just told them.
        vote_blocked = debate_hops < min_hops or hop_count < DEBATE_MIN_HOPS_AFTER_USER
        if vote_blocked:
            prompt += "\n\nIt's too early to vote — the group hasn't argued this enough yet. Don't pick 'vote'."
        quiet = [p for p in PERSONAS if p not in _speakers_since_kickoff(messages)]
        if quiet:
            prompt += (
                f"\n\nHaven't said anything in the debate yet: {', '.join(quiet)}. "
                "Bring them in soon — nobody gets a third message before they've spoken."
            )

        decision = await _route_avoiding_repeat(router, prompt, messages, last_speaker)
        next_speaker = decision.next

        if next_speaker not in PERSONAS and next_speaker not in ("ask_user", "vote"):
            next_speaker = called_out[0] if called_out else _next_in_rotation(last_speaker)
        if next_speaker == "vote" and vote_blocked:
            next_speaker = called_out[0] if called_out else _next_in_rotation(last_speaker)
        if next_speaker == "ask_user" and (hop_count == 0 or not decision.question.strip()):
            # Someone has to react to what the human just said before the
            # manager interrupts again — and never interrupt with nothing.
            next_speaker = _next_in_rotation(last_speaker)
        if next_speaker in PERSONAS and hop_count >= DEBATE_MAX_HOPS_PER_TURN:
            next_speaker = "vote"

        return {
            "next_speaker": next_speaker,
            "pending_question": decision.question if next_speaker == "ask_user" else "",
        }

    def route_from_router(state: State):
        speaker = state["next_speaker"]
        if speaker in PERSONAS:
            return speaker
        return "call_vote" if speaker == "vote" else "ask_user"

    def make_debate_persona_node(name: str, system_prompt: str):
        async def persona_node(state: State):
            context = [SystemMessage(content=system_prompt), *_as_seen_by(name, state["messages"])]
            response = await persona_llm.ainvoke(context)
            if not str(response.content).strip():
                # The model occasionally returns nothing; one retry, then
                # skip the turn rather than post an empty bubble.
                response = await persona_llm.ainvoke(context)
            counters = {
                "hop_count": state.get("hop_count", 0) + 1,
                "debate_hops": state.get("debate_hops", 0) + 1,
            }
            if not str(response.content).strip():
                return counters
            response.name = name
            return {"messages": [response], **counters}

        return persona_node

    async def ask_user_node(state: State):
        question = AIMessage(
            name="manager",
            content=state["pending_question"],
            additional_kwargs={"kind": "to_user"},
        )
        return {"messages": [question], "hop_count": 0, "pending_question": ""}

    async def call_vote_node(state: State):
        call = AIMessage(
            name="manager", content=DEBATE_VOTE_CALL, additional_kwargs={"kind": "vote_call"}
        )
        return {"messages": [call]}

    async def vote_node(state: State):
        async def cast(name: str, system_prompt: str):
            response = await persona_llm.ainvoke(
                [
                    SystemMessage(content=system_prompt + DEBATE_VOTE_INSTRUCTION),
                    *_as_seen_by(name, state["messages"]),
                ]
            )
            response.name = name
            response.additional_kwargs = {"kind": "vote"}
            return response

        votes = await asyncio.gather(*(cast(n, p) for n, p in DEBATE_PERSONAS.items()))
        return {"messages": [v for v in votes if str(v.content).strip()]}

    async def verdict_node(state: State):
        response = await llm.ainvoke(
            [SystemMessage(content=DEBATE_VERDICT_PROMPT), *state["messages"]]
        )
        response.name = "manager"
        response.additional_kwargs = {"kind": "verdict"}
        return {
            "messages": [response],
            "verdict_given": True,
            "hop_count": 0,
            "debate_hops": 0,
        }

    graph_builder = StateGraph(State)
    graph_builder.add_node("intake", intake_node)
    graph_builder.add_node("router", router_node)
    graph_builder.add_node("ask_user", ask_user_node)
    graph_builder.add_node("call_vote", call_vote_node)
    graph_builder.add_node("vote", vote_node)
    graph_builder.add_node("verdict", verdict_node)

    graph_builder.add_conditional_edges(START, route_by_phase, ["intake", "router"])
    graph_builder.add_conditional_edges("intake", route_from_intake, ["router", END])

    for name, system_prompt in DEBATE_PERSONAS.items():
        graph_builder.add_node(name, make_debate_persona_node(name, system_prompt))
        graph_builder.add_edge(name, "router")

    graph_builder.add_conditional_edges(
        "router", route_from_router, list(PERSONAS) + ["ask_user", "call_vote"]
    )
    graph_builder.add_edge("ask_user", END)
    graph_builder.add_edge("call_vote", "vote")
    graph_builder.add_edge("vote", "verdict")
    graph_builder.add_edge("verdict", END)

    return graph_builder.compile(checkpointer=checkpointer)


_BUILDERS = {
    "confidence": _build_confidence_graph,
    "background": _build_background_graph,
    "debate": _build_debate_graph,
}


async def build_graph(checkpointer, strategy: str = DEFAULT_STRATEGY):
    if strategy not in _BUILDERS:
        raise ValueError(f"unknown strategy {strategy!r}, expected one of {STRATEGIES}")
    return await _BUILDERS[strategy](checkpointer)
