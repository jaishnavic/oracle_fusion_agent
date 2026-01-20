from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import uuid

from gemini_agent import extract_supplier_payload
from utils.session_manager import init_session, merge_session, get_missing_fields
from fusion_validator import validate_against_fusion
from fusion_client import create_supplier
from config.fusion_settings import FIELD_QUESTIONS, REQUIRED_FIELDS

app = FastAPI()

# In-memory session store (CLI memory)
sessions = {}

# -------------------------------
# Request schema (fixes Swagger)
# -------------------------------
class SupplierAgentRequest(BaseModel):
    sessionId: Optional[str] = None
    message: str


@app.post("/supplier-agent")
def supplier_agent(payload: SupplierAgentRequest):
    session_id = payload.sessionId
    user_input = payload.message.strip()

    # -------------------------------
    # INIT SESSION (CLI START)
    # -------------------------------
    if not session_id or session_id not in sessions:
        session_id = str(uuid.uuid4())
        session = init_session()

        # Try extracting from first sentence
        extracted = extract_supplier_payload(user_input)
        session = merge_session(session, extracted)

        missing = get_missing_fields(session)
        current_field = missing[0] if missing else None

        sessions[session_id] = {
            "session": session,
            "current_field": current_field,
            "state": "COLLECTING"
        }

        if current_field:
            return {
                "sessionId": session_id,
                "reply": FIELD_QUESTIONS[current_field]
            }

    # -------------------------------
    # RESTORE SESSION
    # -------------------------------
    state = sessions[session_id]
    session = state["session"]
    current_field = state["current_field"]
    mode = state["state"]

    # -------------------------------
    # CONFIRMATION MODE
    # -------------------------------
    if mode == "CONFIRM":
        decision = user_input.lower()

        if decision == "yes":
            status, response = create_supplier(session)
            sessions.pop(session_id)

            if status == 201:
                return {
                    "reply": "Supplier created successfully",
                    "SupplierId": response.get("SupplierId"),
                    "SupplierNumber": response.get("SupplierNumber")
                }

            return {
                "reply": "Supplier creation failed",
                "error": response
            }

        elif decision == "edit":
            state["state"] = "EDIT"
            return {
                "sessionId": session_id,
                "reply": "Which field do you want to edit? (Enter number)"
            }

        elif decision == "cancel":
            sessions.pop(session_id)
            return {"reply": "Supplier creation cancelled."}

        return {
            "sessionId": session_id,
            "reply": "Invalid option. Please type yes, edit, or cancel."
        }

    # -------------------------------
    # EDIT MODE
    # -------------------------------
    if mode == "EDIT":
        field_index_map = {str(i + 1): f for i, f in enumerate(REQUIRED_FIELDS)}

        if user_input in field_index_map:
            current_field = field_index_map[user_input]
            state["current_field"] = current_field
            state["state"] = "COLLECTING"

            return {
                "sessionId": session_id,
                "reply": FIELD_QUESTIONS[current_field]
            }

        return {
            "sessionId": session_id,
            "reply": "Invalid choice. Enter a valid number."
        }

    # -------------------------------
    # COLLECTING MODE (CLI LOOP)
    # -------------------------------
    if current_field:
        if len(user_input.split()) > 3:
            extracted = extract_supplier_payload(user_input)
            session = merge_session(session, extracted)

            if not session.get(current_field):
                session[current_field] = user_input
        else:
            session[current_field] = user_input

    # Persist updates
    state["session"] = session
    state["current_field"] = None

    # -------------------------------
    # CHECK MISSING FIELDS
    # -------------------------------
    missing = get_missing_fields(session)

    if missing:
        next_field = missing[0]
        state["current_field"] = next_field

        return {
            "sessionId": session_id,
            "reply": FIELD_QUESTIONS[next_field]
        }

    # -------------------------------
    # FINAL VALIDATION
    # -------------------------------
    validation_errors = validate_against_fusion(session)
    if validation_errors:
        state["current_field"] = REQUIRED_FIELDS[0]

        return {
            "sessionId": session_id,
            "reply": (
                "Input validation failed:\n" +
                "\n".join(validation_errors) +
                f"\n\n{FIELD_QUESTIONS[REQUIRED_FIELDS[0]]}"
            )
        }

    # -------------------------------
    # CONFIRMATION SUMMARY
    # -------------------------------
    summary = []
    for idx, field in enumerate(REQUIRED_FIELDS, start=1):
        summary.append(f"{idx}. {field}: {session.get(field)}")

    state["state"] = "CONFIRM"

    return {
        "sessionId": session_id,
        "reply": (
            "Please review the supplier details:\n\n" +
            "\n".join(summary) +
            "\n\nConfirm? (yes / edit / cancel)"
        )
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8009, reload=True)