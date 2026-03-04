from functools import wraps
from flask import jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt

# --- DECORADORES DE AUTORIZACION ---
def role_required(*allowed_roles: str):
    # Restringe una ruta a los roles permitidos definidos en el decorador.
    """
    Verifica que el JWT exista y que el claim 'rol' esté dentro de allowed_roles.
    Uso: @role_required("Administrador")
    """
    def decorator(fn):
        # Envuelve la función original para validar el rol antes de ejecutarla.
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # Comprueba el token y bloquea el acceso si el rol no coincide.
            verify_jwt_in_request()
            claims = get_jwt()
            rol = claims.get("rol")
            if rol not in allowed_roles:
                return jsonify({"message": "Acceso denegado (rol insuficiente)"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator
