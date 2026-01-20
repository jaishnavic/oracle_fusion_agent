import streamlit as st
import requests

API_URL = "http://localhost:8009/supplier-agent"

st.set_page_config(page_title="Supplier Agent Chat", layout="centered")

st.title("🤖 Supplier Creation Agent")
st.write("Type create supplier to start the process.")

# -----------------------------
# Session State Initialization
# -----------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "sessionId" not in st.session_state:
    st.session_state.sessionId = None


# -----------------------------
# Display Chat History
# -----------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


# -----------------------------
# User Input
# -----------------------------
user_input = st.chat_input("Type your message...")

if user_input:
    # Show user message
    st.session_state.messages.append({
        "role": "user",
        "content": user_input
    })

    with st.chat_message("user"):
        st.markdown(user_input)

    # -----------------------------
    # Call FastAPI
    # -----------------------------
    payload = {
        "message": user_input
    }

    if st.session_state.sessionId:
        payload["sessionId"] = st.session_state.sessionId

    try:
        response = requests.post(API_URL, json=payload, timeout=60)
        data = response.json() if response.text else {}


    except Exception as e:
        with st.chat_message("assistant"):
            st.error(f"API Error: {e}")
        st.stop()

    # -----------------------------
    # Store sessionId
    # -----------------------------
    if "sessionId" in data:
        st.session_state.sessionId = data["sessionId"]

    # -----------------------------
    # Show Bot Reply
    # -----------------------------
    reply = data.get("reply", "No response")

    st.session_state.messages.append({
        "role": "assistant",
        "content": reply
    })

    with st.chat_message("assistant"):
        st.markdown(reply)

    # -----------------------------
    # Final success response
    # -----------------------------
    if "SupplierId" in data:
        success_msg = (
            f"✅ **Supplier Created Successfully**\n\n"
            f"- Supplier ID: `{data.get('SupplierId')}`\n"
            f"- Supplier Number: `{data.get('SupplierNumber')}`"
        )

        st.session_state.messages.append({
            "role": "assistant",
            "content": success_msg
        })

        with st.chat_message("assistant"):
            st.markdown(success_msg)

        # Reset session after success
        st.session_state.sessionId = None
