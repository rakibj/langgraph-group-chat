"""Minimal LangGraph tool-calling agent, checkpointed to SQLite.

Starter structure: one agent node that can call tools in a loop. Replace/extend
with real nodes, edges, and interrupt() review steps as the project grows.
"""

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.tools import echo


async def build_graph(checkpointer):
    tools = [echo]

    llm = ChatOpenAI(model="gpt-4.1", temperature=0)
    llm_with_tools = llm.bind_tools(tools)

    async def agent(state: MessagesState):
        response = await llm_with_tools.ainvoke(state["messages"])
        return {"messages": [response]}

    graph_builder = StateGraph(MessagesState)
    graph_builder.add_node("agent", agent)
    graph_builder.add_node("tools", ToolNode(tools))

    graph_builder.add_edge(START, "agent")
    graph_builder.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    graph_builder.add_edge("tools", "agent")

    graph = graph_builder.compile(checkpointer=checkpointer)
    return graph
