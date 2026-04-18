import urllib.parse
from datetime import date

import streamlit as st
from dotenv import load_dotenv

from memory.student_registry import get_course, get_student_by_id

load_dotenv()

st.set_page_config(
    page_title="GradeMinds AI",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

if "screen" not in st.session_state:
    st.session_state["screen"] = "welcome"

if "student" not in st.session_state:
    st.session_state["student"] = None

if "active_course" not in st.session_state:
    st.session_state["active_course"] = None



def _render_html_in_iframe(html: str):
    src = "data:text/html;charset=utf-8," + urllib.parse.quote(html)
    st.iframe(src, height=1, width=1)


def _apply_theme():
    """
    Applies dark mode theme (always dark mode now).
    """
    # Always use dark mode
    css = """
    <style>
    .stApp {
        background-color: #0f1419;
        color: #e1e8ed;
    }
    .stSidebar {
        background-color: #1a1a2e;
        color: #e1e8ed;
    }
    .stButton button {
        background-color: #16213e;
        color: #e1e8ed;
        border: 1px solid #0f3460;
    }
    .stButton button:hover {
        background-color: #0f3460;
        color: #ffffff;
    }
    .stTextInput input, .stTextArea textarea, .stSelectbox select {
        background-color: #16213e;
        color: #e1e8ed;
        border: 1px solid #0f3460;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #0f3460;
        box-shadow: 0 0 0 0.2rem rgba(15, 52, 96, 0.25);
    }
    /* Make cursor visible in input fields */
    .stTextInput input {
        caret-color: #e1e8ed;
    }
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
        color: #e1e8ed;
    }
    .stMarkdown p {
        color: #c4c4c4;
    }
    .stAlert {
        background-color: #16213e;
        color: #e1e8ed;
        border: 1px solid #0f3460;
    }
    .stTabs [data-baseweb="tab-list"] {
        background-color: #1a1a2e;
    }
    .stTabs [data-baseweb="tab"] {
        color: #e1e8ed;
    }
    .stProgress > div > div {
        background-color: #0f3460;
    }
    </style>
    """
    st.html(css)


def _set_query_params(student_id=None, screen=None, course_id=None):
    if student_id:
        st.query_params["student_id"] = student_id
    if screen:
        st.query_params["screen"] = screen
    if course_id:
        st.query_params["course_id"] = course_id

    # Persistence Bridge: Sync to LocalStorage using JS
    if student_id:
        _render_html_in_iframe(
            f"""
            <script>
                localStorage.setItem('grademinds_student_id', '{student_id}');
            </script>
            """
        )


def _restore_from_query_params():
    # 1. Try URL parameters first
    student_id = st.query_params.get("student_id")
    screen_param = st.query_params.get("screen")
    course_id = st.query_params.get("course_id")

    if st.session_state["student"] is None and student_id:
        student = get_student_by_id(student_id)
        if student:
            st.session_state["student"] = student
            if screen_param:
                st.session_state["screen"] = screen_param
            if course_id:
                course = get_course(course_id)
                if course and course.get("student_id") == student_id:
                    st.session_state["active_course"] = {
                        "course_id": course_id,
                        "topic": course["topic"],
                    }


_restore_from_query_params()

# Apply theme
_apply_theme()

screen = st.session_state["screen"]

# ── Sidebar (shown only when logged in) ───────────────────────────────────────
if st.session_state["student"]:
    with st.sidebar:
        student = st.session_state["student"]
        active_course = st.session_state.get("active_course") or {}
        current_topic = (
            active_course.get("topic") or student.get("topic") or "No active course"
        )

        st.markdown(f"### 👤 {student['name']}")
        st.caption(f"Topic: {current_topic}")
        st.divider()

        if st.button("Courses", use_container_width=True):
            st.session_state["screen"] = "course_selector"
            _set_query_params(
                student_id=student["student_id"],
                screen="course_selector",
            )
            st.rerun()
        if st.button("Today's Plan", use_container_width=True):
            cache_key = (
                f"todays_plan_{active_course.get('course_id')}_{str(date.today())}"
            )
            st.session_state.pop(cache_key, None)
            st.session_state["screen"] = "today_plan"
            _set_query_params(
                student_id=student["student_id"],
                screen="today_plan",
                course_id=active_course.get("course_id"),
            )
            st.rerun()
        if st.button("My Roadmap", use_container_width=True):
            st.session_state["screen"] = "roadmap_view"
            _set_query_params(
                student_id=student["student_id"],
                screen="roadmap_view",
                course_id=active_course.get("course_id"),
            )
            st.rerun()
        st.divider()
        if st.button("Log out", use_container_width=True):
            st.session_state["student"] = None
            st.session_state["active_course"] = None
            st.session_state["agent_state"] = None
            st.session_state["screen"] = "welcome"
            st.query_params.clear()
            _render_html_in_iframe(
                "<script>localStorage.removeItem('grademinds_student_id');</script>"
            )
            st.rerun()

if screen == "welcome":
    from ui.screens.welcome import render_welcome

    render_welcome()

elif screen == "course_selector":
    from ui.screens.course_selector import render_course_selector

    render_course_selector()

elif screen == "onboarding":
    from agent.graph import app as agent_graph
    from memory.chroma_ops import init_topics_for_course
    from ui.screens.explorer_onboarding import render_explorer_onboarding

    def on_submit(initial_state):
        from agent.state import GradeMindsState
        with st.spinner("Building your personalized roadmap..."):
            final_state = agent_graph.invoke(GradeMindsState(**initial_state))

        # Initialize spaced-rep topic records in Chroma
        init_topics_for_course(
            final_state["student_id"],
            final_state["course_id"],
            final_state.get("topic_graph", []),
            final_state.get("roadmap", []),
        )

        # Persist roadmap state and student context into session
        st.session_state["agent_state"] = final_state
        st.session_state["active_course"] = {
            "course_id": final_state["course_id"],
            "topic": final_state["topic"],
        }
        st.session_state["screen"] = "roadmap_view"
        _set_query_params(
            student_id=final_state["student_id"],
            screen="roadmap_view",
            course_id=final_state["course_id"],
        )
        st.rerun()

    render_explorer_onboarding(on_submit)

elif screen == "roadmap_view":
    from memory.chroma_ops import get_topics_for_course, load_roadmap
    from ui.screens.roadmap_view import render_roadmap_view

    active_course = st.session_state.get("active_course")
    agent_state = st.session_state.get("agent_state")
    course_id = None

    if active_course and isinstance(active_course, dict):
        course_id = active_course.get("course_id")
    elif agent_state and isinstance(agent_state, dict):
        course_id = agent_state.get("course_id")

    if not course_id:
        st.warning("Please select a course first.")
        if st.button("Go to courses"):
            st.session_state["screen"] = "course_selector"
            st.rerun()
    else:
        _set_query_params(
            student_id=st.session_state["student"]["student_id"],
            screen="roadmap_view",
            course_id=course_id,
        )
        roadmap = load_roadmap(course_id) or []
        topic_data = get_topics_for_course(course_id)
        render_roadmap_view(roadmap, topic_data, course_id)

elif screen == "today_plan":
    from agent.nodes.spaced_rep import spaced_rep_node
    from memory.chroma_ops import get_topics_for_course
    from memory.student_registry import get_course
    from ui.screens.today_plan import render_today_plan

    student = st.session_state["student"]
    course = st.session_state.get("active_course") or {}
    course_id = course.get("course_id")
    agent_state = st.session_state.get("agent_state") or {}

    if not course_id:
        st.warning("Please select a course first.")
        if st.button("Go to courses"):
            st.session_state["screen"] = "course_selector"
            st.rerun()
    else:
        if not agent_state or not agent_state.get("roadmap"):
            from memory.chroma_ops import load_roadmap

            roadmap_data = load_roadmap(course_id)
            if roadmap_data:
                agent_state = {
                    "student_id": student["student_id"],
                    "course_id": course_id,
                    "roadmap": roadmap_data,
                    "todays_plan": None,
                }
                st.session_state["agent_state"] = agent_state

        cache_key = f"todays_plan_{course_id}_{str(date.today())}"
        if cache_key not in st.session_state:
            with st.spinner("Preparing your daily briefing and fetching resources..."):
                updated_state = spaced_rep_node(agent_state)
                from agent.nodes.resource_retriever import resource_retriever_node

                updated_state = resource_retriever_node(updated_state)
                st.session_state[cache_key] = updated_state["todays_plan"]
                st.session_state["agent_state"] = updated_state

        todays_plan = st.session_state[cache_key]
        resources = st.session_state.get("agent_state", {}).get("resources", [])
        topic_data = get_topics_for_course(course_id)
        course_info = get_course(course_id)

        render_today_plan(todays_plan, topic_data, course_info, course_id, resources)

elif screen == "academic_onboarding":
    from ui.screens.academic_onboarding import render_academic_onboarding

    def on_academic_submit(initial_state):
        pass

    render_academic_onboarding(on_academic_submit)

elif screen == "diagnosis_view":
    from agent.graph import app as agent_graph
    from memory.chroma_ops import init_topics_for_course
    from memory.student_registry import create_course
    from ui.screens.diagnosis_view import render_diagnosis_view

    def on_confirm(diagnosis):
        from agent.state import GradeMindsState
        student = st.session_state["student"]
        topic = st.session_state["pending_topic"]
        syllabus_text = st.session_state["pending_syllabus"]
        goal = st.session_state["pending_goal"]
        hours = st.session_state["pending_hours"]
        features = st.session_state["pending_features"]
        ml_output = st.session_state["pending_ml_output"]

        sa = {
            "known": "Currently enrolled in this course",
            "hours_per_week": hours,
            "goal": goal,
        }

        course = create_course(
            student_id=student["student_id"],
            topic=topic,
            mode="academic",
            self_assessment=sa,
        )

        initial_state = {
            "mode": "academic",
            "topic": topic,
            "syllabus_text": syllabus_text,
            "self_assessment": sa,
            "academic_features": features,
            "ml_output": ml_output,
            "predicted_score": ml_output["predicted_score"],
            "pass_fail": ml_output["pass_fail"],
            "diagnosis": diagnosis, 
            "topic_graph": None,
            "roadmap": None,
            "todays_plan": None,
            "resources": None,
            "student_id": student["student_id"],
            "course_id": course["course_id"],
            "session_date": str(date.today()),
            "chroma_initialized": False,
        }

        with st.spinner("Building your academic roadmap..."):
            final_state = agent_graph.invoke(GradeMindsState(**initial_state))

        init_topics_for_course(
            student_id=student["student_id"],
            course_id=course["course_id"],
            topic_graph=final_state.get("topic_graph", []),
            roadmap=final_state.get("roadmap", []),
        )

        for key in [
            "pending_ml_output",
            "pending_topic",
            "pending_syllabus",
            "pending_goal",
            "pending_hours",
            "pending_features",
            "diagnosis_result",
        ]:
            st.session_state.pop(key, None)

        st.session_state["agent_state"] = final_state
        st.session_state["active_course"] = {
            "course_id": course["course_id"],
            "topic": topic,
        }
        st.session_state["screen"] = "roadmap_view"
        st.rerun()

    render_diagnosis_view(on_confirm)
