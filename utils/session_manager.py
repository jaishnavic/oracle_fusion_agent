from config.fusion_settings import REQUIRED_FIELDS, DEFAULT_VALUES

def init_session():
    session = {field: None for field in REQUIRED_FIELDS}
    session.update(DEFAULT_VALUES)
    return session


def merge_session(session, extracted):
    for key, value in extracted.items():
        if value is not None:
            session[key] = value
    return session


def get_missing_fields(session):
    return [f for f in REQUIRED_FIELDS if not session.get(f)]
