import streamlit as st

from memory.student_registry import login_student, register_student


def render_welcome():
    st.title("GradeMinds AI")
    st.caption("Your personalized AI study coach.")

    tab_login, tab_register = st.tabs(["Returning student", "New student"])

    with tab_register:
        st.markdown("#### Create your profile")
        name = st.text_input("Choose a username", key="reg_name")
        password = st.text_input(
            "Choose a password (min 6 chars, 1 number)", type="password", key="reg_password"
        )
        if st.button("Create Profile", type="primary"):
            if not name or not password:
                st.error("Please enter a username and a password.")
            else:
                try:
                    student = register_student(name=name, password=password)
                    st.session_state["student"] = student
                    st.session_state["screen"] = "course_selector"
                    st.session_state["student"] = student
                    st.session_state["screen"] = "course_selector"
                    st.query_params["student_id"] = student["student_id"]
                    st.query_params["screen"] = "course_selector"
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    with tab_login:
        st.markdown("#### Welcome back")
        name = st.text_input("Username", key="login_name")
        password = st.text_input("Password", type="password", key="login_password")
        if st.button("Continue", type="primary"):
            student = login_student(name, password)
            if not student:
                st.error("Username or Password not recognised.")
            else:
                st.session_state["student"] = student
                st.session_state["screen"] = "course_selector"
                st.session_state["student"] = student
                st.session_state["screen"] = "course_selector"
                st.query_params["student_id"] = student["student_id"]
                st.query_params["screen"] = "course_selector"
                st.rerun()
