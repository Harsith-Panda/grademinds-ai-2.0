import streamlit as st

from memory.chroma_ops import update_topic_after_session


def render_roadmap_view(roadmap: list[dict], topic_data: list[dict], course_id: str):
    if not roadmap:
        st.warning("No roadmap found. Please complete onboarding first.")
        if st.button("Go to onboarding"):
            st.session_state["screen"] = "onboarding"
            st.rerun()
        return

    # Build a quick lookup: topic name → its Chroma metadata
    topic_meta = {t["name"]: t for t in topic_data}

    # Summary stats
    total_topics = sum(len(w["topics"]) for w in roadmap)
    done_topics = sum(1 for t in topic_data if t.get("status") == "done")
    pct = int((done_topics / total_topics * 100) if total_topics else 0)

    st.markdown("## Your Learning Roadmap")
    st.progress(
        pct / 100, text=f"{done_topics}/{total_topics} topics complete ({pct}%)"
    )
    st.divider()

    for week in roadmap:
        week_num = week["week"]
        week_topics = week["topics"]
        week_done = sum(
            1 for t in week_topics if topic_meta.get(t, {}).get("status") == "done"
        )
        week_complete = week_done == len(week_topics)

        label = (
            f"Week {week_num} — {week['focus']} (Complete)"
            if week_complete
            else f"Week {week_num} — {week['focus']}"
        )

        with st.expander(label, expanded=(week_done < len(week_topics))):
            st.caption(
                f"{week['total_hours']}h estimated · {week_done}/{len(week_topics)} done"
            )
            for topic_name in week_topics:
                meta = topic_meta.get(topic_name, {})
                status = meta.get("status", "not_started")

                col1, col2, col3 = st.columns([5, 1, 1])
                with col1:
                    icon = (
                        "[Done]"
                        if status == "done"
                        else "[In Progress]"
                        if status == "in_progress"
                        else "[Not Started]"
                    )
                    badge = (
                        "must-know"
                        if meta.get("topic_type") == "must_know"
                        else "enrichment"
                    )
                    st.markdown(f"{icon} **{topic_name}** &nbsp; `{badge}`")

                with col2:
                    if status != "done":
                        if st.button("Done (Easy)", key=f"done_{topic_name}", use_container_width=True):
                            update_topic_after_session(
                                course_id,
                                topic_name,
                                struggled=False,
                            )
                            st.rerun()
                    else:
                        st.write("Done")

                with col3:
                    if status != "done":
                        if st.button("Done (Hard)", key=f"hard_{topic_name}", use_container_width=True):
                            update_topic_after_session(
                                course_id,
                                topic_name,
                                struggled=True,
                            )
                            st.rerun()

    st.info("**Tip:** 'Done (Easy)' schedules a review in 2-3 days. 'Done (Hard)' schedules it for tomorrow.")
