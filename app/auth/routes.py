from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt

from app.extensions import db
from app.models import Usuario
from app.auth.service import authenticate_user

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

# --- RUTAS DE AUTENTICACION ---
@auth_bp.post("/login")
def login():
    # Autentica al usuario y devuelve un token JWT si las credenciales son válidas.
    data = request.get_json(silent=True) or {}
    correo = (data.get("correo") or "").strip().lower()
    contrasena = data.get("contrasena") or ""

    if not correo or not contrasena:
        return jsonify({"message": "Correo y contrasena son requeridos"}), 400

    user, rol_nombre = authenticate_user(correo, contrasena)
    if not user:
        return jsonify({"message": "Credenciales inválidas"}), 401

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
