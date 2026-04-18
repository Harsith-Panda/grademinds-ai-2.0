import streamlit as st

from memory.chroma_ops import delete_course_data
from memory.student_registry import delete_course, get_student_courses


def render_course_selector():
    student = st.session_state["student"]
    courses = get_student_courses(student["student_id"])

    st.markdown(f"## Welcome back, {student['name']}")
    st.caption("Pick a course to continue, or start a new one.")
    st.divider()

    if courses:
        st.markdown("### Your courses")
        for course in courses:
            total = course["total_topics"]
            done = course["done_topics"]
            pct = int((done / total * 100) if total else 0)

            with st.container():
                col1, col2, col3 = st.columns([5, 2, 1])

                with col1:
                    mode_badge = (
                        "Academic" if course["mode"] == "academic" else "Explorer"
                    )
                    st.markdown(f"**{course['topic']}** &nbsp; `{mode_badge}`")
                    if total:
                        st.progress(
                            pct / 100, text=f"{done}/{total} topics complete ({pct}%)"
                        )
                    else:
                        st.caption("Roadmap building...")
                    st.caption(f"Last accessed: {course['last_accessed'][:10]}")

                with col2:
                    label = "Continue" if course["roadmap_ready"] else "Resume setup"
                    if st.button(
                        label,
                        key=f"open_{course['course_id']}",
                        type="primary",
                        use_container_width=True,
                    ):
                        st.session_state["active_course"] = course
                        from memory.chroma_ops import (
                            get_topics_for_course,
                            load_roadmap,
                        )

                        roadmap = load_roadmap(course["course_id"])
                        topic_data = get_topics_for_course(course["course_id"])

                        # Rebuild the minimal agent state for this course
                        from datetime import date

                        st.session_state["agent_state"] = {
                            "mode": course["mode"],
                            "topic": course["topic"],
                            "syllabus_text": "",
                            "self_assessment": course["self_assessment"],
                            "academic_features": {},
                            "predicted_score": None,
                            "pass_fail": None,
                            "diagnosis": {},
                            "topic_graph": [
                                {
                                    "name": t["name"],
                                    "bloom_level": t.get("bloom_level", 1),
                                    "estimated_hours": 1,
                                    "prerequisites": [],
                                    "type": t.get("topic_type", "must_know"),
                                }
                                for t in topic_data
                            ],
                            "roadmap": roadmap,
                            "todays_plan": None,
                            "resources": None,
                            "student_id": student["student_id"],
                            "course_id": course["course_id"],
                            "session_date": str(date.today()),
                            "chroma_initialized": True,
                        }
                        st.session_state["screen"] = "today_plan"
                        set_qp = getattr(st, "experimental_set_query_params", None)
                        if set_qp is None:
                            set_qp = getattr(st, "set_query_params", None)
                        if set_qp:
                            set_qp(
                                student_id=student["student_id"],
                                screen="today_plan",
                                course_id=course["course_id"],
                            )
                        st.rerun()

                with col3:
                    if st.button(
                        "Delete", key=f"del_{course['course_id']}", help="Delete this course"
                    ):
                        delete_course(course["course_id"])
                        delete_course_data(course["course_id"])
                        st.rerun()

    st.divider()
    st.markdown("### Start a new course")

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "Explorer — learn any topic", use_container_width=True, type="primary"
        ):
            st.session_state["screen"] = "onboarding"
            st.rerun()
    with col2:
        if st.button(
            "Academic — study from syllabus/grades", use_container_width=True
        ):
            st.session_state["screen"] = "academic_onboarding"
            st.rerun()
