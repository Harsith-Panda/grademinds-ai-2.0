import streamlit as st


def render_diagnosis_view(on_confirm):
    ml_output = st.session_state.get("pending_ml_output", {})
    topic = st.session_state.get("pending_topic", "")

    if not ml_output:
        st.error("No prediction data found. Please go back and re-enter your details.")
        if st.button("← Back"):
            st.session_state["screen"] = "academic_onboarding"
            st.rerun()
        return

    score = ml_output["predicted_score"]
    pass_fail = ml_output["pass_fail"]
    pass_prob = ml_output["pass_probability"] * 100
    gaps = ml_output["feature_gaps"]

    st.markdown(f"## 📊 Your Academic Analysis — {topic}")
    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        color = "🟢" if pass_fail == "PASS" else "🔴"
        st.metric("Predicted Score", f"{score:.1f} / 100")
    with col2:
        st.metric("Prediction", f"{color} {pass_fail}")
    with col3:
        st.metric("Pass Probability", f"{pass_prob:.1f}%")

    st.divider()

    st.markdown("### 📈 Feature Analysis")
    st.caption(
        "How each factor compares to the dataset average and its impact on your score."
    )

    for gap in gaps:
        feat = gap["feature"]
        if feat == "Extracurricular_Activities_Yes":
            val_display = "Yes" if gap["student_value"] == 1 else "No"
            avg_display = "~50% do"
        else:
            val_display = f"{gap['student_value']:.1f}"
            avg_display = f"{gap['average_value']:.1f}"

        impact_color = (
            "🔴"
            if gap["score_impact"] < -5
            else "🟡"
            if gap["score_impact"] < 0
            else "🟢"
        )
        arrow = "↓" if gap["is_below_avg"] else "↑"

        col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
        with col1:
            st.markdown(f"**{gap['label']}**")
        with col2:
            st.markdown(f"You: **{val_display}** {arrow} Avg: {avg_display}")
        with col3:
            impact_str = f"{gap['score_impact']:+.1f} pts"
            st.markdown(f"{impact_color} {impact_str}")
        with col4:
            st.markdown(f"Importance: {gap['importance'] * 100:.0f}%")

    st.divider()

    diagnosis = st.session_state.get("diagnosis_result")

    if not diagnosis:
        with st.spinner("🤖 AI Diagnostician is analysing your results..."):
            from agent.nodes.diagnostician import diagnostician_node

            temp_state = {
                "ml_output": ml_output,
                "topic": topic,
                "mode": "academic",
                "diagnosis": None,
            }
            result = diagnostician_node(temp_state)
            diagnosis = result.get("diagnosis", {})
            st.session_state["diagnosis_result"] = diagnosis

    if diagnosis:
        st.markdown("### 🔍 AI Diagnosis")
        st.info(f"**{diagnosis.get('summary', '')}**")

        weak_areas = diagnosis.get("weak_areas", [])
        if weak_areas:
            st.markdown("**Key issues identified:**")
            for wa in weak_areas:
                impact_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                    wa["impact"], "⚪"
                )
                with st.expander(
                    f"{impact_emoji} {wa['factor']} — {wa['impact'].upper()} impact ({wa['score_lost']} lost)"
                ):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Your value:** {wa['student_value']}")
                        st.markdown(f"**Average:** {wa['average_value']}")
                    with col2:
                        st.markdown(f"**Score lost:** {wa['score_lost']}")
                    st.markdown(f"**What to do:** {wa['action']}")

        recs = diagnosis.get("recommendations", [])
        if recs:
            st.markdown("**Top recommendations:**")
            for i, rec in enumerate(recs, 1):
                st.markdown(f"{i}. {rec}")

    st.divider()

    st.markdown("### Ready to build your personalised roadmap?")
    st.caption(
        "GradeMinds will use this analysis to front-load the topics that will "
        "have the most impact on your score."
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        if st.button("✅ Build My Roadmap", type="primary", use_container_width=True):
            on_confirm(diagnosis)
    with col2:
        if st.button("← Adjust my data", use_container_width=True):
            st.session_state.pop("diagnosis_result", None)
            st.session_state["screen"] = "academic_onboarding"
            st.rerun()
