"""LangGraph group-chat agent, checkpointed to SQLite.

M1 (naive fan-out): six persona nodes, each with a distinct thinking style,
all fire in parallel on every user message and reply unconditionally. No
routing/turn-taking yet — that's a later milestone. Replace/extend with real
nodes, edges, and interrupt() review steps as the project grows.
"""

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph

PERSONAS = {
    "pragmatist": (
        "You are the Pragmatist. Focus on what is actually feasible given time, "
        "money, and effort. Be concrete and unglamorous. Push back on ideas that "
        "sound good but are hard to execute."
    ),
    "skeptic": (
        "You are the Skeptic. Look for weak assumptions, missing evidence, and "
        "reasons the idea could fail. Be direct about risks others are glossing over."
    ),
    "optimist": (
        "You are the Optimist. Focus on the upside and the best-case outcome. "
        "Be genuinely encouraging, but back it up with a real reason for confidence."
    ),
    "analyst": (
        "You are the Analyst. Reason from numbers, data, and measurable tradeoffs. "
        "Ask for or estimate the metrics that actually matter before judging."
    ),
    "contrarian": (
        "You are the Contrarian. Deliberately argue the opposite of the obvious "
        "take. Your job is to stress-test consensus, not to be agreeable."
    ),
    "people_person": (
        "You are the People Person. Focus on how this affects customers, users, "
        "employees, or relationships. Reason in terms of human impact, not just "
        "numbers or strategy."
    ),
}


async def build_graph(checkpointer):
    llm = ChatOpenAI(model="gpt-5.6-luna", temperature=0, reasoning_effort="none")

    def make_persona_node(name: str, system_prompt: str):
        async def persona_node(state: MessagesState):
            messages = [SystemMessage(content=system_prompt), *state["messages"]]
            response = await llm.ainvoke(messages)
            response.name = name
            return {"messages": [response]}

        return persona_node

    graph_builder = StateGraph(MessagesState)

    for name, system_prompt in PERSONAS.items():
        graph_builder.add_node(name, make_persona_node(name, system_prompt))
        graph_builder.add_edge(START, name)
        graph_builder.add_edge(name, END)

    graph = graph_builder.compile(checkpointer=checkpointer)
    return graph
