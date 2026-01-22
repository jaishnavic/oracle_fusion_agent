import requests
from requests.auth import HTTPBasicAuth
from config.fusion_settings import FUSION_BASE_URL, FUSION_USERNAME, FUSION_PASSWORD, SUPPLIER_ENDPOINT
import logging


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

    logging.info("--- FUSION DEBUG START ---")
    logging.info(f"Status: {response.status_code}")

    try:
        body = response.json()
        logging.info(f"Raw Response: {body}")
    except ValueError:
        body = None
        logging.info(f"Raw Response Text: {response.text}")

    logging.info("--- FUSION DEBUG END ---")

    # 🔴 IMPORTANT: return TEXT if JSON is empty
    if not body:
        return response.status_code, response.text.strip()

    return response.status_code, body
