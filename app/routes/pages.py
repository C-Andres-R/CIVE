from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session
from flask_jwt_extended import create_access_token

from app.auth.service import authenticate_user
from utils.auth_ui import get_current_user_from_api

pages_bp = Blueprint("pages", __name__)


def _safe_next_path(value: str | None):
    candidate = (value or "").strip()
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return ""

def requiere_inicio_sesion(view_func):
    # Protege una vista para que solo pueda abrirse con sesión iniciada.
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get ("access_token"):
            return redirect(url_for("pages.pagina_inicio_sesion"))
        return view_func(*args, **kwargs)
    return wrapper

@pages_bp.get("/")
@pages_bp.get("/login")
def pagina_inicio_sesion():
    next_path = _safe_next_path(request.args.get("next"))
    if session.get("access_token"):
        return redirect(next_path or url_for("pages.pagina_panel"))
    return render_template("login.html", datos_formulario={"correo": "", "next": next_path}, errores_campo={})

@pages_bp.post("/login")
def procesar_inicio_sesion():
    correo = (request.form.get("correo") or "").strip().lower()
    contrasena = request.form.get("contrasena") or ""
    next_path = _safe_next_path(request.form.get("next"))
    datos_formulario = {"correo": correo, "next": next_path}
    errores_campo = {}

    if not correo:
        errores_campo["correo"] = "Este campo no puede estar vacío."
    elif "@" not in correo or "." not in correo.split("@")[-1]:
        errores_campo["correo"] = "Por favor, verifica la información ingresada."

    if not contrasena:
        errores_campo["contrasena"] = "Este campo no puede estar vacío."

    if errores_campo:
        return render_template("login.html", datos_formulario=datos_formulario, errores_campo=errores_campo)

    user, rol_nombre = authenticate_user(correo, contrasena)
    if not user:
        errores_campo = {
            "correo": "Por favor, verifica la información ingresada.",
            "contrasena": "Por favor, verifica la información ingresada.",
        }
        return render_template("login.html", datos_formulario=datos_formulario, errores_campo=errores_campo)
    access_token = create_access_token(
        identity=str(user.id),
        additional_claims={"rol": rol_nombre}
    )
    session["access_token"] = access_token
    return redirect(next_path or url_for("pages.pagina_panel"))

@pages_bp.get("/dashboard")
@requiere_inicio_sesion
def pagina_panel():
    me = get_current_user_from_api()
    if not me:
        session.clear()
        return redirect(url_for("pages.pagina_inicio_sesion"))
    rol = (me.get("rol") or "").strip().lower()
    if rol == "cliente":
        return redirect(url_for("clientes.clientes_portal"))
    if rol == "veterinario":
        return redirect(url_for("citas.citas_lista"))
    return redirect(url_for("datos.datos_dashboard"))

@pages_bp.get("/logout")
@requiere_inicio_sesion
def pagina_cerrar_sesion():
    # Cierra la sesión actual y vuelve al login.
    session.clear()
    return redirect(url_for("pages.pagina_inicio_sesion"))
