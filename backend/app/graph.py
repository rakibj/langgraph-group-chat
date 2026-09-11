"""LangGraph group-chat agent, checkpointed to SQLite.

M2 (routing/turn-taking): a manager node reads the conversation and picks
which persona(s) should respond this turn — not all six every time. The
manager's decision is appended to the message list as a visible "manager"
message so the UI can show who was routed to and why. Replace/extend with
real nodes, edges, and interrupt() review steps as the project grows.
"""

from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph

from app.schemas import RoutingDecision

GROUP_CHAT_STYLE = (
    "You're one of six close friends this person texts when they need to think "
    "something through — not a consultant, not an assistant. Talk like a friend "
    "who actually knows them: warm, direct, a little informal. 1-2 short "
    "sentences, max. No headers, no bullet lists, no markdown, no "
    "'firstly/secondly'.\n\n"
    "Your job isn't to hand them a verdict — it's to push their thinking from "
    "your specific angle. Prefer a sharp question, a reframe, or a concrete "
    "example/data point over a flat opinion. If you cite a number, keep it "
    "quick and real-feeling (a rough stat, a benchmark, a 'most people in this "
    "spot...') — not a citation, just the kind of thing a sharp friend would "
    "actually know off the top of their head."
)

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
    "your own opinion, you just have a feel for who should say something next: "
    + ", ".join(PERSONAS)
    + ". Given the conversation so far, pick only the friends who'd genuinely "
    "add a fresh angle right now, the way a real group chat naturally has one "
    "or two people jump in rather than all six dogpiling every message. Always "
    "let at least one through."
)


class State(MessagesState):
    next_speakers: list[str]


async def build_graph(checkpointer):
    llm = ChatOpenAI(model="gpt-5.6-luna", temperature=0, reasoning_effort="none")
    router = llm.with_structured_output(RoutingDecision)

    async def manager_node(state: State):
        messages = [SystemMessage(content=MANAGER_PROMPT), *state["messages"]]
        decision = await router.ainvoke(messages)
        speakers = [name for name in decision.speakers if name in PERSONAS] or [
            next(iter(PERSONAS))
        ]
        labels = ", ".join(name.replace("_", " ").title() for name in speakers)
        manager_message = AIMessage(
            name="manager",
            content=f"Routing to: {labels} — {decision.reasoning}",
        )
        return {"messages": [manager_message], "next_speakers": speakers}

    def make_persona_node(name: str, system_prompt: str):
        async def persona_node(state: State):
            messages = [SystemMessage(content=system_prompt), *state["messages"]]
            response = await llm.ainvoke(messages)
            response.name = name
            return {"messages": [response]}

        return persona_node

    def route_to_speakers(state: State):
        return state["next_speakers"]

    graph_builder = StateGraph(State)

    graph_builder.add_node("manager", manager_node)
    graph_builder.add_edge(START, "manager")

    for name, system_prompt in PERSONAS.items():
        graph_builder.add_node(name, make_persona_node(name, system_prompt))
        graph_builder.add_edge(name, END)

    graph_builder.add_conditional_edges(
        "manager", route_to_speakers, list(PERSONAS)
    )

    graph = graph_builder.compile(checkpointer=checkpointer)
    return graph
