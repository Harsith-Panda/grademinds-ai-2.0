from typing import List, Optional, TypedDict


class GradeMindsState(TypedDict):
    mode: str
    topic: str
    syllabus_text: str
    self_assessment: dict
    academic_features: dict
    predicted_score: Optional[float]
    pass_fail: Optional[str]
    diagnosis: Optional[dict]
    topic_graph: Optional[List]
    roadmap: Optional[List]
    todays_plan: Optional[dict]
    resources: Optional[List]
    student_id: str
    course_id: str  # ← NEW: namespaces all Chroma data
    session_date: str
    chroma_initialized: bool
    ml_output: Optional[dict]
