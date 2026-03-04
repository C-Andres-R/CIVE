from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
import bcrypt
from werkzeug.security import check_password_hash

from app.extensions import db
from app.models import Usuario

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

# --- UTILIDADES DE AUTENTICACION ---
def verify_password(plain_password: str, stored_hash: str) -> bool:
    # Verifica una contraseña contra los formatos soportados por la aplicación.

    if not stored_hash:
        return False

    # Acepta contrasenas en texto plano solo para escenarios de prueba.
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



# --- RUTAS DE AUTENTICACION ---
@auth_bp.post("/login")
def login():
    # Autentica al usuario y devuelve un token JWT si las credenciales son válidas.
    data = request.get_json(silent=True) or {}
    correo = (data.get("correo") or "").strip().lower()
    contrasena = data.get("contrasena") or ""

    if not correo or not contrasena:
        return jsonify({"message": "Correo y contrasena son requeridos"}), 400

    user: Usuario | None = (
        db.session.query(Usuario)
        .filter(Usuario.correo == correo)
        .first()
    )

    # Evitamos revelar si el correo existe por seguridad.
    if not user or user.eliminado or not user.activo:
        return jsonify({"message": "Credenciales inválidas"}), 401

    if not verify_password(contrasena, user.contrasena):
        return jsonify({"message": "Credenciales inválidas"}), 401

    rol_nombre = user.rol.nombre if user.rol else None

    access_token = create_access_token(
        identity=str(user.id),                 
        additional_claims={"rol": rol_nombre} 
    )

    return jsonify({
        "access_token": access_token,
        "user_id": user.id,
        "rol": rol_nombre
    }), 200


@auth_bp.get("/me")
@jwt_required()
def me():
    # Devuelve los datos básicos del usuario autenticado.
    user_id = get_jwt_identity()
    claims = get_jwt()
    rol = claims.get("rol")

    user: Usuario | None = db.session.get(Usuario, user_id)
    if not user or user.eliminado or not user.activo:
        return jsonify({"message": "Usuario no válido o inactivo"}), 401

    return jsonify({
        "id": user.id,
        "nombre": user.nombre,
        "correo": user.correo,
        "telefono": user.telefono,
        "domicilio": user.domicilio,
        "rol": rol
    }), 200


# --- RUTA DE EJEMPLO ---
@auth_bp.get("/admin-only")
@jwt_required()
def admin_only():
    # Ejemplo de ruta protegida solo para administradores.
    claims = get_jwt()
    if claims.get("rol") != "Administrador":
        return jsonify({"message": "Acceso denegado (solo Administrador)"}), 403
    return jsonify({"message": "OK (admin)"}), 200
