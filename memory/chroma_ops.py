import json
from datetime import datetime

import chromadb

client = chromadb.PersistentClient(path="./grademinds_db")
topics = client.get_or_create_collection("topics")
roadmaps = client.get_or_create_collection("roadmaps")


# Roadmap Persistence (Save & Load Roadmaps)
def save_roadmap(student_id: str, course_id: str, roadmap: list[dict]):
    """Persist roadmap keyed by course_id (not student_id)."""
    roadmap_json = json.dumps(roadmap)
    existing = roadmaps.get(ids=[course_id])
    payload = {
        "student_id": student_id,
        "course_id": course_id,
        "saved_at": datetime.now().isoformat(),
        "week_count": len(roadmap),
    }
    if existing["ids"]:
        roadmaps.update(ids=[course_id], documents=[roadmap_json], metadatas=[payload])
    else:
        roadmaps.add(ids=[course_id], documents=[roadmap_json], metadatas=[payload])
    print(f"[chroma_ops] Roadmap saved — course {course_id} ({len(roadmap)} weeks).")


def load_roadmap(course_id: str) -> list[dict] | None:
    """Load a roadmap by course_id. Returns None if not found."""
    try:
        result = roadmaps.get(ids=[course_id])
        if result["ids"]:
            return json.loads(result["documents"][0])
    except Exception as e:
        print(f"[chroma_ops] load_roadmap failed: {e}")
    return None


# Register Topics
def init_topics_for_course(
    student_id: str,
    course_id: str,
    topic_graph: list[dict],
    roadmap: list[dict],
):
    """
    Initialize spaced-rep records for every topic in a course.
    Skips topics already stored (safe to call multiple times).
    Attaches the week number from the roadmap to each topic record.
    """
    week_lookup: dict[str, int] = {}
    for week in roadmap:
        for t in week["topics"]:
            week_lookup[t] = week["week"]

    # Find already-stored topic names for this course
    existing = topics.get(where={"course_id": course_id})
    existing_names = set(existing["documents"]) if existing["ids"] else set()

    new_ids, new_docs, new_metas = [], [], []

    for topic in topic_graph:
        name = topic["name"]
        if name in existing_names:
            continue
        new_ids.append(f"{course_id}_{name}")
        new_docs.append(name)
        new_metas.append(
            {
                "student_id": student_id,
                "course_id": course_id,
                "week": week_lookup.get(name, 0),
                "bloom_level": topic.get("bloom_level", 1),
                "status": "not_started",
                "last_reviewed": "",
                "review_interval": 1,
                "times_reviewed": 0,
                "struggled_last": False,
                "topic_type": topic.get("type", "must_know"),
            }
        )

    if new_ids:
        topics.add(ids=new_ids, documents=new_docs, metadatas=new_metas)
        print(f"[chroma_ops] Initialized {len(new_ids)} topics for course {course_id}.")
    else:
        print(f"[chroma_ops] Topics already initialized for course {course_id}.")


def get_topics_for_course(course_id: str) -> list[dict]:
    """Fetch all topic records for a specific course."""
    result = topics.get(where={"course_id": course_id})
    return (
        [
            {"name": doc, **meta}
            for doc, meta in zip(result["documents"], result["metadatas"])
        ]
        if result["ids"]
        else []
    )


def update_topic_after_session(
    course_id: str,
    topic_name: str,
    struggled: bool,
):
    """Update a topic's spaced-rep state after review."""
    doc_id = f"{course_id}_{topic_name}"
    result = topics.get(ids=[doc_id])
    if not result["ids"]:
        print(f"[chroma_ops] Topic not found: {doc_id}")
        return

    meta = result["metadatas"][0]
    interval = int(meta.get("review_interval", 1))
    new_interval = 1 if struggled else round(interval * 2.5)

    topics.update(
        ids=[doc_id],
        metadatas=[
            {
                **meta,
                "status": "done",
                "last_reviewed": datetime.now().isoformat(),
                "review_interval": new_interval,
                "times_reviewed": int(meta.get("times_reviewed", 0)) + 1,
                "struggled_last": struggled,
            }
        ],
    )
    print(f"[chroma_ops] '{topic_name}' updated — interval now {new_interval}d. Syncing registry...")
    
    # ──────────────────────────────────────────────────────────────────────────
    # CRITICAL FIX: Update the summary metadata in student_courses collection
    # ──────────────────────────────────────────────────────────────────────────
    try:
        # 1. Count ALL topics currently marked as "done" for this course
        done_count_results = topics.get(
            where={"$and": [{"course_id": course_id}, {"status": "done"}]}
        )
        done_count = len(done_count_results["ids"])

        # 2. Update the student_courses collection record
        course_registry = client.get_or_create_collection("student_courses")
        course_meta_results = course_registry.get(ids=[course_id])
        
        if course_meta_results["ids"]:
            current_meta = course_meta_results["metadatas"][0]
            course_registry.update(
                ids=[course_id],
                metadatas=[{
                    **current_meta,
                    "done_topics": done_count,
                    "last_accessed": datetime.now().isoformat()
                }]
            )
            print(f"[chroma_ops] Registry progress updated: {done_count} topics done.")
        else:
            print(f"[chroma_ops] WARNING: Course {course_id} not found in registry during sync.")
    except Exception as e:
        print(f"[chroma_ops] ERROR updating registry summary: {e}")


def delete_course_data(course_id: str):
    """Clean up all Chroma data for a deleted course."""
    # Delete roadmap
    try:
        roadmaps.delete(ids=[course_id])
    except Exception:
        pass

    # Delete all topic records
    course_topics = topics.get(where={"course_id": course_id})
    if course_topics["ids"]:
        topics.delete(ids=course_topics["ids"])
    print(f"[chroma_ops] Deleted all data for course {course_id}.")
