import json
import os
import time

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from pydantic import BaseModel, validator

load_dotenv()

llm = ChatGroq(
    model="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.2,
    max_retries=2,
)

MAX_RETRIES = 2


# Output schema
class WeakArea(BaseModel):
    factor: str  # Feature label
    impact: str  # "high" | "medium" | "low"
    student_value: str  # e.g. "62%"
    average_value: str  # e.g. "77.8%"
    score_lost: str  # e.g. "~12 points"
    action: str  # one specific actionable recommendation


class DiagnosisOutput(BaseModel):
    weak_areas: list[WeakArea]
    summary: str  # one plain-English sentence
    recommendations: list[str]  # 2-3 top actions, ordered by impact
    predicted_grade: str  # letter grade interpretation of score

    @validator("weak_areas")
    def at_least_one(cls, v):
        if not v:
            raise ValueError("Must have at least one weak area")
        return v

    @validator("impact", each_item=False, pre=False, always=False, check_fields=False)
    def valid_impacts(cls, v):
        return v


def _build_prompt(ml_output: dict, syllabus_topic: str) -> str:
    score = ml_output["predicted_score"]
    pass_fail = ml_output["pass_fail"]
    pass_prob = ml_output["pass_probability"]
    feature_gaps = ml_output["feature_gaps"]
    features = ml_output["input_features"]

    # Format feature gaps for the prompt — sorted by impact already
    gaps_text = ""
    for g in feature_gaps:
        direction = "BELOW" if g["is_below_avg"] else "above"
        if g["feature"] == "Extracurricular_Activities_Yes":
            val_str = "Yes" if g["student_value"] == 1 else "No"
            avg_str = "~50% of students do extracurriculars"
            gaps_text += f"\n  - {g['label']}: {val_str} | {avg_str} | score impact: {g['score_impact']:+.1f} pts"
        else:
            gaps_text += (
                f"\n  - {g['label']}: {g['student_value']} vs avg {g['average_value']} "
                f"({direction} average by {abs(g['gap_pct'] or 0):.1f}%) "
                f"| score impact: {g['score_impact']:+.1f} pts "
                f"| classifier importance: {g['importance'] * 100:.1f}%"
            )

    letter_grade = _score_to_grade(score)

    return f"""You are an academic performance analyst for an AI study coach.
        A student's data has been analysed by ML models. Your job is to explain the
        results clearly and produce actionable guidance. Output ONLY valid JSON.

        STUDENT RESULTS:
        - Predicted exam score: {score}/100 (approx grade: {letter_grade})
        - Pass/Fail prediction: {pass_fail} (pass probability: {pass_prob * 100:.1f}%)
        - Subject/course: {syllabus_topic or "general academics"}

        FEATURE GAP ANALYSIS (sorted by score impact, worst first):
        {gaps_text}

        CONTEXT:
        - Dataset averages represent a typical student in this course.
        - Score impact = how many points this gap costs the student.
        - Classifier importance = how heavily this feature affects pass/fail.
        - Extracurricular has only 1.9% classifier importance — deprioritise it.

        Respond with this exact JSON structure:
        {{
          "weak_areas": [
            {{
              "factor":        "human-readable feature name",
              "impact":        "high | medium | low",
              "student_value": "student's actual value with unit",
              "average_value": "dataset average with unit",
              "score_lost":    "approx points lost e.g. ~8 points",
              "action":        "one specific actionable step"
            }}
          ],
          "summary": "One plain-English sentence explaining the overall prediction",
          "recommendations": [
            "Most impactful action",
            "Second most impactful action",
            "Third action if relevant"
          ],
          "predicted_grade": "e.g. C+ or D — interpret the score as a letter grade"
        }}

        Rules:
        1. Only include features where impact is meaningful (skip extracurricular 
           unless student_value=0 AND all other features are strong).
        2. impact = "high" if importance > 0.3, "medium" if > 0.1, "low" otherwise.
        3. Actions must be specific — not "study more" but 
           "increase study hours from X to Y per week over the next 3 weeks".
        4. summary must mention the single biggest factor causing the prediction.
        5. Order weak_areas by impact descending (high first).
        6. Maximum 3 weak areas.
    """


def _correction_prompt(bad_json: str, error_msg: str) -> str:
    return f"""Your JSON caused this error: {error_msg}
        Fix it and return ONLY the corrected JSON. No explanation.
        Broken output:
        {bad_json}
    """


def _score_to_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _parse_and_validate(raw: str) -> dict:
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else parts[0]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())
    output = DiagnosisOutput(**data)
    return output.dict()


# Main Diagnostician Node
def diagnostician_node(state: dict) -> dict:
    """
    Node 1 — Academic Mode only.
    Reads ml_output from state, produces structured diagnosis.
    """
    ml_output = state.get("ml_output")
    if not ml_output:
        print("[diagnostician] No ml_output in state — skipping.")
        return state

    topic = state.get("topic", "")
    raw = ""
    last_error = None
    prompt = _build_prompt(ml_output, topic)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if attempt == 1:
                response = llm.invoke(prompt)
            else:
                print(f"[diagnostician] Retry {attempt} after: {last_error}")
                response = llm.invoke(_correction_prompt(raw, str(last_error)))
                time.sleep(1)

            raw = response.content.strip()
            diagnosis = _parse_and_validate(raw)

            print(
                f"[diagnostician] Diagnosis complete — {len(diagnosis['weak_areas'])} weak areas found."
            )
            return {**state, "diagnosis": diagnosis}

        except Exception as e:
            last_error = e
            continue

    print(
        f"[diagnostician] All retries failed ({last_error}) — using fallback diagnosis."
    )
    gaps = ml_output.get("feature_gaps", [])
    score = ml_output.get("predicted_score", 0)
    pass_fail = ml_output.get("pass_fail", "FAIL")
    fallback_diagnosis = {
        "weak_areas": [
            {
                "factor": g["label"],
                "impact": "high" if g["importance"] > 0.3 else "medium",
                "student_value": str(g["student_value"]),
                "average_value": str(g["average_value"]),
                "score_lost": f"~{abs(g['score_impact']):.0f} points",
                "action": f"Improve {g['label']} from {g['student_value']} towards {g['average_value']}",
            }
            for g in gaps
            if g["is_below_avg"]
        ][:3],
        "summary": f"Predicted score of {score}/100 ({pass_fail}) driven by below-average performance metrics.",
        "recommendations": [
            f"Focus on improving {g['label']}" for g in gaps[:2] if g["is_below_avg"]
        ],
        "predicted_grade": _score_to_grade(score),
    }
    return {**state, "diagnosis": fallback_diagnosis}
