from google import genai
from google.genai.errors import ClientError
from config.fusion_settings import GEMINI_API_KEY
import json
import logging

client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
Extract Oracle Fusion Supplier fields from user input.
Output JSON only. Valid fields: Supplier, TaxOrganizationType, SupplierType, TaxpayerCountry, TaxpayerId, DUNSNumber.
"""

def extract_supplier_payload(user_input: str) -> dict:
    try:
        # Switching to 1.5 Flash for better free-tier availability
        response = client.models.generate_content(
            model="models/gemini-1.5-flash", 
            contents=f"{SYSTEM_PROMPT}\n\nUser input:\n{user_input}"
        )

        if not response or not response.text:
            return {}

        text = response.text.strip()
        if text.startswith("```"):
            text = text.strip("```").replace("json", "").strip()

        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}

    except ClientError as e:
        if "429" in str(e):
            logging.error(" Gemini Quota Exhausted (429). Falling back to manual extraction.")
        else:
            logging.error(f"Gemini API Error: {e}")
        return {} # Returns empty dict so app.py handles it manually
    except Exception:
        logging.exception("Unexpected error in AI extraction")
        return {}