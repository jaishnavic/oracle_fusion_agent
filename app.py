from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
import requests
import os
import logging
import json
 
from gemini_agent import extract_supplier_payload
from utils.session_manager import init_session, merge_session, get_missing_fields
from fusion_validator import validate_against_fusion
from fusion_client import create_supplier
from config.fusion_settings import FIELD_QUESTIONS, REQUIRED_FIELDS
 
app = FastAPI()
logging.basicConfig(level=logging.INFO)
 
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

    url = "https://login.microsoftonline.com/b3a4b690-cc48-44de-8fa2-1211996e5d85/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": os.getenv("MICROSOFT_APP_ID"),
        "client_secret": os.getenv("MICROSOFT_APP_PASSWORD"),
        "scope": "https://api.botframework.com/.default"
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"

    }
    r = requests.post(url, data=data, headers=headers)
    r.raise_for_status()
    return r.json()["access_token"]


def send_activity(activity: dict, text: str):
    try:
        token = get_access_token()

        # ✅ Normalize "from"
        sender = activity.get("from") or activity.get("from_")
        recipient = activity.get("recipient")

        if not sender or not recipient:
            logging.error("Invalid activity payload for sending message")
            logging.error(activity)
            return

        url = f"{activity['serviceUrl']}/v3/conversations/{activity['conversation']['id']}/activities"

        payload = {
            "type": "message",
            "from": recipient,   # BOT
            "recipient": sender, # USER
            "conversation": activity["conversation"],
            "replyToId": activity.get("id"),
            "text": text
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        requests.post(url, headers=headers, json=payload)

    except Exception:
        logging.exception("Failed to send activity")

# ------------------------------------------------------------------
# Azure Bot Activity Model (SAFE)
# ------------------------------------------------------------------
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
        populate_by_name = True
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
# Supplier Agent Endpoint
# ------------------------------------------------------------------
@app.post("/supplier-agent")
async def supplier_agent(request: Request):
    activity_json = await request.json()

    logging.info("===== AZURE PAYLOAD =====")
    logging.info(activity_json)
    logging.info("=========================")

    activity_type = activity_json.get("type")

    # --------------------------------------------------------------
    # Ignore typing / ping
    # --------------------------------------------------------------
    if activity_type in ["typing", "ping"]:
        return {"status": "ok"}

    # --------------------------------------------------------------
    # Conversation start
    # --------------------------------------------------------------
    if activity_type == "conversationUpdate":
        if activity_json.get("membersAdded"):
            send_activity(activity_json, "👋 Hi! Type **create supplier** to begin.")
        return {"status": "ok"}

    # --------------------------------------------------------------
    # Only MESSAGE activities
    # --------------------------------------------------------------
    if activity_type != "message":
        return {"status": "ok"}

    activity = BotActivity(**activity_json)
    activity_dict = activity.model_dump(by_alias=True)

    if not activity.text:
        return {"status": "ok"}

    conversation_id = activity_dict["conversation"]["id"]
    user_input = activity.text.strip().lower()

    # ==============================================================
    # ✅ FIXED INIT SESSION LOGIC
    # ==============================================================
    if conversation_id not in sessions:

        # ---- enforce command trigger ----
        if user_input not in ["create supplier", "create a supplier"]:
            send_activity(
                activity_json,
                "Please type **create supplier** to start supplier creation."
            )
            return {"status": "ok"}

        # ---- explicitly start supplier flow ----
        session = init_session()
        first_field = REQUIRED_FIELDS[0]

        sessions[conversation_id] = {
            "session": session,
            "current_field": first_field,
            "state": "COLLECTING"
        }

        send_activity(activity_json, FIELD_QUESTIONS[first_field])
        return {"status": "ok"}

    # ==============================================================
    # RESTORE SESSION
    # ==============================================================
    state = sessions[conversation_id]
    session = state["session"]
    current_field = state["current_field"]
    mode = state["state"]

    # --------------------------------------------------------------
    # CONFIRM MODE
    # --------------------------------------------------------------
    if mode == "CONFIRM":
        decision = user_input

        if decision == "yes":
            # 1. Trigger the API
            status, response = create_supplier(session)
            
            # 2. DEBUG LOGGING: This will show up in your Render logs
            logging.info(f"--- FUSION DEBUG START ---")
            logging.info(f"Status: {status}")
            logging.info(f"Raw Response: {response}")
            logging.info(f"--- FUSION DEBUG END ---")

            sessions.pop(conversation_id, None)

            # 3. Handle the Response
            if status == 201 and isinstance(response, dict):
                supplier_id = response.get("SupplierId", "N/A")
                supplier_number = response.get("SupplierNumber", "N/A")

                send_activity(
                    activity_json,
                    "✅ **Success! Supplier created.**\n\n"
                    f"Supplier ID: {supplier_id}\n"
                    f"Supplier Number: {supplier_number}"
                )
                return {"status": "ok"}

            else:
                # FAILURE: Send the exact error string to Azure Chat
                # If response is a dict, convert it to a readable string
                error_detail = json.dumps(response, indent=2) if isinstance(response, dict) else str(response)
                
                error_message = (
                    f"❌ **Fusion API Error ({status})**\n\n"
                    f"Please check the details below:\n"
                    f"```\n{error_detail}\n```"
                )
                
                send_activity(activity_json, error_message)
            
            return {"status": "ok"}


        if decision == "edit":
            state["state"] = "EDIT"
            send_activity(
                activity_json,
                "Which field do you want to edit?\n" +
                "\n".join(f"{i+1}. {f}" for i, f in enumerate(REQUIRED_FIELDS))
            )
            return {"status": "ok"}

        if decision == "cancel":
            sessions.pop(conversation_id, None)
            send_activity(activity_json, "❌ Supplier creation cancelled.")
            return {"status": "ok"}

        send_activity(activity_json, "Please type: yes, edit, or cancel.")
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
            send_activity(activity_json, FIELD_QUESTIONS[field])
        else:
            send_activity(activity_json, "Invalid choice. Try again.")

        return {"status": "ok"}

    # --------------------------------------------------------------
    # COLLECTING MODE
    # --------------------------------------------------------------
    if current_field:
        extracted = extract_supplier_payload(user_input)
        session = merge_session(session, extracted)

        if not session.get(current_field):
            session[current_field] = activity.text.strip()

    state["session"] = session
    state["current_field"] = None

    missing = get_missing_fields(session)

    if missing:
        next_field = missing[0]
        state["current_field"] = next_field
        send_activity(activity_json, FIELD_QUESTIONS[next_field])
        return {"status": "ok"}

    # --------------------------------------------------------------
    # FINAL VALIDATION
    # --------------------------------------------------------------
    errors = validate_against_fusion(session)
    if errors:
        send_activity(activity_json, "Validation failed:\n" + "\n".join(errors))
        return {"status": "ok"}

    # --------------------------------------------------------------
    # CONFIRM SUMMARY
    # --------------------------------------------------------------
    summary = "\n".join(
        f"{i+1}. {f}: {session[f]}"
        for i, f in enumerate(REQUIRED_FIELDS)
    )

    state["state"] = "CONFIRM"

    send_activity(
        activity_json,
        "Please review the supplier details:\n\n"
        + summary
        + "\n\nConfirm? (yes / edit / cancel)"
    )

    return {"status": "ok"}
 