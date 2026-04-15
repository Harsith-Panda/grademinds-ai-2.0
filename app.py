import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="GradeMinds AI",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Screen routing ─────────────────────────────────────────────────────────────
if "screen" not in st.session_state:
    st.session_state["screen"] = "welcome"

if "student" not in st.session_state:
    st.session_state["student"] = None

if "active_course" not in st.session_state:
    st.session_state["active_course"] = None

screen = st.session_state["screen"]

# ── Sidebar (shown only when logged in) ───────────────────────────────────────
if st.session_state["student"]:
    with st.sidebar:
        student = st.session_state["student"]
        active_course = st.session_state.get("active_course") or {}
        current_topic = active_course.get("topic") or student.get("topic") or "No active course"

        st.markdown(f"### 👤 {student['name']}")
        st.caption(f"Topic: {current_topic}")
        st.divider()
        if st.button("📅 Today's Plan", use_container_width=True):
            st.session_state["screen"] = "today_plan"
            st.rerun()
        if st.button("🗺️ My Roadmap", use_container_width=True):
            st.session_state["screen"] = "roadmap_view"
            st.rerun()
        st.divider()
        if st.button("🚪 Log out", use_container_width=True):
            st.session_state["student"] = None
            st.session_state["active_course"] = None
            st.session_state["agent_state"] = None
            st.session_state["screen"] = "welcome"
            st.rerun()

# ── Screen dispatch ────────────────────────────────────────────────────────────
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
        with st.spinner("Building your personalized roadmap..."):
            final_state = agent_graph.invoke(initial_state)

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
        roadmap = load_roadmap(course_id)
        topic_data = get_topics_for_course(course_id)
        render_roadmap_view(roadmap, topic_data, course_id)

elif screen == "today_plan":
    from ui.screens.today_plan import render_today_plan

    render_today_plan()
