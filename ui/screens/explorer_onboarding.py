import streamlit as st

from agent.nodes.curriculum_parser import extract_syllabus_text
from memory.student_registry import create_course


def render_explorer_onboarding(on_submit):
    """
    Renders the Explorer Mode onboarding form.
    on_submit(state_dict) is called when the student clicks Start.
    """
    st.markdown("## What do you want to learn?")
    st.caption("GradeMinds will build you a personalized roadmap and daily study plan.")

    col1, col2 = st.columns([3, 2])

    with col1:
        topic = st.text_input(
            "Topic or skill",
            placeholder="e.g. Machine Learning, Web Development, Photography...",
        )

        known = st.text_area(
            "What do you already know about this?",
            placeholder="e.g. I know basic Python and some algebra. Leave blank if starting fresh.",
            height=80,
        )

        goal = st.radio(
            "What is your end goal?",
            options=[
                "Understand it conceptually",
                "Build a real project",
                "Pass an exam or test",
            ],
            horizontal=True,
        )

        hours = st.slider(
            "Hours available per week", min_value=1, max_value=20, value=5
        )

    with col2:
        st.markdown("#### Have a syllabus? (optional)")
        st.caption(
            "Upload your course syllabus PDF and GradeMinds will base the "
            "roadmap on your actual curriculum instead of generating one from scratch."
        )
        uploaded_pdf = st.file_uploader(
            "Upload syllabus PDF",
            type=["pdf"],
            label_visibility="collapsed",
        )

        if uploaded_pdf is not None:
            syllabus_text = extract_syllabus_text(uploaded_pdf.read())
            if syllabus_text:
                st.success(
                    f"Syllabus loaded — {len(syllabus_text)} characters extracted."
                )
                with st.expander("Preview extracted text"):
                    st.text(syllabus_text[:500] + "...")
            else:
                st.warning(
                    "Could not extract text from this PDF. Try a different file."
                )
                syllabus_text = ""
        else:
            syllabus_text = ""

    st.divider()

    if st.button("Build My Roadmap", type="primary", use_container_width=True):
        if not topic.strip() and not syllabus_text:
            st.error("Please enter a topic or upload a syllabus.")
            return

        display_topic = topic.strip() or (
            uploaded_pdf.name if uploaded_pdf else "My Course"
        )
        student = st.session_state["student"]

        sa = {
            "known": known.strip(),
            "hours_per_week": hours,
            "goal": goal,
        }

        # Create course record — gets a fresh course_id
        course = create_course(
            student_id=student["student_id"],
            topic=display_topic,
            mode="explorer",
            self_assessment=sa,
        )

        from datetime import date

        initial_state = {
            "mode": "explorer",
            "topic": display_topic,
            "syllabus_text": syllabus_text,
            "self_assessment": sa,
            "academic_features": {},
            "predicted_score": None,
            "pass_fail": None,
            "diagnosis": {},
            "topic_graph": None,
            "roadmap": None,
            "todays_plan": None,
            "resources": None,
            "student_id": student["student_id"],
            "course_id": course["course_id"],  # ← course-scoped
            "session_date": str(date.today()),
            "chroma_initialized": False,
        }

        on_submit(initial_state)
