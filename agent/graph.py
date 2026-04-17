from langgraph.graph import END, START, StateGraph

from agent.nodes.curriculum_parser import curriculum_parser_node
from agent.nodes.diagnostician import diagnostician_node
from agent.nodes.resource_retriever import resource_retriever_node
from agent.nodes.roadmap_planner import roadmap_planner_node
from agent.nodes.spaced_rep import spaced_rep_node


# Routing Function
def route_entry(state: dict) -> str:
    """
    Academic Mode → runs Diagnostician (Node 1) first.
    Explorer Mode → skips directly to Curriculum Parser (Node 2).
    """
    mode = state.get("mode", "explorer")
    print(f"[graph] Routing — mode={mode}")
    return "diagnostician" if mode == "academic" else "curriculum_parser"


# Building Graph
def build_graph():
    from agent.state import GradeMindsState

    graph = StateGraph(GradeMindsState)

    # Register all nodes
    graph.add_node("diagnostician", diagnostician_node)
    graph.add_node("curriculum_parser", curriculum_parser_node)
    graph.add_node("roadmap_planner", roadmap_planner_node)
    graph.add_node("spaced_rep", spaced_rep_node)
    graph.add_node("resource_retriever", resource_retriever_node)

    # Conditional entry point — branches on mode
    graph.add_conditional_edges(
        START,
        route_entry,
        {
            "diagnostician": "diagnostician",
            "curriculum_parser": "curriculum_parser",
        },
    )

    # Diagnostician always feeds into Curriculum Parser
    graph.add_edge("diagnostician", "curriculum_parser")

    # Fixed downstream chain — same for both modes
    graph.add_edge("curriculum_parser", "roadmap_planner")
    graph.add_edge("roadmap_planner", "spaced_rep")
    graph.add_edge("spaced_rep", "resource_retriever")
    graph.add_edge("resource_retriever", END)

    return graph.compile()


app = build_graph()
