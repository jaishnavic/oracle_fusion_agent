def normalize_supplier_payload(payload: dict) -> dict:
    """
    Normalize LLM output to Oracle Fusion LOV-compliant values
    """

    FUSION_TAX_ORG_TYPE = {
        "corporation": "Corporation",
        "corp": "Corporation",
        "company": "Corporation"
    }

    FUSION_SUPPLIER_TYPE = {
        "services": "Services",
        "service": "Services",
        "provided services": "Services"
    }

    FUSION_COUNTRY = {
        "us": "United States",
        "usa": "United States",
        "united states": "United States"
    }

    def normalize(value, mapping):
        if not value:
            return None
        key = value.strip().lower()
        return mapping.get(key)

    # 🔒 FORCE Fusion-approved values
    payload["TaxOrganizationType"] = normalize(
        payload.get("TaxOrganizationType"),
        FUSION_TAX_ORG_TYPE
    )

    payload["SupplierType"] = normalize(
        payload.get("SupplierType"),
        FUSION_SUPPLIER_TYPE
    )

    payload["TaxpayerCountry"] = normalize(
        payload.get("TaxpayerCountry"),
        FUSION_COUNTRY
    )

    # Defaults
    payload["BusinessRelationship"] = "Prospective"
    payload["OneTimeSupplierFlag"] = False

    # Remove nulls (Fusion rejects null LOVs)
    cleaned = {k: v for k, v in payload.items() if v is not None}

    return cleaned
