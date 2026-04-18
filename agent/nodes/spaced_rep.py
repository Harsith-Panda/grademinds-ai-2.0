import os
from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, field_validator

from memory.chroma_ops import get_topics_for_course

class TaskTopic(BaseModel):
    """Internal validation for topic metadata from Chroma."""
    name: str
    week: int
    bloom_level: int
    status: str
    last_reviewed: str
    review_interval: int
    struggled_last: bool
    topic_type: str

class TodaysPlanSchema(BaseModel):
    """Strict schema for the todays_plan state field."""
    new_topic: Optional[str]
    review_topics: List[str]
    current_week: int
    week_focus: str
    session_date: str
    all_done_today: bool

    @field_validator("current_week")
    @classmethod
    def week_positive(cls, v):
        if v < 1:
            raise ValueError("current_week must be >= 1")
        return v

def _get_days_since(last_reviewed_iso: str) -> int:
    if not last_reviewed_iso:
        return 999  # Long ago
    try:
        last_date = datetime.fromisoformat(last_reviewed_iso).date()
        return (date.today() - last_date).days
    except:
        return 999

def spaced_rep_node(state: dict) -> dict:
    """
    Node 4: Spaced Repetition Scheduler.
    Pure logic — no LLM calls.
    Determines today's new topic and review queue based on ChromaDB state.
    """
    print("[spaced_rep] Starting scheduler logic...")
    
    student_id = state.get("student_id")
    course_id = state.get("course_id")
    roadmap = state.get("roadmap") or []
    
    # Safe Fallback
    fallback_plan = {
        "new_topic": None,
        "review_topics": [],
        "current_week": 1,
        "week_focus": "Stay curious!",
        "session_date": str(date.today()),
        "all_done_today": True
    }

    if not course_id:
        print("[spaced_rep] No course_id found. Returning fallback.")
        return {**state, "todays_plan": fallback_plan}

    try:
        # 1. Fetch all topics for this course from Chroma
        topic_records = get_topics_for_course(course_id)
        if not topic_records:
            print(f"[spaced_rep] No topics found in Chroma for course {course_id}. Returning fallback.")
            return {**state, "todays_plan": fallback_plan}

        # 2. Determine Current Week
        # The lowest week number that still has at least one topic status != "done"
        active_weeks = []
        for week_data in roadmap:
            week_num = week_data.get("week", 1)
            week_topics = week_data.get("topics", [])
            
            # Check if any topic in this week is not done
            week_is_done = True
            for t_name in week_topics:
                # Find the record for this topic
                record = next((r for r in topic_records if r["name"] == t_name), None)
                if record and record.get("status") != "done":
                    week_is_done = False
                    break
            
            if not week_is_done:
                active_weeks.append(week_num)
        
        current_week = min(active_weeks) if active_weeks else (roadmap[-1].get("week", 1) if roadmap else 1)
        
        # Get week focus
        week_info = next((w for w in roadmap if w.get("week") == current_week), {})
        week_focus = week_info.get("focus", "Continuing your journey.")

        # 3. Identify Review Topics (Due Today)
        review_topics = []
        for topic in topic_records:
            if topic.get("status") == "done":
                last_reviewed = topic.get("last_reviewed", "")
                interval = int(topic.get("review_interval", 1))
                
                if last_reviewed:
                    days_since = _get_days_since(last_reviewed)
                    if days_since >= interval:
                        review_topics.append(topic["name"])
        
        # 4. Identify New Topic
        # Pick the first "not_started" topic from the current week,
        # ordered by bloom_level ascending.
        current_week_topics = week_info.get("topics", [])
        not_started_cadidates = []
        
        for t_name in current_week_topics:
            record = next((r for r in topic_records if r["name"] == t_name), None)
            if record and record.get("status") == "not_started":
                not_started_cadidates.append(record)
        
        # Sort by bloom_level ascending
        not_started_cadidates.sort(key=lambda x: int(x.get("bloom_level", 1)))
        
        new_topic = not_started_cadidates[0]["name"] if not_started_cadidates else None
        
        # 5. Build Result
        result = {
            "new_topic": new_topic,
            "review_topics": review_topics[:3], # Cap reviews to 3 per day
            "current_week": current_week,
            "week_focus": week_focus,
            "session_date": str(date.today()),
            "all_done_today": (new_topic is None and not review_topics)
        }
        
        # 6. Validate with Pydantic
        validated_plan = TodaysPlanSchema(**result)
        
        print(f"[spaced_rep] Plan built for week {current_week}. New: {new_topic}, Reviews: {len(review_topics)}")
        return {**state, "todays_plan": validated_plan.dict()}

    except Exception as e:
        print(f"[spaced_rep] ERROR in scheduler: {e}")
        return {**state, "todays_plan": fallback_plan}
