from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
import requests
import os

from gemini_agent import extract_supplier_payload
from utils.session_manager import init_session, merge_session, get_missing_fields
from fusion_validator import validate_against_fusion
from fusion_client import create_supplier
from config.fusion_settings import FIELD_QUESTIONS, REQUIRED_FIELDS

app = FastAPI()

# ------------------------------------------------------------------
# In-memory session store (POC only)
# ------------------------------------------------------------------
sessions = {}

# ------------------------------------------------------------------
# Azure Bot Authentication
# ------------------------------------------------------------------
MICROSOFT_APP_ID = os.getenv("MICROSOFT_APP_ID")
MICROSOFT_APP_PASSWORD = os.getenv("MICROSOFT_APP_PASSWORD")


def get_access_token():
    url = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": MICROSOFT_APP_ID,
        "client_secret": MICROSOFT_APP_PASSWORD,
        "scope": "https://api.botframework.com/.default"
    }
    r = requests.post(url, data=data)
    r.raise_for_status()
    return r.json()["access_token"]


def send_activity(activity: dict, text: str):
    """
    Send message to Azure Bot Framework (WebChat / Teams)
    """
    token = get_access_token()

    url = f"{activity['serviceUrl']}/v3/conversations/{activity['conversation']['id']}/activities"

    payload = {
        "type": "message",
        "from": activity["recipient"],
        "recipient": activity["from"],
        "conversation": activity["conversation"],
        "replyToId": activity["id"],
        "channelId": activity.get("channelId"),
        "timestamp": datetime.utcnow().isoformat(),
        "text": text
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    requests.post(url, headers=headers, json=payload)


# ------------------------------------------------------------------
# Azure Bot Activity Model
# ------------------------------------------------------------------
class BotActivity(BaseModel):
    type: Optional[str]
    id: Optional[str]
    text: Optional[str]
    serviceUrl: Optional[str]
    channelId: Optional[str]
    from_: Optional[Dict[str, Any]]
    recipient: Optional[Dict[str, Any]]
    conversation: Optional[Dict[str, Any]]

    class Config:
        allow_population_by_field_name = True
        fields = {"from_": "from"}


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------
@app.get("/")
def root():
    return {"message": "Fusion Supplier Agent is running"}

@app.get("/health")
def health():
    return {"status": "ok"}


# ------------------------------------------------------------------
# Supplier Agent Endpoint (Azure Bot)
# ------------------------------------------------------------------
@app.post("/supplier-agent")
async def supplier_agent(request: Request):
    activity_json = await request.json()
    print("===== AZURE PAYLOAD =====")
    print(activity_json)
    print("=========================")

    activity = BotActivity(**activity_json)
    activity_dict = activity.dict(by_alias=True)

    # --------------------------------------------------------------
    # Handle conversation start
    # --------------------------------------------------------------
    if activity.type == "conversationUpdate":
        if activity_dict.get("membersAdded"):
            send_activity(activity_dict, "👋 Hi! Type **create supplier** to begin.")
        return {"status": "ok"}

    # --------------------------------------------------------------
    # Ignore non-message activities
    # --------------------------------------------------------------
    if activity.type != "message" or not activity.text:
        return {"status": "ok"}

    conversation_id = activity_dict["conversation"]["id"]
    user_input = activity.text.strip()

    # --------------------------------------------------------------
    # INIT SESSION
    # --------------------------------------------------------------
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
            send_activity(activity_dict, FIELD_QUESTIONS[current_field])
        else:
            send_activity(activity_dict, "Please provide supplier details.")

        return {"status": "ok"}

    # --------------------------------------------------------------
    # RESTORE SESSION
    # --------------------------------------------------------------
    state = sessions[conversation_id]
    session = state["session"]
    current_field = state["current_field"]
    mode = state["state"]

    # --------------------------------------------------------------
    # CONFIRM MODE
    # --------------------------------------------------------------
    if mode == "CONFIRM":
        decision = user_input.lower()

        if decision == "yes":
            status, response = create_supplier(session)
            sessions.pop(conversation_id, None)

            if status == 201:
                send_activity(
                    activity_dict,
                    f"✅ Supplier Created Successfully\n"
                    f"Supplier ID: {response.get('SupplierId')}\n"
                    f"Supplier Number: {response.get('SupplierNumber')}"
                )
            else:
                send_activity(activity_dict, "❌ Supplier creation failed.")

            return {"status": "ok"}

        if decision == "edit":
            state["state"] = "EDIT"
            send_activity(
                activity_dict,
                "Which field do you want to edit?\n" +
                "\n".join(f"{i+1}. {f}" for i, f in enumerate(REQUIRED_FIELDS))
            )
            return {"status": "ok"}

        if decision == "cancel":
            sessions.pop(conversation_id, None)
            send_activity(activity_dict, "❌ Supplier creation cancelled.")
            return {"status": "ok"}

        send_activity(activity_dict, "Please type: yes, edit, or cancel.")
        return {"status": "ok"}

    # --------------------------------------------------------------
    # EDIT MODE
    # --------------------------------------------------------------
    if mode == "EDIT":
        field_map = {str(i + 1): f for i, f in enumerate(REQUIRED_FIELDS)}

        if user_input in field_map:
            field = field_map[user_input]
            state["current_field"] = field
            state["state"] = "COLLECTING"
            send_activity(activity_dict, FIELD_QUESTIONS[field])
        else:
            send_activity(activity_dict, "Invalid choice. Try again.")

        return {"status": "ok"}

    # --------------------------------------------------------------
    # COLLECTING MODE
    # --------------------------------------------------------------
    if current_field:
        extracted = extract_supplier_payload(user_input)
        session = merge_session(session, extracted)

        if not session.get(current_field):
            session[current_field] = user_input

    state["session"] = session
    state["current_field"] = None

    # --------------------------------------------------------------
    # NEXT FIELD
    # --------------------------------------------------------------
    missing = get_missing_fields(session)

    if missing:
        next_field = missing[0]
        state["current_field"] = next_field
        send_activity(activity_dict, FIELD_QUESTIONS[next_field])
        return {"status": "ok"}

    # --------------------------------------------------------------
    # FINAL VALIDATION
    # --------------------------------------------------------------
    errors = validate_against_fusion(session)
    if errors:
        send_activity(activity_dict, "Validation failed:\n" + "\n".join(errors))
        return {"status": "ok"}

    # --------------------------------------------------------------
    # CONFIRM SUMMARY
    # --------------------------------------------------------------
    summary = "\n".join(f"{i+1}. {f}: {session[f]}" for i, f in enumerate(REQUIRED_FIELDS))
    state["state"] = "CONFIRM"

    send_activity(
        activity_dict,
        "Please review the supplier details:\n\n" +
        summary +
        "\n\nConfirm? (yes / edit / cancel)"
    )

    return {"status": "ok"}
