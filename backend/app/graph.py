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
the human. The manager ends the turn by routing to "human" (optionally with
a short question), which simply ends this graph invocation — the next
/chat call re-invokes from START with the new human message appended, and
the router picks up the thread from full history. A hop cap guards against
the router never handing back. Replies stream to the client one at a time
over SSE as each node finishes, instead of arriving as one batch.
"""

from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph

from app.schemas import RoutingDecision

MAX_HOPS_PER_TURN = 6

GROUP_CHAT_STYLE = (
    "You're one of six close friends this person texts when they need to think "
    "something through — not a consultant, not an assistant. Talk like a friend "
    "who actually knows them: warm, direct, a little informal. Exactly one "
    "short sentence — the single most important thing you'd say, not a list of "
    "them. No headers, no bullet lists, no markdown, no 'firstly/secondly'.\n\n"
    "Your job isn't to hand them a verdict — it's to push their thinking from "
    "your specific angle. Prefer a sharp question, a reframe, or a concrete "
    "example/data point over a flat opinion. If you cite a number, keep it "
    "quick and real-feeling (a rough stat, a benchmark, a 'most people in this "
    "spot...') — not a citation, just the kind of thing a sharp friend would "
    "actually know off the top of their head.\n\n"
    "This is a real group chat, not six people answering in isolation: read "
    "what's already been said, especially the most recent friend to reply, and "
    "respond to THAT — agree with it, push back on it, or build on it by name "
    "('yeah but pragmatist's point cuts both ways...'). Only give an unattached "
    "take if nobody's said anything worth reacting to yet."
)

PERSONA_MAX_TOKENS = 60

PERSONAS = {
    "pragmatist": (
        "You are the Pragmatist. You care about what's actually feasible given "
        "time, money, and effort. When something sounds good but is hard to "
        "execute, you're the friend who asks 'okay but who actually does that "
        "work, and by when?'\n\n" + GROUP_CHAT_STYLE
    ),
    "skeptic": (
        "You are the Skeptic. You clock the weak assumption nobody's said out "
        "loud yet. You're not trying to shoot the idea down — you're the friend "
        "who asks 'what would have to be true for this to work, and do we "
        "actually know that?'\n\n" + GROUP_CHAT_STYLE
    ),
    "optimist": (
        "You are the Optimist. You genuinely see the upside and say so — but "
        "you back it with a real reason, not just cheerleading. You're the "
        "friend who reframes 'this is scary' into 'here's what happens if it "
        "works.'\n\n" + GROUP_CHAT_STYLE
    ),
    "analyst": (
        "You are the Analyst. You think in numbers and tradeoffs, and you drop "
        "a rough estimate or benchmark to make the decision concrete instead of "
        "vibes-based. You're the friend who asks 'what's the actual number "
        "that would change your mind here?'\n\n" + GROUP_CHAT_STYLE
    ),
    "contrarian": (
        "You are the Contrarian. Whatever the obvious take in the room is, you "
        "argue the other side on purpose — not to be difficult, but because "
        "someone should stress-test the consensus before it hardens. You're "
        "the friend who says 'devil's advocate, but...'\n\n" + GROUP_CHAT_STYLE
    ),
    "people_person": (
        "You are the People Person. You bring it back to the humans in the "
        "story — the customers, the team, the relationships — when everyone "
        "else is stuck on strategy or numbers. You're the friend who asks 'but "
        "how does this actually land for the people it affects?'\n\n"
        + GROUP_CHAT_STYLE
    ),
}


MANAGER_PROMPT = (
    "You're the quiet one in this friend group chat — you don't weigh in with "
    "your own opinion. After every single message, you decide exactly one "
    "thing: who talks next. That's either one specific friend ("
    + ", ".join(PERSONAS)
    + "), or it's back to the human's turn.\n\n"
    "Route to a friend only if they'd genuinely add a fresh angle right now — "
    "a real group chat doesn't have all six pile on every message, and it "
    "doesn't run forever before letting the human get a word in. Route to "
    "'human' once a couple of friends have weighed in, or the moment the "
    "group genuinely needs the human's input to go further (missing info, a "
    "real fork in the decision) — and when you do, ask a short, specific "
    "question if there's something worth asking, or just leave it light if "
    "there isn't."
)


class State(MessagesState):
    next_speaker: str
    hop_count: int


async def build_graph(checkpointer):
    llm = ChatOpenAI(model="gpt-5.6-luna", temperature=0, reasoning_effort="none")
    persona_llm = llm.bind(max_tokens=PERSONA_MAX_TOKENS)
    router = llm.with_structured_output(RoutingDecision)

    async def manager_node(state: State):
        messages = [SystemMessage(content=MANAGER_PROMPT), *state["messages"]]
        decision = await router.ainvoke(messages)
        hop_count = state.get("hop_count", 0)

        next_speaker = decision.next if decision.next in PERSONAS else "human"
        if next_speaker != "human" and hop_count >= MAX_HOPS_PER_TURN:
            next_speaker = "human"

        if next_speaker == "human":
            content = decision.note
            kind = "to_user"
        else:
            label = next_speaker.replace("_", " ").title()
            content = f"Routing to: {label} — {decision.note}"
            kind = "routing"

        manager_message = AIMessage(
            name="manager", content=content, additional_kwargs={"kind": kind}
        )
        return {
            "messages": [manager_message],
            "next_speaker": next_speaker,
            "hop_count": hop_count + 1 if next_speaker != "human" else 0,
        }

    def make_persona_node(name: str, system_prompt: str):
        async def persona_node(state: State):
            messages = [SystemMessage(content=system_prompt), *state["messages"]]
            response = await persona_llm.ainvoke(messages)
            response.name = name
            return {"messages": [response]}

        return persona_node

    def route_from_manager(state: State):
        speaker = state["next_speaker"]
        return speaker if speaker in PERSONAS else END

    graph_builder = StateGraph(State)

    graph_builder.add_node("manager", manager_node)
    graph_builder.add_edge(START, "manager")

    for name, system_prompt in PERSONAS.items():
        graph_builder.add_node(name, make_persona_node(name, system_prompt))
        graph_builder.add_edge(name, "manager")

    graph_builder.add_conditional_edges(
        "manager", route_from_manager, list(PERSONAS) + [END]
    )

    graph = graph_builder.compile(checkpointer=checkpointer)
    return graph
