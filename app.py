from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
import requests
import os
import logging

from gemini_agent import extract_supplier_payload
from utils.session_manager import init_session, merge_session, get_missing_fields
from fusion_validator import validate_against_fusion
from fusion_client import create_supplier
from config.fusion_settings import FIELD_QUESTIONS, REQUIRED_FIELDS

app = FastAPI()
logging.basicConfig(level=logging.INFO)

sessions = {}

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
    token = get_access_token()
    if not token:
        logging.error("❌ Unable to acquire token, message not sent")
        return

    url = f"{activity['serviceUrl']}/v3/conversations/{activity['conversation']['id']}/activities"

    payload = {
        "type": "message",
        "from": activity["recipient"],
        "recipient": activity["from"],
        "conversation": activity["conversation"],
        "replyToId": activity.get("id"),
        "text": text
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    requests.post(url, headers=headers, json=payload)


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


@app.get("/")
def root():
    return {"status": "ok"}


@app.post("/supplier-agent")
async def supplier_agent(request: Request):
    activity_json = await request.json()
    logging.info(activity_json)

    # Ignore non-message activities completely
    if activity_json.get("type") != "message":
        return {"status": "ok"}

    activity = BotActivity(**activity_json)
    activity_dict = activity.model_dump(by_alias=True)

    if not activity.text:
        return {"status": "ok"}

    conversation_id = activity_dict["conversation"]["id"]
    user_input = activity.text.strip()

    # INIT
    if conversation_id not in sessions:
        session = init_session()
        extracted = extract_supplier_payload(user_input)
        session = merge_session(session, extracted)

        missing = get_missing_fields(session)
        current_field = missing[0]

        sessions[conversation_id] = {
            "session": session,
            "current_field": current_field,
            "state": "COLLECTING"
        }

        send_activity(activity_dict, FIELD_QUESTIONS[current_field])
        return {"status": "ok"}

    state = sessions[conversation_id]
    session = state["session"]
    current_field = state["current_field"]
    mode = state["state"]

    if current_field:
        session[current_field] = user_input

    missing = get_missing_fields(session)

    if missing:
        next_field = missing[0]
        state["current_field"] = next_field
        send_activity(activity_dict, FIELD_QUESTIONS[next_field])
        return {"status": "ok"}

    summary = "\n".join(f"{f}: {session[f]}" for f in REQUIRED_FIELDS)
    state["state"] = "CONFIRM"

    send_activity(
        activity_dict,
        f"Please confirm supplier details:\n\n{summary}\n\nType yes / cancel"
    )

    return {"status": "ok"}
