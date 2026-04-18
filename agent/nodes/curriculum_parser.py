import json
import os
import time

import fitz
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from pydantic import BaseModel, field_validator

load_dotenv()

llm = ChatGroq(
    model="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.3,
    max_retries=2,
)

MAX_SYLLABUS_CHARS = 3000
MAX_RETRIES = 2


# Output Schema -> Validation for LLM output (What our system expects)
class TopicNode(BaseModel):
    name: str
    estimated_hours: float
    bloom_level: int
    prerequisites: list[str]
    type: str

    @field_validator("bloom_level")
    @classmethod
    def bloom_in_range(cls, v):
        if not 1 <= v <= 6:
            raise ValueError(f"bloom_level must be 1–6, got {v}")
        return v

    @field_validator("type")
    @classmethod
    def valid_type(cls, v):
        v = v.lower().replace("-", "_").replace(" ", "_")
        if v not in ("must_know", "enrichment"):
            return "must_know"  # safe default
        return v

    @field_validator("estimated_hours")
    @classmethod
    def positive_hours(cls, v):
        return max(0.5, float(v))


# Extract syllabus from PDF
def extract_syllabus_text(pdf_bytes: bytes) -> str:
    """Extract plain text from a PDF uploaded as raw bytes."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        doc.close()

        # Truncate (Constraint due to groq's limit)
        return text[:MAX_SYLLABUS_CHARS].strip()

    except Exception as e:
        print(f"[curriculum_parser] PDF extraction failed: {e}")
        return ""


# Building Prompt
def _build_prompt(
    topic: str,
    known: str,
    hours: int,
    goal: str,
    diagnosis_context: str,
    syllabus_context: str,
) -> str:
    # Handling if user has provided syllabus use it, else give a free roadmap on topic.
    if syllabus_context:
        source_block = f"""
            The student uploaded their course syllabus. Use it as the primary source of topics.
            --- SYLLABUS START ---
            {syllabus_context}
            --- SYLLABUS END ---
            Extract the real topics from this syllabus and supplement with any important
            prerequisites not explicitly listed but needed to understand the course.
        """
    else:
        source_block = f"""
            Generate a learning roadmap for the topic: "{topic}"
            Use your knowledge of this subject to define the ideal learning progression.
        """

    return f"""You are an expert curriculum designer. Output ONLY valid JSON. No preamble, no explanation.

        {source_block}

        Student context:
        - Already knows: "{known}"
        - Available hours per week: {hours}
        - End goal: "{goal}"{diagnosis_context}

        Return a JSON array of topic objects only:
        [{{
          "name": "topic name (concise, specific)",
          "estimated_hours": 2.0,
          "bloom_level": 2,
          "prerequisites": ["exact name of prerequisite topic"],
          "type": "must_know"
        }}]

        Rules:
        1. Order topics so prerequisites always appear before dependents.
        2. bloom_level: 1=Remember, 2=Understand, 3=Apply, 4=Analyze, 5=Evaluate, 6=Create
        3. type must be exactly "must_know" or "enrichment" — nothing else.
        4. estimated_hours must be a positive number (0.5 minimum).
        5. prerequisites must reference exact topic names from this same list.
        6. Maximum 14 topics. Skip topics the student already knows.
        7. Scale total hours to realistically fit within {hours} hours per week.
    """


def _correction_prompt(bad_json: str, error_msg: str) -> str:
    return f"""The JSON you returned caused this error: {error_msg}

        Fix the JSON and return ONLY the corrected JSON array. No explanation.
        Original (broken) output:
        {bad_json}
    """


# Parser + Validator
def _parse_and_validate(raw: str) -> list[dict]:
    """Strip markdown fences, parse JSON, validate each topic node."""
    # Strip ```json ... ``` fences
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else parts[0]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw.strip())

    if not isinstance(data, list):
        raise ValueError("Expected a JSON array at the top level")

    validated = []
    for i, item in enumerate(data):
        try:
            node = TopicNode(**item)
            validated.append(node.dict())
        except Exception as e:
            print(f"[curriculum_parser] Skipping malformed topic #{i}: {e}")
            continue

    if not validated:
        raise ValueError("No valid topic nodes found after validation")

    return validated


# Main Curriculum Parser Node
def curriculum_parser_node(state: dict) -> dict:
    if state.get("topic_graph"):
        print(
            f"[curriculum_parser] Course {state.get('course_id')} already has topic_graph — skipping."
        )
        return state

    topic = state.get("topic", "")
    sa = state.get("self_assessment", {})
    known = sa.get("known", "nothing yet")
    hours = sa.get("hours_per_week", 5)
    goal = sa.get("goal", "understand the topic")

    # Diagnosis context (Academic Mode only, empty in Explorer Mode)
    diagnosis = state.get("diagnosis", {})
    diagnosis_context = ""
    if diagnosis:
        weak = diagnosis.get("weak_areas", [])
        if weak:
            factors = ", ".join(w["factor"] for w in weak)
            diagnosis_context = f"\n- Prioritize these weak areas: {factors}"

    # Syllabus text (set upstream if student uploaded a PDF)
    syllabus_context = state.get("syllabus_text", "")

    prompt = _build_prompt(
        topic, known, hours, goal, diagnosis_context, syllabus_context
    )
    raw = ""
    last_error = None

    # Retry loop
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if attempt == 1:
                response = llm.invoke(prompt)
            else:
                # Send correction prompt with the previous bad output
                print(f"[curriculum_parser] Retry {attempt} after error: {last_error}")
                response = llm.invoke(_correction_prompt(raw, str(last_error)))
                time.sleep(1)

            raw = response.content.strip()
            topic_graph = _parse_and_validate(raw)
            print(
                f"[curriculum_parser] Parsed {len(topic_graph)} topics on attempt {attempt}"
            )
            return {**state, "topic_graph": topic_graph}

        except Exception as e:
            last_error = e
            continue

    # retries exhausted — return a safe fallback
    print(f"[curriculum_parser] All retries failed. Last error: {last_error}")
    fallback = [
        {
            "name": topic or "Introduction",
            "estimated_hours": 2.0,
            "bloom_level": 1,
            "prerequisites": [],
            "type": "must_know",
        }
    ]
    return {**state, "topic_graph": fallback}
