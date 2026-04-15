import json
import os
import time
from datetime import date, datetime

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from pydantic import BaseModel, validator

from memory.chroma_ops import topics

load_dotenv()

llm = ChatGroq(
    model="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.2,
    max_retries=2,
)

MAX_RETRIES = 2
MAX_REVIEW_TOPICS = 2


class TaskTopic(BaseModel):
    name: str
    week: int
    estimated_hours: float
    bloom_level: int
    type: str
    status: str
    days_since_last_reviewed: int | None = None
    review_interval: int | None = None
    struggled_last: bool = False

    @validator("week")
    def week_positive(cls, v):
        if v < 1:
            raise ValueError("week must be >= 1")
        return v

    @validator("estimated_hours")
    def hours_positive(cls, v):
        return max(0.5, float(v))

    @validator("bloom_level")
    def bloom_in_range(cls, v):
        if not 1 <= int(v) <= 6:
            raise ValueError("bloom_level must be between 1 and 6")
        return int(v)

    @validator("type")
    def valid_type(cls, v):
        v = (v or "must_know").lower().replace("-", "_").replace(" ", "_")
        if v not in ("must_know", "enrichment"):
            return "must_know"
        return v

    @validator("status")
    def valid_status(cls, v):
        allowed = {"not_started", "in_progress", "done"}
        if v not in allowed:
            return "not_started"
        return v

    @validator("days_since_last_reviewed", "review_interval")
    def non_negative_optional(cls, v):
        if v is None:
            return None
        if int(v) < 0:
            raise ValueError("value must be >= 0")
        return int(v)


class TodaysPlan(BaseModel):
    session_date: str
    current_week: int
    new_topic: TaskTopic | None
    review_topics: list[TaskTopic]
    total_estimated_hours: float

    @validator("current_week")
    def current_week_positive(cls, v):
        if v < 1:
            raise ValueError("current_week must be >= 1")
        return v

    @validator("review_topics")
    def review_limit(cls, v):
        if len(v) > MAX_REVIEW_TOPICS:
            raise ValueError(f"review_topics must contain at most {MAX_REVIEW_TOPICS}")
        return v

    @validator("total_estimated_hours")
    def total_hours_non_negative(cls, v):
        return max(0.0, float(v))


def _correction_prompt(bad_json: str, error_msg: str) -> str:
    return f"""Your previous JSON caused this error: {error_msg}

Return ONLY the corrected JSON object. No explanation.

Expected shape:
{{
  "session_date": "YYYY-MM-DD",
  "current_week": 1,
  "new_topic": {{
    "name": "topic",
    "week": 1,
    "estimated_hours": 1.0,
    "bloom_level": 2,
    "type": "must_know",
    "status": "not_started",
    "days_since_last_reviewed": null,
    "review_interval": null,
    "struggled_last": false
  }},
  "review_topics": [],
  "total_estimated_hours": 1.0
}}

Broken output was:
{bad_json}
"""


def _parse_and_validate(raw: str) -> dict:
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else parts[0]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw.strip())
    validated = TodaysPlan(**data)
    return validated.dict()


def _safe_date(raw_date: str | None) -> date:
    if raw_date:
        try:
            return date.fromisoformat(raw_date)
        except Exception:
            pass
    return date.today()


def _days_since(last_reviewed: str, today: date) -> int | None:
    if not last_reviewed:
        return None
    try:
        reviewed_dt = datetime.fromisoformat(last_reviewed).date()
        return max(0, (today - reviewed_dt).days)
    except Exception:
        return None


def _topic_details(
    topic_name: str,
    meta: dict,
    graph_lookup: dict[str, dict],
) -> dict:
    graph_topic = graph_lookup.get(topic_name, {})
    return {
        "name": topic_name,
        "week": int(meta.get("week", 1) or 1),
        "estimated_hours": float(graph_topic.get("estimated_hours", 1.0)),
        "bloom_level": int(meta.get("bloom_level", graph_topic.get("bloom_level", 1))),
        "type": meta.get("topic_type", graph_topic.get("type", "must_know")),
        "status": meta.get("status", "not_started"),
        "days_since_last_reviewed": None,
        "review_interval": None,
        "struggled_last": bool(meta.get("struggled_last", False)),
    }


def _load_course_topics(student_id: str, course_id: str) -> list[dict]:
    result = topics.get(where={"course_id": course_id})
    if not result["ids"]:
        print(f"[spaced_rep] No topic records found for course {course_id}.")
        return []

    topic_rows = []
    for doc_id, doc, meta in zip(
        result["ids"], result["documents"], result["metadatas"]
    ):
        if meta.get("student_id") != student_id:
            continue
        topic_rows.append({"id": doc_id, "name": doc, **meta})

    print(
        f"[spaced_rep] Loaded {len(topic_rows)} topic records for student {student_id} in course {course_id}."
    )
    return topic_rows


def _find_current_week(roadmap: list[dict], topic_meta: dict[str, dict]) -> int:
    for week in roadmap:
        week_topics = week.get("topics", [])
        if any(topic_meta.get(name, {}).get("status") != "done" for name in week_topics):
            return int(week.get("week", 1) or 1)
    if roadmap:
        return int(roadmap[-1].get("week", 1) or 1)
    return 1


def _pick_new_topic(
    roadmap: list[dict],
    current_week: int,
    topic_meta: dict[str, dict],
    graph_lookup: dict[str, dict],
) -> dict | None:
    current_week_block = next(
        (week for week in roadmap if int(week.get("week", 0)) == current_week),
        None,
    )
    if not current_week_block:
        return None

    for topic_name in current_week_block.get("topics", []):
        meta = topic_meta.get(topic_name, {})
        status = meta.get("status", "not_started")
        if status == "not_started":
            print(f"[spaced_rep] Selected new topic '{topic_name}' from week {current_week}.")
            return _topic_details(
                topic_name,
                {
                    **meta,
                    "week": meta.get("week", current_week),
                    "status": status,
                },
                graph_lookup,
            )
    print(f"[spaced_rep] No new topic available in week {current_week}.")
    return None


def _pick_review_topics(
    topic_rows: list[dict],
    today: date,
    graph_lookup: dict[str, dict],
) -> list[dict]:
    due_topics = []

    for topic in topic_rows:
        if topic.get("status") != "done":
            continue

        days_since = _days_since(topic.get("last_reviewed", ""), today)
        interval = int(topic.get("review_interval", 1) or 1)

        if days_since is None or days_since < interval:
            continue

        item = _topic_details(topic["name"], topic, graph_lookup)
        item["days_since_last_reviewed"] = days_since
        item["review_interval"] = interval
        due_topics.append(item)

    due_topics.sort(
        key=lambda t: (
            -(t.get("days_since_last_reviewed", 0) - (t.get("review_interval") or 0)),
            not t.get("struggled_last", False),
            t["week"],
        )
    )
    selected = due_topics[:MAX_REVIEW_TOPICS]
    print(f"[spaced_rep] Selected {len(selected)} due review topic(s).")
    return selected


def _build_candidate_plan(state: dict) -> dict:
    student_id = state.get("student_id", "")
    course_id = state.get("course_id", "")
    roadmap = state.get("roadmap") or []
    topic_graph = state.get("topic_graph") or []
    today = _safe_date(state.get("session_date"))

    topic_rows = _load_course_topics(student_id, course_id)
    topic_meta = {row["name"]: row for row in topic_rows}
    graph_lookup = {topic["name"]: topic for topic in topic_graph if topic.get("name")}

    current_week = _find_current_week(roadmap, topic_meta)
    review_topics = _pick_review_topics(topic_rows, today, graph_lookup)
    new_topic = _pick_new_topic(roadmap, current_week, topic_meta, graph_lookup)

    total_estimated_hours = sum(t["estimated_hours"] for t in review_topics)
    if new_topic:
        total_estimated_hours += new_topic["estimated_hours"]

    candidate = {
        "session_date": today.isoformat(),
        "current_week": current_week,
        "new_topic": new_topic,
        "review_topics": review_topics,
        "total_estimated_hours": round(total_estimated_hours, 1),
    }
    print(
        f"[spaced_rep] Built candidate plan — new_topic={bool(new_topic)} review_topics={len(review_topics)}."
    )
    return candidate


def _fallback_plan(state: dict) -> dict:
    roadmap = state.get("roadmap") or []
    topic_graph = state.get("topic_graph") or []
    session_date = _safe_date(state.get("session_date")).isoformat()
    graph_lookup = {topic["name"]: topic for topic in topic_graph if topic.get("name")}

    fallback_topic = None
    fallback_week = 1

    for week in roadmap:
        for topic_name in week.get("topics", []):
            graph_topic = graph_lookup.get(topic_name, {})
            fallback_week = int(week.get("week", 1) or 1)
            fallback_topic = {
                "name": topic_name,
                "week": fallback_week,
                "estimated_hours": float(graph_topic.get("estimated_hours", 1.0)),
                "bloom_level": int(graph_topic.get("bloom_level", 1)),
                "type": graph_topic.get("type", "must_know"),
                "status": "not_started",
                "days_since_last_reviewed": None,
                "review_interval": None,
                "struggled_last": False,
            }
            break
        if fallback_topic:
            break

    total_estimated_hours = fallback_topic["estimated_hours"] if fallback_topic else 0.0
    return {
        "session_date": session_date,
        "current_week": fallback_week,
        "new_topic": fallback_topic,
        "review_topics": [],
        "total_estimated_hours": round(total_estimated_hours, 1),
    }


def spaced_rep_node(state: dict) -> dict:
    if state.get("todays_plan"):
        print("[spaced_rep] todays_plan already present — skipping.")
        return state

    student_id = state.get("student_id")
    course_id = state.get("course_id")
    roadmap = state.get("roadmap")

    if not student_id or not course_id:
        print("[spaced_rep] Missing student_id or course_id — skipping.")
        return state

    if not roadmap:
        print("[spaced_rep] No roadmap in state — skipping.")
        return state

    raw = ""
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if attempt == 1:
                candidate = _build_candidate_plan(state)
                raw = json.dumps(candidate)
            else:
                print(f"[spaced_rep] Retry {attempt} after error: {last_error}")
                response = llm.invoke(_correction_prompt(raw, str(last_error)))
                raw = response.content.strip()
                time.sleep(1)

            todays_plan = _parse_and_validate(raw)
            print(
                f"[spaced_rep] Built today's plan on attempt {attempt} with {len(todays_plan['review_topics'])} review topic(s)."
            )
            return {**state, "todays_plan": todays_plan}

        except Exception as e:
            last_error = e
            continue

    print(f"[spaced_rep] All retries failed. Last error: {last_error}")
    fallback = _fallback_plan(state)
    return {**state, "todays_plan": fallback}
