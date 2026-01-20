import base64

def get_basic_auth_header(username, password):
    auth_str = f"{username}:{password}"
    encoded = base64.b64encode(auth_str.encode()).decode()
    return f"Basic {encoded}"
