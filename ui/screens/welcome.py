import streamlit as st

from memory.student_registry import login_student, register_student


def render_welcome():
    st.title("GradeMinds AI")
    st.caption("Your personalized AI study coach.")

    tab_login, tab_register = st.tabs(["Returning student", "New student"])

    with tab_register:
        st.markdown("#### Create your profile")
        name = st.text_input("Choose a name", key="reg_name")
        pin = st.text_input(
            "Choose a 4-digit PIN", type="password", max_chars=4, key="reg_pin"
        )
        if st.button("Create Profile", type="primary"):
            if not name or not pin or len(pin) != 4:
                st.error("Please enter a name and a 4-digit PIN.")
            else:
                try:
                    student = register_student(name=name, pin=pin)
                    st.session_state["student"] = student
                    st.session_state["screen"] = "course_selector"
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    with tab_login:
        st.markdown("#### Welcome back")
        name = st.text_input("Your name", key="login_name")
        pin = st.text_input("Your PIN", type="password", max_chars=4, key="login_pin")
        if st.button("Continue", type="primary"):
            student = login_student(name, pin)
            if not student:
                st.error("Name or PIN not recognised.")
            else:
                st.session_state["student"] = student
                st.session_state["screen"] = "course_selector"
                st.rerun()
