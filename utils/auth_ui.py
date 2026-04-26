from flask import session
from flask_jwt_extended import decode_token

from app.extensions import db
from app.models import Usuario


# --- INTEGRACION CON AUTENTICACION ---
def get_current_user_from_api():
    # Obtiene el usuario autenticado validando el JWT localmente.
    token = session.get("access_token")
    if not token:
        return None

    try:
        claims = decode_token(token)
    except Exception:
        return None

    usuario_id = claims.get("sub")
    if not usuario_id:
        return None

    try:
        usuario_id = int(usuario_id)
    except (TypeError, ValueError):
        return None

    user: Usuario | None = db.session.get(Usuario, usuario_id)
    if not user or user.eliminado or not user.activo:
        return None

    return {
        "id": user.id,
        "nombre": user.nombre,
        "correo": user.correo,
        "telefono": user.telefono,
        "domicilio": user.domicilio,
        "rol": claims.get("rol"),
    }
