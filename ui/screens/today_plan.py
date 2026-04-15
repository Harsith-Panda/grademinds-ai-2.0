import streamlit as st
from datetime import date, datetime
from memory.chroma_ops import update_topic_after_session, get_topics_for_course
from memory.student_registry import update_course_progress, record_session_activity

BLOOM_MAP = {
    1: "Remember",
    2: "Understand",
    3: "Apply",
    4: "Analyze",
    5: "Evaluate",
    6: "Create"
}

def render_today_plan(todays_plan, topic_data, course_info, course_id):
    """
    Renders the beautiful Daily Study Briefing screen.
    """
    st.markdown("""
        <style>
        .stButton button { width: 100%; }
        .topic-card {
            padding: 20px;
            border-radius: 10px;
            border: 1px solid #e0e0e0;
            margin-bottom: 20px;
        }
        .streak-fire { color: #FF4B4B; font-weight: bold; }
        </style>
    """, unsafe_allow_html=True)

    # ── SECTION A: HEADER ───────────────────────────────────────────────────
    today_str = date.today().strftime("%A, %d %B")
    
    st.title("Today's Study Briefing")
    st.markdown(f"**{today_str}** · {course_info['topic']}")

    st.divider()

    # ── SECTION D: ALL DONE STATE (Exclusive check) ─────────────────────────
    if todays_plan.get("all_done_today"):
        st.balloons()
        st.success("### You're all caught up for today! 🎉")
        st.write("Excellent work. Your brain is absorbing the material perfectly.")
        
        # Next session preview
        st.markdown("#### Coming up tomorrow...")
        _render_tomorrow_preview(topic_data, todays_plan['current_week'])
        return

    # ── SECTION B: NEW TOPIC CARD ───────────────────────────────────────────
    new_topic_name = todays_plan.get("new_topic")
    if new_topic_name:
        st.markdown("### 🎯 New Milestone")
        
        # Get metadata for this topic
        meta = next((t for t in topic_data if t['name'] == new_topic_name), {})
        
        # Card container
        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"## {new_topic_name}")
                st.caption(f"Week {todays_plan['current_week']} · {todays_plan['week_focus']}")
            
            with col2:
                # Bloom Badge
                bloom_val = meta.get("bloom_level", 1)
                st.info(f"**{BLOOM_MAP.get(bloom_val, 'Learn')}**")
            
            # Badges
            c_tag, c_time, c_type = st.columns(3)
            c_tag.caption(f"📍 Week {meta.get('week', 1)}")
            c_time.caption(f"⏱️ {meta.get('estimated_hours', 1.0)} hours")
            t_type = meta.get("topic_type", "must_know").replace("_", " ").title()
            c_type.caption(f"💎 {t_type}")

            st.divider()
            
            # Resource Placeholder (Node 5)
            st.markdown("#### 📚 Recommended Resources")
            st.info("🔍 *Knowledge retrieval in progress... (Node 5 integration coming soon)*")
            
            # Action Buttons
            bt1, bt2 = st.columns(2)
            if bt1.button("Mark as Done ✅", type="primary", key="btn_new_done"):
                _handle_completion(course_id, new_topic_name, False)
            
            if bt2.button("Mark as Struggled ⚠️", key="btn_new_hard"):
                _handle_completion(course_id, new_topic_name, True)

    # ── SECTION C: REVIEW CARDS ─────────────────────────────────────────────
    reviews = todays_plan.get("review_topics", [])
    if reviews:
        st.divider()
        st.markdown("### 🔄 Daily Review Queue")
        st.caption("Spaced repetition keeps these topics fresh in your long-term memory.")
        
        for i, r_name in enumerate(reviews):
            meta = next((t for t in topic_data if t['name'] == r_name), {})
            
            with st.expander(f"Review: {r_name}"):
                # Calculate days since last reviewed
                last_rev = meta.get("last_reviewed")
                if last_rev:
                    dt = datetime.fromisoformat(last_rev).date()
                    days = (date.today() - dt).days
                else:
                    days = "unknown"
                
                st.write(f"Last seen: **{days} days ago**")
                st.write(f"Times reviewed before: **{meta.get('times_reviewed', 0)}**")
                
                b1, b2 = st.columns(2)
                if b1.button("Got it ✓", key=f"rev_done_{i}"):
                    _handle_completion(course_id, r_name, False)
                if b2.button("Still struggling", key=f"rev_hard_{i}"):
                    _handle_completion(course_id, r_name, True)

    # ── SECTION E: TOMORROW'S PREVIEW ───────────────────────────────────────
    st.divider()
    with st.expander("📅 Coming up next..."):
        _render_tomorrow_preview(topic_data, todays_plan['current_week'], todays_plan.get("new_topic"))


def _render_tomorrow_preview(topic_data, current_week, todays_new_topic=None):
    """Internal helper to show upcoming work."""
    # Find the next available not_started topic after the one assigned for today
    upcoming = [t for t in topic_data if t['status'] == 'not_started' and t['name'] != todays_new_topic]
    # Sort by week then bloom level
    upcoming.sort(key=lambda x: (x.get('week', 1), x.get('bloom_level', 1)))
    
    if upcoming:
        next_t = upcoming[0]
        st.markdown(f"**Next New Topic:** {next_t['name']} (Week {next_t['week']})")
    else:
        st.markdown("**No more new topics!** You are completing the curriculum.")

    # Show reviews due tomorrow
    reviews_tomorrow = []
    for t in topic_data:
        if t.get("status") == "done":
            last_rev = t.get("last_reviewed")
            interval = int(t.get("review_interval", 1))
            if last_rev:
                dt = datetime.fromisoformat(last_rev).date()
                if (date.today() - dt).days + 1 >= interval:
                    reviews_tomorrow.append(t['name'])
    
    if reviews_tomorrow:
        st.markdown(f"**Scheduled for Review:** {', '.join(reviews_tomorrow[:3])}")
    else:
        st.markdown("*No reviews scheduled for tomorrow.*")


def _handle_completion(course_id, topic_name, struggled):
    """Helper to update Chroma and clear the UI cache."""
    # 1. Update Spaced Rep logic in Chroma
    update_topic_after_session(course_id, topic_name, struggled)
    
    # 2. Update session activity
    student = st.session_state.get("student")
    if student:
        record_session_activity(student["student_id"])
    
    # 3. Clear the plan cache so Node 4 re-evaluates
    cache_key = f"todays_plan_{course_id}_{str(date.today())}"
    if cache_key in st.session_state:
        del st.session_state[cache_key]
    
    st.success("Progress updated!")
    st.rerun()
