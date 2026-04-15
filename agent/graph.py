from agent.nodes.curriculum_parser import curriculum_parser_node
from agent.nodes.roadmap_planner import roadmap_planner_node


class GradeMindsAgent:
    def invoke(self, state: dict) -> dict:
        state = curriculum_parser_node(state)
        state = roadmap_planner_node(state)
        return state


app = GradeMindsAgent()
