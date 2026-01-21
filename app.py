from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
import requests
import time
 
from gemini_agent import extract_supplier_payload
from utils.session_manager import init_session, merge_session, get_missing_fields
from fusion_validator import validate_against_fusion
from fusion_client import create_supplier
from config.fusion_settings import FIELD_QUESTIONS, REQUIRED_FIELDS
 
app = FastAPI()
 
# -------------------------------
# In-memory session store
# -------------------------------
sessions = {}
 
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
# Azure Bot helpers
# -------------------------------
def send_activity(activity: dict, message_text: str):
    """Send a message to Teams / Web Chat using Bot Framework."""
    if not activity.get("serviceUrl") or not activity.get("conversation"):
        return
 
    service_url = activity["serviceUrl"]
    conversation_id = activity["conversation"]["id"]
 
    url = f"{service_url}/v3/conversations/{conversation_id}/activities"
 
    payload = {
        "type": "message",
        "from": activity.get("recipient", {}),
        "recipient": activity.get("from", {}),
        "conversation": activity.get("conversation", {}),
        "replyToId": activity.get("id"),
        "channelId": activity.get("channelId"),
        "text": message_text,
        "timestamp": datetime.utcnow().isoformat()
    }
 
    try:
        # Simulate typing indicator before sending
        typing_payload = payload.copy()
        typing_payload["type"] = "typing"
        requests.post(url, json=typing_payload)
        time.sleep(0.5)  # small delay for UX
 
        # Send actual message
        requests.post(url, json=payload)
    except Exception as e:
        print("Error sending activity:", e)

def bot_activity_response(text: str, activity: Dict[str, Any], actions: list = None):
    """
    Construct a proper bot activity response, with optional suggested action buttons.
    """
    msg = {
        "type": "message",
        "from": activity.get("recipient", {}),
        "recipient": activity.get("from", {}),
        "conversation": activity.get("conversation", {}),
        "replyToId": activity.get("id"),
        "serviceUrl": activity.get("serviceUrl"),
        "channelId": activity.get("channelId"),
        "timestamp": datetime.utcnow().isoformat(),
        "text": text
    }
    if actions:
        msg["suggestedActions"] = {
            "actions": [{"type": "imBack", "title": a, "value": a} for a in actions]
        }
    return msg
 
# -------------------------------
# Health Endpoints
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
 
    # Only process messages
    if activity.type != "message" or not activity.text:
        return []
 
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
            question = FIELD_QUESTIONS.get(current_field, f"Please provide {current_field.replace('_',' ')}")
            return [bot_activity_response(question, activity_dict)]
 
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
                return [bot_activity_response(
                    f"✅ Supplier created successfully\nSupplierId: {response.get('SupplierId')}\nSupplierNumber: {response.get('SupplierNumber')}",
                    activity_dict
                )]
            return [bot_activity_response("❌ Supplier creation failed", activity_dict)]
 
        if decision == "edit":
            state["state"] = "EDIT"
            return [bot_activity_response(
                "Which field do you want to edit? (Enter number)",
                activity_dict,
                actions=[str(i+1) for i in range(len(REQUIRED_FIELDS))]
            )]
 
        if decision == "cancel":
            sessions.pop(conversation_id, None)
            return [bot_activity_response("Supplier creation cancelled.", activity_dict)]
 
        return [bot_activity_response("Please type: yes, edit, or cancel.", activity_dict,
                                      actions=["yes","edit","cancel"])]
 
    # -------------------------------
    # EDIT MODE
    # -------------------------------
    if mode == "EDIT":
        field_index_map = {str(i+1): f for i, f in enumerate(REQUIRED_FIELDS)}
        if user_input in field_index_map:
            field = field_index_map[user_input]
            state["current_field"] = field
            state["state"] = "COLLECTING"
            return [bot_activity_response(FIELD_QUESTIONS[field], activity_dict)]
        return [bot_activity_response("Invalid number. Try again.", activity_dict,
                                      actions=[str(i+1) for i in range(len(REQUIRED_FIELDS))])]
 
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
        question = FIELD_QUESTIONS.get(next_field, f"Please provide {next_field.replace('_',' ')}")
        return [bot_activity_response(question, activity_dict)]
 
    # -------------------------------
    # FINAL VALIDATION
    # -------------------------------
    errors = validate_against_fusion(session)
    if errors:
        state["current_field"] = REQUIRED_FIELDS[0]
        return [bot_activity_response("Validation failed:\n" + "\n".join(errors), activity_dict)]
 
    # -------------------------------
    # CONFIRM SUMMARY
    # -------------------------------
    summary = "\n".join(f"{i+1}. {f}: {session[f]}" for i, f in enumerate(REQUIRED_FIELDS))
    state["state"] = "CONFIRM"
    return [bot_activity_response(
        f"Please review the supplier details:\n\n{summary}\n\nConfirm?",
        activity_dict,
        actions=["yes","edit","cancel"]
    )]