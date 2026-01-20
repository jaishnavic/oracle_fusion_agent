import requests
from requests.auth import HTTPBasicAuth
from config.fusion_settings import FUSION_BASE_URL, FUSION_USERNAME, FUSION_PASSWORD, SUPPLIER_ENDPOINT


def create_supplier(payload: dict):
    url = f"{FUSION_BASE_URL}{SUPPLIER_ENDPOINT}"

    response = requests.post(
        url,
        json=payload,
        auth=HTTPBasicAuth(FUSION_USERNAME, FUSION_PASSWORD),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        timeout=60
    )

    # 🔒 SAFE RESPONSE PARSING (Oracle-friendly)
    try:
        body = response.json()
    except ValueError:
        body = {}   # Oracle returns empty body on 201
    print("Fusion status:", response.status_code)
    print("Fusion response text:", response.text)


    return response.status_code, body