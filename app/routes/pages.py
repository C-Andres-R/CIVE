from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session
from flask_jwt_extended import create_access_token

from app.auth.service import authenticate_user
from utils.auth_ui import get_current_user_from_api

pages_bp = Blueprint("pages", __name__)

# --- UTILIDADES DE SESION ---
def login_required(view_func):
    # Protege una vista para que solo pueda abrirse con sesión iniciada.
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        # Verifica que exista un token guardado en la sesión actual.
        if not session.get ("access_token"):
            return redirect(url_for("pages.login_page"))
        return view_func(*args, **kwargs)
    return wrapper

# --- RUTAS DE PAGINAS ---
@pages_bp.get("/")
@pages_bp.get("/login")
def login_page():
    # Muestra la pantalla de inicio de sesión.
    if session.get("access_token"):
        return redirect(url_for("pages.dashboard_page"))
    return render_template("login.html", form_data={"correo": ""}, field_errors={})

@pages_bp.post("/login")
def login_post():
    # Valida credenciales y guarda el JWT en la sesión.
    correo = (request.form.get("correo") or "").strip().lower()
    contrasena = request.form.get("contrasena") or ""
    form_data = {"correo": correo}
    field_errors = {}

    if not correo:
        field_errors["correo"] = "Este campo no puede estar vacío."
    elif "@" not in correo or "." not in correo.split("@")[-1]:
        field_errors["correo"] = "Por favor, verifica la información ingresada."

    if not contrasena:
        field_errors["contrasena"] = "Este campo no puede estar vacío."

    if field_errors:
        return render_template("login.html", form_data=form_data, field_errors=field_errors)

    user, rol_nombre = authenticate_user(correo, contrasena)
    if not user:
        field_errors = {
            "correo": "Por favor, verifica la información ingresada.",
            "contrasena": "Por favor, verifica la información ingresada.",
        }
        return render_template("login.html", form_data=form_data, field_errors=field_errors)

    # Guardamos el token en la sesion para las siguientes vistas.
    access_token = create_access_token(
        identity=str(user.id),
        additional_claims={"rol": rol_nombre}
    )
    session["access_token"] = access_token
    return redirect(url_for("pages.dashboard_page"))

@pages_bp.get("/dashboard")
@login_required
def dashboard_page():
    # Redirige al panel principal según el rol del usuario.
    me = get_current_user_from_api()
    if not me:
        session.clear()
        return redirect(url_for("pages.login_page"))
    if (me.get("rol") or "").strip().lower() == "cliente":
        return redirect(url_for("clientes.clientes_portal"))
    return redirect(url_for("usuarios.usuarios_index"))

@pages_bp.get("/logout")
@login_required
def logout_page():
    # Cierra la sesión actual y vuelve al login.
    session.clear()
    return redirect(url_for("pages.login_page"))
