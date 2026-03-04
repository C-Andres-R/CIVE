from flask import Blueprint, jsonify
from app.models.usuario import Usuario

# --- RUTAS DE SALUD ---
health_bp = Blueprint("health", __name__)

@health_bp.route("/health/db", methods=["GET"])
def health_db():
    # Verifica que la aplicación pueda consultar la base de datos.
    usuarios = Usuario.query.limit(1).all()
    return jsonify({
        "status": "ok",
        "usuarios_encontrados": len(usuarios)
    })
