import streamlit as st

from agent.nodes.curriculum_parser import extract_syllabus_text
from ml.predictor import get_feature_averages, get_feature_labels, run_prediction


def render_academic_onboarding(on_submit):
    st.markdown("## 🎓 Academic Mode")
    st.caption(
        "Enter your academic data. The ML model will predict your score and identify what to focus on."
    )

    averages = get_feature_averages()
    labels = get_feature_labels()

    with st.form("academic_form"):
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### Your academic data")

            study_hours = st.slider(
                f"{labels['Study_Hours_per_Week']}",
                min_value=1,
                max_value=60,
                value=int(averages["Study_Hours_per_Week"]),
                help=f"Dataset average: {averages['Study_Hours_per_Week']:.0f} hrs/week",
            )

            attendance = st.slider(
                f"{labels['Attendance_Rate']} (%)",
                min_value=0,
                max_value=100,
                value=int(averages["Attendance_Rate"]),
                help=f"Dataset average: {averages['Attendance_Rate']:.1f}%",
            )

            past_scores = st.slider(
                f"{labels['Past_Exam_Scores']}",
                min_value=0,
                max_value=100,
                value=int(averages["Past_Exam_Scores"]),
                help=f"Dataset average: {averages['Past_Exam_Scores']:.1f}",
            )

            extra = st.radio(
                labels["Extracurricular_Activities_Yes"],
                options=["No", "Yes"],
                horizontal=True,
            )

        with col2:
            st.markdown("#### Study context")

            topic = st.text_input(
                "Subject or course name",
                placeholder="e.g. Mathematics, Physics, Computer Science...",
            )

            goal = st.radio(
                "What is your goal?",
                options=["Pass the exam", "Score above average", "Get top marks"],
                horizontal=False,
            )

            hours_available = st.slider(
                "Study hours available per week for improvement",
                min_value=1,
                max_value=20,
                value=8,
            )

            st.markdown("#### Syllabus (optional)")
            st.caption("Upload to base your roadmap on actual course content.")
            uploaded_pdf = st.file_uploader(
                "Upload syllabus PDF", type=["pdf"], label_visibility="collapsed"
            )

        submitted = st.form_submit_button(
            "🔍 Analyse & Build Roadmap", type="primary", use_container_width=True
        )

    if submitted:
        if not topic.strip():
            st.error("Please enter a subject or course name.")
            return

        features = {
            "Study_Hours_per_Week": float(study_hours),
            "Attendance_Rate": float(attendance),
            "Past_Exam_Scores": float(past_scores),
            "Extracurricular_Activities_Yes": 1.0 if extra == "Yes" else 0.0,
        }

        syllabus_text = ""
        if uploaded_pdf:
            syllabus_text = extract_syllabus_text(uploaded_pdf.read())

        with st.spinner("Running ML analysis..."):
            ml_output = run_prediction(features)

        st.session_state["pending_ml_output"] = ml_output
        st.session_state["pending_topic"] = topic.strip()
        st.session_state["pending_syllabus"] = syllabus_text
        st.session_state["pending_goal"] = goal
        st.session_state["pending_hours"] = hours_available
        st.session_state["pending_features"] = features
        st.session_state["screen"] = "diagnosis_view"
        st.rerun()
