from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
import requests

from gemini_agent import extract_supplier_payload
from utils.session_manager import init_session, merge_session, get_missing_fields
from fusion_validator import validate_against_fusion
from fusion_client import create_supplier
from config.fusion_settings import FIELD_QUESTIONS, REQUIRED_FIELDS

app = FastAPI()

# In-memory session store (POC only – not production safe)
sessions = {}

# -------------------------------
# Azure Bot helpers
# -------------------------------

def send_activity(activity: dict, reply: dict):
    service_url = activity["serviceUrl"]
    conversation_id = activity["conversation"]["id"]

    url = f"{service_url}/v3/conversations/{conversation_id}/activities"

    headers = {
        "Content-Type": "application/json"
        # Authorization header will be added later
    }

    requests.post(url, headers=headers, json=reply)


def bot_activity_response(text: str, activity: dict):
    return {
        "type": "message",
        "from": activity.get("recipient", {}),   # bot
        "recipient": activity.get("from", {}),   # user
        "conversation": activity.get("conversation", {}),
        "replyToId": activity.get("id"),
        "serviceUrl": activity.get("serviceUrl"),
        "channelId": activity.get("channelId"),
        "timestamp": datetime.utcnow().isoformat(),
        "text": text
    }


# -------------------------------
# Azure Bot Activity Model
# -------------------------------

class BotActivity(BaseModel):
    type: Optional[str] = None
    id: Optional[str] = None
    text: Optional[str] = None
    serviceUrl: Optional[str] = None
    channelId: Optional[str] = None
    from_: Optional[Dict[str, Any]] = None
    recipient: Optional[Dict[str, Any]] = None
    conversation: Optional[Dict[str, Any]] = None

    class Config:
        allow_population_by_field_name = True
        fields = {"from_": "from"}


# -------------------------------
# Health
# -------------------------------

@app.get("/")
def root():
    return {"message": "Fusion AI Agent is running"}

@app.get("/health")
def health():
    return {"status": "ok"}


# -------------------------------
# Supplier Agent Endpoint
# -------------------------------

@app.post("/supplier-agent")
async def supplier_agent(request: Request):

    raw_body = await request.json()
    print("===== AZURE RAW PAYLOAD =====")
    print(raw_body)
    print("============================")

    activity = BotActivity(**raw_body)
    activity_dict = activity.dict(by_alias=True)

    # Ignore non-message activities
    if activity.type != "message":
        return {}

    if not activity_dict.get("from") or not activity_dict.get("recipient"):
        return {}

    conversation_id = activity_dict["conversation"]["id"]
    user_input = (activity.text or "").strip()

    # -------------------------------
    # INIT SESSION
    # -------------------------------

    if conversation_id not in sessions:
        session = init_session()

        extracted = extract_supplier_payload(user_input)
        session = merge_session(session, extracted)

        missing = get_missing_fields(session)
        current_field = missing[0] if missing else None

        sessions[conversation_id] = {
            "session": session,
            "current_field": current_field,
            "state": "COLLECTING"
        }

        if current_field:
            reply = bot_activity_response(
                FIELD_QUESTIONS[current_field],
                activity_dict
            )
            send_activity(activity_dict, reply)
            return {}

    # -------------------------------
    # RESTORE SESSION
    # -------------------------------

    state = sessions[conversation_id]
    session = state["session"]
    current_field = state["current_field"]
    mode = state["state"]

    # -------------------------------
    # CONFIRM MODE
    # -------------------------------

    if mode == "CONFIRM":
        decision = user_input.lower()

        if decision == "yes":
            status, response = create_supplier(session)
            sessions.pop(conversation_id, None)

            if status == 201:
                reply = bot_activity_response(
                    f"✅ Supplier created successfully\n"
                    f"SupplierId: {response.get('SupplierId')}\n"
                    f"SupplierNumber: {response.get('SupplierNumber')}",
                    activity_dict
                )
                send_activity(activity_dict, reply)
                return {}

            reply = bot_activity_response(
                "❌ Supplier creation failed",
                activity_dict
            )
            send_activity(activity_dict, reply)
            return {}

        if decision == "edit":
            state["state"] = "EDIT"
            reply = bot_activity_response(
                "Which field do you want to edit? (Enter number)",
                activity_dict
            )
            send_activity(activity_dict, reply)
            return {}

        if decision == "cancel":
            sessions.pop(conversation_id, None)
            reply = bot_activity_response(
                "Supplier creation cancelled.",
                activity_dict
            )
            send_activity(activity_dict, reply)
            return {}

        reply = bot_activity_response(
            "Please type: yes, edit, or cancel.",
            activity_dict
        )
        send_activity(activity_dict, reply)
        return {}

    # -------------------------------
    # EDIT MODE
    # -------------------------------

    if mode == "EDIT":
        field_index_map = {str(i + 1): f for i, f in enumerate(REQUIRED_FIELDS)}

        if user_input in field_index_map:
            field = field_index_map[user_input]
            state["current_field"] = field
            state["state"] = "COLLECTING"

            reply = bot_activity_response(
                FIELD_QUESTIONS[field],
                activity_dict
            )
            send_activity(activity_dict, reply)
            return {}

        reply = bot_activity_response(
            "Invalid number. Try again.",
            activity_dict
        )
        send_activity(activity_dict, reply)
        return {}

    # -------------------------------
    # COLLECTING MODE
    # -------------------------------

    if current_field:
        extracted = extract_supplier_payload(user_input)
        session = merge_session(session, extracted)

        if not session.get(current_field):
            session[current_field] = user_input

    state["session"] = session
    state["current_field"] = None

    # -------------------------------
    # NEXT FIELD
    # -------------------------------

    missing = get_missing_fields(session)

    if missing:
        next_field = missing[0]
        state["current_field"] = next_field

        reply = bot_activity_response(
            FIELD_QUESTIONS[next_field],
            activity_dict
        )
        send_activity(activity_dict, reply)
        return {}

    # -------------------------------
    # FINAL VALIDATION
    # -------------------------------

    errors = validate_against_fusion(session)

    if errors:
        state["current_field"] = REQUIRED_FIELDS[0]

        reply = bot_activity_response(
            "Validation failed:\n" + "\n".join(errors),
            activity_dict
        )
        send_activity(activity_dict, reply)
        return {}

    # -------------------------------
    # CONFIRM SUMMARY
    # -------------------------------

    summary = "\n".join(
        f"{i+1}. {f}: {session[f]}" for i, f in enumerate(REQUIRED_FIELDS)
    )

    state["state"] = "CONFIRM"

    reply = bot_activity_response(
        "Please review:\n\n" + summary + "\n\nConfirm? (yes / edit / cancel)",
        activity_dict
    )
    send_activity(activity_dict, reply)
    return {}
