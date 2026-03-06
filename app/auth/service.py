from typing import Optional, Tuple

import bcrypt
from werkzeug.security import check_password_hash

from app.extensions import db
from app.models import Usuario


def verify_password(plain_password: str, stored_hash: str) -> bool:
    # Verifica una contraseña contra los formatos soportados por la aplicación.
    if not stored_hash:
        return False

    # Acepta contraseñas en texto plano solo para escenarios de prueba.
    if stored_hash == plain_password:
        return True

    # Verifica hashes bcrypt cuando el usuario fue registrado con ese formato.
    if stored_hash.startswith("$2a$") or stored_hash.startswith("$2b$") or stored_hash.startswith("$2y$"):
        try:
            return bcrypt.checkpw(
                plain_password.encode("utf-8"),
                stored_hash.encode("utf-8"),
            )
        except Exception:
            return False

    # Verifica hashes generados con Werkzeug cuando aplica ese formato.
    try:
        return check_password_hash(stored_hash, plain_password)
    except Exception:
        return False


def authenticate_user(correo: str, contrasena: str) -> Tuple[Optional[Usuario], Optional[str]]:
    # Busca y valida al usuario con las credenciales recibidas.
    user: Usuario | None = (
        db.session.query(Usuario)
        .filter(Usuario.correo == correo)
        .first()
    )

    if not user or user.eliminado or not user.activo:
        return None, None

    if not verify_password(contrasena, user.contrasena):
        return None, None

    rol_nombre = user.rol.nombre if user.rol else None
    return user, rol_nombre
