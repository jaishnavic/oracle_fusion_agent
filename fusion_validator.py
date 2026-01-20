from config.fusion_settings import FUSION_ALLOWED_VALUES

def validate_against_fusion(payload):
    errors = []

    for field, allowed in FUSION_ALLOWED_VALUES.items():
        if payload.get(field) and payload[field] not in allowed:
            errors.append(
                f"{field} must be one of {allowed}. "
                f"Received: {payload.get(field)}"
            )

    if payload.get("DUNSNumber"):
        if not payload["DUNSNumber"].isdigit() or len(payload["DUNSNumber"]) != 9:
            errors.append("DUNSNumber must be exactly 9 digits")

    return errors
