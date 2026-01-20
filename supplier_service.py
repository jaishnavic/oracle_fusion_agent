#the script that calls the fusion rest api
import requests
from config.fusion_settings import (
    FUSION_BASE_URL,
    SUPPLIER_ENDPOINT,
    FUSION_USERNAME,
    FUSION_PASSWORD
)
from utils.auth import get_basic_auth_header

def create_supplier(payload: dict):
    url = FUSION_BASE_URL + SUPPLIER_ENDPOINT

    headers = {
        "Authorization": get_basic_auth_header(
            FUSION_USERNAME, FUSION_PASSWORD
        ),
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code == 201:
        data = response.json()
        return {
            "status": "SUCCESS",
            "supplierId": data.get("SupplierId"),
            "supplierNumber": data.get("SupplierNumber")
        }

    return {
        "status": "FAILED",
        "httpStatus": response.status_code,
        "error": response.text
    }
