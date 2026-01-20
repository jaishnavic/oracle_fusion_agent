import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

FUSION_BASE_URL = os.getenv("FUSION_BASE_URL")
FUSION_USERNAME = os.getenv("FUSION_USERNAME")
FUSION_PASSWORD = os.getenv("FUSION_PASSWORD")

SUPPLIER_ENDPOINT = (
    "/fscmRestApi/resources/11.13.18.05/suppliers"
)

REQUIRED_FIELDS = [
    "Supplier",
    "TaxOrganizationType",
    "SupplierType",
    "BusinessRelationship",
    "TaxpayerCountry",
    "TaxpayerId",
    "DUNSNumber"
]

DEFAULT_VALUES = {
    "BusinessRelationship": "Prospective",
    "OneTimeSupplierFlag": False
}

FIELD_QUESTIONS = {
    "Supplier": "What is the supplier name?",
    "TaxOrganizationType": "What is the Tax Organization Type? (defaullt:Corporation)",
    "SupplierType": "What is the Supplier Type? (Default:Services)",
    "TaxpayerCountry": "Which country is the taxpayer based in? (Ex:United States)",
    "TaxpayerId": "Please provide the Taxpayer ID(xx-xxxxxxxx)",
    "DUNSNumber": "Please provide the 9-digit DUNS Number"
}

FUSION_ALLOWED_VALUES = {
    "TaxOrganizationType": ["Corporation"],
    "SupplierType": ["Services"],
    "BusinessRelationship": ["Prospective"],
    }
