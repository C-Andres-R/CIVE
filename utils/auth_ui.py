import json
import urllib.request
from flask import current_app, session


# --- INTEGRACION CON AUTENTICACION ---
def get_current_user_from_api():
    # Consulta la API interna para obtener los datos del usuario autenticado.
    token = session.get("access_token")
    if not token:
        return None

    api_base = current_app.config.get("API_BASE_URL", "http://127.0.0.1:5000")
    url = f"{api_base}/auth/me"

    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"}
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
