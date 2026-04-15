import hashlib
import json
import uuid
from datetime import datetime

import chromadb

client = chromadb.PersistentClient(path="./grademinds_db")
registry = client.get_or_create_collection("student_registry")
courses = client.get_or_create_collection("student_courses")


# Helper -> Hashing Password
def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def validate_password_strength(password: str):
    """
    Standard password validation:
    - Minimum 6 characters
    - Must contain at least one number
    """
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters long.")
    if not any(char.isdigit() for char in password):
        raise ValueError("Password must contain at least one number.")


# Student identity - Registration
def register_student(name: str, password: str) -> dict:
    """
    Create a new student identity (no course yet).
    Raises ValueError if name is already taken or password is weak.
    """
    validate_password_strength(password)
    
    existing = registry.get(where={"name": name})
    if existing["ids"]:
        raise ValueError(f"Username '{name}' is already taken. Choose a different one.")

    student_id = str(uuid.uuid4())
    registry.add(
        ids=[student_id],
        documents=[name],
        metadatas=[
            {
                "name": name,
                "password_hash": _hash_password(password),
                "created_at": datetime.now().isoformat(),
                "last_active": datetime.now().isoformat(),
            }
        ],
    )
    print(f"[registry] Registered new student '{name}' → {student_id}")
    return {"student_id": student_id, "name": name}


def login_student(name: str, password: str) -> dict | None:
    """Verify username + password. Returns student record or None."""
    results = registry.get(where={"name": name})
    if not results["ids"]:
        return None

    meta = results["metadatas"][0]
    # Handle legacy 'pin_hash' for existing users
    stored_hash = meta.get("password_hash") or meta.get("pin_hash")
    if stored_hash != _hash_password(password):
        return None

    student_id = results["ids"][0]
    registry.update(
        ids=[student_id],
        metadatas=[{**meta, "last_active": datetime.now().isoformat()}],
    )
    print(f"[registry] Login successful for '{name}' → {student_id}")
    return {"student_id": student_id, "name": meta["name"]}


def record_session_activity(student_id: str):
    """Simple activity tracker for persistence."""
    results = registry.get(ids=[student_id])
    if results["ids"]:
        meta = results["metadatas"][0]
        registry.update(
            ids=[student_id],
            metadatas=[{
                **meta,
                "last_active": datetime.now().isoformat()
            }]
        )

# Course Management
def create_course(
    student_id: str,
    topic: str,
    mode: str,
    self_assessment: dict,
) -> dict:
    """
    Create a new course for a student.
    Each course gets its own course_id used to namespace all Chroma data.
    Returns the course record.
    """
    course_id = str(uuid.uuid4())
    courses.add(
        ids=[course_id],
        documents=[topic],
        metadatas=[
            {
                "student_id": student_id,
                "topic": topic,
                "mode": mode,
                "self_assessment": json.dumps(self_assessment),
                "created_at": datetime.now().isoformat(),
                "last_accessed": datetime.now().isoformat(),
                "roadmap_ready": False,
                "total_topics": 0,
                "done_topics": 0,
            }
        ],
    )
    print(f"[registry] Created course '{topic}' → {course_id} for student {student_id}")
    return {
        "course_id": course_id,
        "topic": topic,
        "mode": mode,
        "self_assessment": self_assessment,
        "roadmap_ready": False,
    }


def get_student_courses(student_id: str) -> list[dict]:
    """Return all courses belonging to a student, newest first."""
    results = courses.get(where={"student_id": student_id})
    if not results["ids"]:
        return []

    course_list = []
    # Access the topics collection for accurate counts
    topics_col = client.get_or_create_collection("topics")

    for cid, doc, meta in zip(
        results["ids"], results["documents"], results["metadatas"]
    ):
        # Fail-safe: Fetch the actual "done" count from topics collection
        try:
            done_results = topics_col.get(where={"$and": [{"course_id": cid}, {"status": "done"}]})
            actual_done = len(done_results["ids"])
        except Exception as e:
            actual_done = meta.get("done_topics", 0)

        course_list.append(
            {
                "course_id": cid,
                "topic": doc,
                "mode": meta.get("mode", "explorer"),
                "roadmap_ready": meta.get("roadmap_ready", False),
                "created_at": meta.get("created_at", ""),
                "last_accessed": meta.get("last_accessed", ""),
                "total_topics": meta.get("total_topics", 0),
                "done_topics": actual_done, # Use refreshed count
                "self_assessment": json.loads(meta.get("self_assessment", "{}")),
            }
        )

    # Sort newest first
    course_list.sort(key=lambda c: c["created_at"], reverse=True)
    return course_list


def get_course(course_id: str) -> dict | None:
    """Fetch a single course record by course_id."""
    results = courses.get(ids=[course_id])
    if not results["ids"]:
        return None
    meta = results["metadatas"][0]
    return {
        "course_id": course_id,
        "student_id": meta.get("student_id"),
        "topic": results["documents"][0],
        "mode": meta.get("mode", "explorer"),
        "roadmap_ready": meta.get("roadmap_ready", False),
        "self_assessment": json.loads(meta.get("self_assessment", "{}")),
        "total_topics": meta.get("total_topics", 0),
        "done_topics": meta.get("done_topics", 0),
    }


def get_student_by_id(student_id: str) -> dict | None:
    """Fetch a student record by student_id."""
    results = registry.get(ids=[student_id])
    if not results["ids"]:
        return None
    meta = results["metadatas"][0]
    return {"student_id": student_id, "name": meta.get("name")}


def mark_roadmap_ready(student_id: str, course_id: str, total_topics: int):
    """Called after Node 3 completes for this course."""
    results = courses.get(ids=[course_id])
    if results["ids"]:
        meta = results["metadatas"][0]
        courses.update(
            ids=[course_id],
            metadatas=[
                {
                    **meta,
                    "roadmap_ready": True,
                    "total_topics": total_topics,
                }
            ],
        )
        print(f"[registry] Course {course_id} marked ready ({total_topics} topics).")


def update_course_progress(course_id: str, done_topics: int):
    """Update done_topics count and last_accessed timestamp."""
    results = courses.get(ids=[course_id])
    if results["ids"]:
        meta = results["metadatas"][0]
        courses.update(
            ids=[course_id],
            metadatas=[
                {
                    **meta,
                    "done_topics": done_topics,
                    "last_accessed": datetime.now().isoformat(),
                }
            ],
        )


def delete_course(course_id: str):
    """Remove a course record. Chroma topic data is cleaned up separately."""
    courses.delete(ids=[course_id])
    print(f"[registry] Deleted course {course_id}.")


def get_all_students() -> list[dict]:
    """Admin/debug — list all students."""
    results = registry.get()
    return [
        {"student_id": sid, **meta}
        for sid, meta in zip(results["ids"], results["metadatas"])
    ]
