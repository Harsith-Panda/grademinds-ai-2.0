import json
import os
import time
from collections import defaultdict, deque

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from pydantic import BaseModel, validator

from memory.chroma_ops import load_roadmap, save_roadmap
from memory.student_registry import mark_roadmap_ready

load_dotenv()

llm = ChatGroq(
    model="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.2,
    max_retries=2,
)

MAX_RETRIES = 2


# Output Schema -> Validation for LLM output (What our system expects)
class WeekPlan(BaseModel):
    week: int
    topics: list[str]
    total_hours: float
    focus: str  # one sentence -> Goal for this week

    @validator("week")
    def week_positive(cls, v):
        if v < 1:
            raise ValueError("Week must be >= 1")
        return v

    @validator("topics")
    def topics_not_empty(cls, v):
        if not v:
            raise ValueError("Week must have at least one topic")
        return v

    @validator("total_hours")
    def hours_positive(cls, v):
        return max(0.5, float(v))


# Topo Sort (Topo Sort using khan's algorithm so each prerequisites comes before)
def topological_sort(topic_graph: list[dict]) -> list[dict]:
    """
    Sort topics so every prerequisite comes before the topic that needs it.
    Uses Kahn's algorithm. Cycles are broken by dropping the offending edge.
    """
    name_to_node = {t["name"]: t for t in topic_graph}
    in_degree = defaultdict(int)
    adj = defaultdict(list)

    for node in topic_graph:
        for prereq in node.get("prerequisites", []):
            if prereq in name_to_node and prereq != node["name"]:
                adj[prereq].append(node["name"])
                in_degree[node["name"]] += 1

    # Nodes with no prerequisites go first
    queue = deque(n["name"] for n in topic_graph if in_degree[n["name"]] == 0)
    sorted_names = []

    while queue:
        name = queue.popleft()
        sorted_names.append(name)
        for dependent in adj[name]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    seen = set(sorted_names)
    for node in topic_graph:
        if node["name"] not in seen:
            sorted_names.append(node["name"])

    return [name_to_node[n] for n in sorted_names if n in name_to_node]


# Assigning Topics to weeks
def pack_into_weeks(
    sorted_topics: list[dict],
    hours_per_week: int,
    week_focuses: dict[str, str],
) -> list[dict]:
    """
    Greedily assign topics to weeks based on estimated_hours.
    Must-know topics are always scheduled before enrichment topics.
    """
    must_know = [t for t in sorted_topics if t.get("type") == "must_know"]
    enrichment = [t for t in sorted_topics if t.get("type") != "must_know"]
    ordered = must_know + enrichment

    weeks = []
    current_week = []
    current_hrs = 0.0
    week_num = 1

    def flush_week():
        nonlocal current_week, current_hrs, week_num
        if not current_week:
            return
        topic_names = [t["name"] for t in current_week]
        focus = next(
            (week_focuses.get(n) for n in topic_names if week_focuses.get(n)),
            f"Complete {', '.join(topic_names[:2])}{'...' if len(topic_names) > 2 else ''}",
        )
        weeks.append(
            {
                "week": week_num,
                "topics": topic_names,
                "total_hours": round(current_hrs, 1),
                "focus": focus,
            }
        )
        week_num += 1
        current_week = []
        current_hrs = 0.0

    for topic in ordered:
        est = topic.get("estimated_hours", 1.0)

        if est >= hours_per_week:
            flush_week()
            weeks.append(
                {
                    "week": week_num,
                    "topics": [topic["name"]],
                    "total_hours": round(est, 1),
                    "focus": week_focuses.get(
                        topic["name"], f"Deep dive into {topic['name']}"
                    ),
                }
            )
            week_num += 1
            continue

        if current_hrs + est > hours_per_week and current_week:
            flush_week()

        current_week.append(topic)
        current_hrs += est

    flush_week()
    return weeks


# Prompt Builder
def _build_prompt(
    topic_graph: list[dict],
    hours_per_week: int,
    goal: str,
    diagnosis_context: str,
) -> str:
    graph_json = json.dumps(topic_graph, indent=2)
    return f"""You are an expert study planner. Output ONLY valid JSON. No preamble.

        Given this topic graph:
        {graph_json}

        Student details:
        - Available hours per week: {hours_per_week}
        - End goal: "{goal}"{diagnosis_context}

        For each topic, provide a one-sentence "focus" describing what the student
        should be able to do by the end of that study session.

        Return a JSON object:
        {{
          "week_focuses": {{
            "topic name": "focus sentence for this topic"
          }}
        }}

        Rules:
        - Every topic in the graph must have a focus entry.
        - Focuses should be specific and action-oriented (e.g. "Implement linear regression from scratch in Python").
        - Match the Bloom's level: lower levels = comprehension focus, higher = application/creation focus.
        - Keep each focus under 15 words.
    """


def _correction_prompt(bad_json: str, error_msg: str) -> str:
    return f"""Your previous JSON caused this error: {error_msg}

        Return ONLY the corrected JSON object. No explanation.
        Broken output was:
        {bad_json}
    """


# Parser
def _parse_focuses(raw: str) -> dict[str, str]:
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else parts[0]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())
    focuses = data.get("week_focuses", data)  # handle both shapes
    if not isinstance(focuses, dict):
        raise ValueError("week_focuses must be a dict")
    return focuses


def _validate_weeks(weeks: list[dict]) -> list[dict]:
    validated = []
    for w in weeks:
        try:
            validated.append(WeekPlan(**w).dict())
        except Exception as e:
            print(f"[roadmap_planner] Skipping invalid week: {e}")
    return validated


# Main Node - Actual Roadmap Planner Node
def roadmap_planner_node(state: dict) -> dict:
    student_id = state.get("student_id")
    course_id = state.get("course_id")

    existing_roadmap = load_roadmap(course_id)
    if existing_roadmap:
        print(f"[roadmap_planner] Loaded saved roadmap for course {course_id}.")
        return {**state, "roadmap": existing_roadmap}

    topic_graph = state.get("topic_graph")
    if not topic_graph:
        print("[roadmap_planner] No topic_graph in state — skipping.")
        return state

    sa = state.get("self_assessment", {})
    hours_per_week = int(sa.get("hours_per_week", 5))
    goal = sa.get("goal", "understand the topic")

    # Diagnosis priority signal (Academic Mode only)
    diagnosis = state.get("diagnosis", {})
    diagnosis_context = ""
    if diagnosis:
        weak = diagnosis.get("weak_areas", [])
        if weak:
            factors = ", ".join(w["factor"] for w in weak)
            diagnosis_context = f"\n- Prioritize weak areas: {factors}"

    # 1 — topological sort (Performed by code, not by LLM)
    sorted_topics = topological_sort(topic_graph)
    print(f"[roadmap_planner] Sorted {len(sorted_topics)} topics topologically.")

    # 2 — get per-topic focus sentences from LLM
    prompt = _build_prompt(sorted_topics, hours_per_week, goal, diagnosis_context)
    raw = ""
    week_focuses: dict[str, str] = {}
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if attempt == 1:
                response = llm.invoke(prompt)
            else:
                print(f"[roadmap_planner] Retry {attempt} after: {last_error}")
                response = llm.invoke(_correction_prompt(raw, str(last_error)))
                time.sleep(1)

            raw = response.content.strip()
            week_focuses = _parse_focuses(raw)
            print(f"[roadmap_planner] Got {len(week_focuses)} focus sentences.")
            break

        except Exception as e:
            last_error = e
            continue

    # 3 — pack topics into weeks, plan the week (done in code)
    weeks = pack_into_weeks(sorted_topics, hours_per_week, week_focuses)

    # 4 — validate output schema
    validated_weeks = _validate_weeks(weeks)

    if not validated_weeks:
        print("[roadmap_planner] Validation produced empty roadmap — using fallback.")
        validated_weeks = [
            {
                "week": 1,
                "topics": [t["name"] for t in sorted_topics],
                "total_hours": sum(
                    t.get("estimated_hours", 1.0) for t in sorted_topics
                ),
                "focus": f"Complete the full {state.get('topic', 'course')} roadmap",
            }
        ]

    print(f"[roadmap_planner] Final roadmap: {len(validated_weeks)} weeks.")

    save_roadmap(student_id, course_id, validated_weeks)
    mark_roadmap_ready(
        student_id,
        course_id,
        total_topics=sum(len(w["topics"]) for w in validated_weeks),
    )

    return {**state, "roadmap": validated_weeks}
