from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import uuid
from fastapi import Request
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
# Teams-compatible response helper
# -------------------------------
from datetime import datetime
 
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

 
from typing import Dict, Any
 
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
# Request schema
# -------------------------------
class SupplierAgentRequest(BaseModel):
    sessionId: Optional[str] = None
    message: str


# -------------------------------
# Health / Root
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

@app.post("/supplier-agent")
async def supplier_agent(request: Request):

    raw_body = await request.json()
    print("===== AZURE RAW PAYLOAD =====")
    print(raw_body)
    print("============================")

    # Now safely parse into BotActivity
    activity = BotActivity(**raw_body)

    # Ignore non-message activities (typing, conversationUpdate, etc.)

    if activity.type != "message":
        return {}
    if not activity.dict(by_alias=True).get("from") or not activity.dict(by_alias=True).get("recipient"):
        return {}

    conversation_id = activity.conversation["id"]
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

            return bot_activity_response(

                FIELD_QUESTIONS[current_field],

                activity.dict(by_alias=True)

            )
 
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

                return bot_activity_response(

                    f"✅ Supplier created successfully\n"

                    f"SupplierId: {response.get('SupplierId')}\n"

                    f"SupplierNumber: {response.get('SupplierNumber')}",

                    activity.dict(by_alias=True)

                )
 
            return bot_activity_response(

                "❌ Supplier creation failed",

                activity.dict(by_alias=True)

            )
 
        if decision == "edit":

            state["state"] = "EDIT"

            return bot_activity_response(

                "Which field do you want to edit? (Enter number)",

                activity.dict(by_alias=True)

            )
 
        if decision == "cancel":

            sessions.pop(conversation_id, None)

            return bot_activity_response(

                "Supplier creation cancelled.",

                activity.dict(by_alias=True)

            )
 
        return bot_activity_response(

            "Please type: yes, edit, or cancel.",

            activity.dict(by_alias=True)

        )
 
    # -------------------------------

    # EDIT MODE

    # -------------------------------

    if mode == "EDIT":

        field_index_map = {str(i + 1): f for i, f in enumerate(REQUIRED_FIELDS)}
 
        if user_input in field_index_map:

            field = field_index_map[user_input]

            state["current_field"] = field

            state["state"] = "COLLECTING"
 
            return bot_activity_response(

                FIELD_QUESTIONS[field],

                activity.dict(by_alias=True)

            )
 
        return bot_activity_response(

            "Invalid number. Try again.",

            activity.dict(by_alias=True)

        )
 
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
 
        return bot_activity_response(

            FIELD_QUESTIONS[next_field],

            activity.dict(by_alias=True)

        )
 
    # -------------------------------

    # FINAL VALIDATION

    # -------------------------------

    errors = validate_against_fusion(session)

    if errors:

        state["current_field"] = REQUIRED_FIELDS[0]

        return bot_activity_response(

            "Validation failed:\n" + "\n".join(errors),

            activity.dict(by_alias=True)

        )
 
    # -------------------------------

    # CONFIRM SUMMARY

    # -------------------------------

    summary = "\n".join(

        f"{i+1}. {f}: {session[f]}" for i, f in enumerate(REQUIRED_FIELDS)

    )
 
    state["state"] = "CONFIRM"
 
    return bot_activity_response(

        "Please review:\n\n" + summary + "\n\nConfirm? (yes / edit / cancel)",

        activity.dict(by_alias=True)

    )
 