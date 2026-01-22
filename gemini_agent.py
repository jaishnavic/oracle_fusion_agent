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

import json
import logging
from google.genai.errors import ClientError

def extract_supplier_payload(user_input: str) -> dict:
    try:
        response = client.models.generate_content(
            model="models/gemini-2.5-flash",
            contents=f"{SYSTEM_PROMPT}\n\nUser input:\n{user_input}"
        )

        if not response or not response.text:
            return {}

        text = response.text.strip()

        # 🔒 Strip markdown if present
        if text.startswith("```"):
            text = text.strip("```").replace("json", "").strip()

        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed

    except ClientError as e:
        # 🔥 Gemini quota / rate-limit / auth errors
        logging.error("Gemini API error (quota / auth / rate limit)")
        logging.error(str(e))

    except json.JSONDecodeError:
        logging.warning("Gemini returned non-JSON response")

    except Exception as e:
        logging.exception("Unexpected error in extract_supplier_payload")

    # ✅ SAFE FALLBACK
    return {}
