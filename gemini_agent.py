from google import genai
from config.fusion_settings import GEMINI_API_KEY
import json

client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
Extract Oracle Fusion Supplier fields from user input.

Rules:
- Extract ONLY fields explicitly mentioned
- Do NOT guess values
- Do NOT normalize
- Output JSON only
- Missing fields must be omitted

Valid fields:
Supplier
TaxOrganizationType
SupplierType
TaxpayerCountry
TaxpayerId
DUNSNumber
"""

def extract_supplier_payload(user_input: str) -> dict:
    response = client.models.generate_content(
        model="models/gemini-2.5-flash",
        contents=f"{SYSTEM_PROMPT}\n\nUser input:\n{user_input}"
    )

    text = response.text.strip()

    # 🔒 Strip markdown if present
    if text.startswith("```"):
        text = text.strip("```").replace("json", "").strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    return {}
