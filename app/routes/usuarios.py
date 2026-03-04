from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash
import re
from app.auth.password_policy import validate_password
from app.extensions import db
from app.models import Usuario, Rol, Mascota
from utils.auth_ui import get_current_user_from_api

usuarios_bp = Blueprint("usuarios", __name__)

# --- UTILIDADES DE ACCESO Y VALIDACION ---
LOGIN_GET_ENDPOINT = "pages.login_page"

def redirect_to_login():
    # Redirige al formulario de inicio de sesión.
    return redirect(url_for(LOGIN_GET_ENDPOINT))

def require_login_or_redirect():
    # Verifica que exista una sesión activa antes de continuar.
    if not session.get("access_token"):
        return redirect_to_login()
    return None

def require_admin_or_denied(me):
    # Permite el acceso solo a usuarios con rol de administrador.
    if (me.get("rol") or "").lower() != "administrador":
        return render_template("acceso_denegado.html", me=me)
    return None

def is_valid_email(email: str) -> bool:
    # Valida que el correo tenga un formato básico correcto.
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email or ""))


def is_valid_phone(phone: str) -> bool:
    # Valida que el telefono tenga un formato y longitud correctos.
    if not phone:
        return False
    if not re.match(r"^[0-9+\-()\s]{10,20}$", phone):
        return False
    digits = re.sub(r"\D", "", phone or "")
    return 10 <= len(digits) <= 15


def is_valid_cp(cp: str) -> bool:
    # Valida que el codigo postal tenga exactamente 5 digitos.
    if not cp:
        return True
    return bool(re.match(r"^\d{5}$", cp))


def full_name(nombres: str, apellido_paterno: str, apellido_materno: str) -> str:
    # Construye el nombre completo a partir de componentes atomicos.
    parts = [nombres.strip(), apellido_paterno.strip(), apellido_materno.strip()]
    return " ".join(part for part in parts if part)


def full_address(calle: str, numero: str, colonia: str, codigo_postal: str, estado: str, entidad: str) -> str:
    # Construye el domicilio legible para compatibilidad hacia atras.
    street = " ".join(part for part in [calle.strip(), numero.strip()] if part).strip()
    tail = []
    if colonia.strip():
        tail.append(colonia.strip())
    if codigo_postal.strip():
        tail.append(f"CP {codigo_postal.strip()}")
    if estado.strip():
        tail.append(estado.strip())
    if entidad.strip():
        tail.append(entidad.strip())
    if street and tail:
        return f"{street}, {', '.join(tail)}"
    if street:
        return street
    if tail:
        return ", ".join(tail)
    return ""


def user_form_data(form=None, user: Usuario | None = None):
    # Prepara datos de formulario de usuario para crear/editar sin perder capturas.
    form = form or {}
    user_nombres = (user.nombres if user else "") or ""
    user_apellido_paterno = (user.apellido_paterno if user else "") or ""
    user_apellido_materno = (user.apellido_materno if user else "") or ""
    if user and not user_nombres and user.nombre:
        parts = [p for p in (user.nombre or "").split() if p]
        if parts:
            user_nombres = parts[0]
        if len(parts) >= 2:
            user_apellido_paterno = parts[1]
        if len(parts) >= 3:
            user_apellido_materno = " ".join(parts[2:])
    return {
        "nombres": (form.get("nombres") if form else None) or user_nombres,
        "apellido_paterno": (form.get("apellido_paterno") if form else None) or user_apellido_paterno,
        "apellido_materno": (form.get("apellido_materno") if form else None) or user_apellido_materno,
        "calle": (form.get("calle") if form else None) or (user.calle if user else "") or "",
        "numero": (form.get("numero") if form else None) or (user.numero if user else "") or "",
        "colonia": (form.get("colonia") if form else None) or (user.colonia if user else "") or "",
        "codigo_postal": (form.get("codigo_postal") if form else None) or (user.codigo_postal if user else "") or "",
        "estado": (form.get("estado") if form else None) or (user.estado if user else "") or "",
        "entidad": (form.get("entidad") if form else None) or (user.entidad if user else "") or "",
        "correo": (form.get("correo") if form else None) or (user.correo if user else "") or "",
        "telefono": (form.get("telefono") if form else None) or (user.telefono if user else "") or "",
        "rol_id": (form.get("rol_id") if form else None) or (str(user.rol_id) if user and user.rol_id else ""),
        "activo": (form.get("activo") == "on") if form else bool(user.activo if user else True),
    }

def tab_for_role_name(role_name: str) -> str:
    # Convierte el nombre del rol en la pestaña usada por la interfaz.
    role = (role_name or "").strip().lower()
    if role == "veterinario":
        return "veterinarios"
    if role == "cliente":
        return "clientes"
    return "administradores"

# --- RUTAS DE USUARIOS ---
@usuarios_bp.get("/usuarios")
def usuarios_index():
    # Muestra el listado de usuarios agrupado por tipo de rol.
    # Verificamos la sesión antes de consultar cualquier dato.
    r = require_login_or_redirect()
    if r:
        return r

    # Cargamos al usuario autenticado desde la API interna.
    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return redirect_to_login()

    # Permitimos el acceso solo a administradores.
    denied = require_admin_or_denied(me)
    if denied:
        return denied

    # Identificamos la pestaña solicitada para mostrar solo ese tipo de usuario.
    tab = (request.args.get("rol") or "administradores").lower()
    tab_to_role_name = {
        "administradores": "administrador",
        "veterinarios": "veterinario",
        "clientes": "cliente",
    }
    role_name = tab_to_role_name.get(tab, "administrador")

    # Consultamos los usuarios del rol seleccionado y su cantidad de mascotas.
    usuarios_rows = (
        db.session.query(
            Usuario,
            Rol.nombre.label("rol_nombre"),
            func.count(Mascota.id).label("mascotas_count"),
        )
        .join(Rol, Usuario.rol_id == Rol.id)
        .outerjoin(Mascota, Mascota.dueno_id == Usuario.id)
        .filter(func.lower(Rol.nombre) == role_name.lower())
        .filter(Usuario.eliminado.is_(False))
        .group_by(Usuario.id, Rol.nombre)
        .order_by(Usuario.id.asc())
        .all()
    )

    return render_template(
        "dashboard_usuarios.html",
        me=me,
        active_tab=tab,
        usuarios_rows=usuarios_rows,
    )

@usuarios_bp.route("/usuarios/nuevo", methods=["GET", "POST"])
def usuarios_new():
    # Crea un nuevo usuario desde el formulario de administración.
    r = require_login_or_redirect()
    if r:
        return r

    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return redirect_to_login()

    denied = require_admin_or_denied(me)
    if denied:
        return denied

    roles = db.session.query(Rol).order_by(Rol.nombre.asc()).all()

    if request.method == "GET":
        form_data = user_form_data()
        return render_template("usuario_form.html", me=me, roles=roles, form_data=form_data, mode="create")

    # Leemos y validamos los datos enviados por el formulario.
    nombres = (request.form.get("nombres") or "").strip()
    apellido_paterno = (request.form.get("apellido_paterno") or "").strip()
    apellido_materno = (request.form.get("apellido_materno") or "").strip()
    calle = (request.form.get("calle") or "").strip()
    numero = (request.form.get("numero") or "").strip()
    colonia = (request.form.get("colonia") or "").strip()
    codigo_postal = (request.form.get("codigo_postal") or "").strip()
    estado = (request.form.get("estado") or "").strip()
    entidad = (request.form.get("entidad") or "").strip()
    correo = (request.form.get("correo") or "").strip().lower()
    contrasena = request.form.get("contrasena") or ""
    telefono = (request.form.get("telefono") or "").strip()
    rol_id_raw = request.form.get("rol_id") or ""
    activo = request.form.get("activo") == "on"

    nombre = full_name(nombres, apellido_paterno, apellido_materno)
    domicilio = full_address(calle, numero, colonia, codigo_postal, estado, entidad)
    form_data = user_form_data(request.form)

    errors = []

    if not nombres:
        errors.append("El nombre es obligatorio.")
    if not correo:
        errors.append("El correo es obligatorio.")
    elif not is_valid_email(correo):
        errors.append("El correo no tiene un formato válido.")
    if codigo_postal and not is_valid_cp(codigo_postal):
        errors.append("El C.P. debe tener exactamente 5 dígitos.")
    if not telefono:
        errors.append("El teléfono es obligatorio.")
    elif not is_valid_phone(telefono):
        errors.append("El teléfono debe tener un formato válido.")
    if not contrasena:
        errors.append("La contraseña es obligatoria.")
    if not rol_id_raw:
        errors.append("El rol es obligatorio.")
    if contrasena:
        errors.extend(validate_password(contrasena, correo=correo, nombre=nombre))

    rol = None
    if rol_id_raw:
        try:
            rol = db.session.get(Rol, int(rol_id_raw))
            if not rol:
                errors.append("El rol seleccionado no existe.")
        except ValueError:
            errors.append("Rol inválido.")

    if correo:
        correo_duplicado = (
            db.session.query(Usuario.id)
            .filter(func.lower(Usuario.correo) == correo.lower())
            .first()
        )
        if correo_duplicado:
            errors.append("Ya existe un usuario con ese correo.")

    if errors:
        for err in errors:
            flash(err, "error")
        return render_template("usuario_form.html", me=me, roles=roles, form_data=form_data, mode="create")

    nuevo = Usuario(
        nombres=nombres,
        apellido_paterno=apellido_paterno or None,
        apellido_materno=apellido_materno or None,
        nombre=nombre,
        correo=correo,
        contrasena=generate_password_hash(contrasena),
        calle=calle or None,
        numero=numero or None,
        colonia=colonia or None,
        codigo_postal=codigo_postal or None,
        estado=estado or None,
        entidad=entidad or None,
        domicilio=domicilio or None,
        telefono=telefono or None,
        rol_id=rol.id,
        activo=activo,
    )

    db.session.add(nuevo)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Ya existe un usuario con ese correo.", "error")
        return render_template("usuario_form.html", me=me, roles=roles, form_data=form_data, mode="create")

    flash("Usuario creado correctamente.", "success")
    return redirect(url_for("usuarios.usuarios_index", rol=tab_for_role_name(rol.nombre)))

@usuarios_bp.route("/usuarios/<int:user_id>/editar", methods=["GET", "POST"])
def usuarios_edit(user_id: int):
    # Actualiza los datos de un usuario existente.
    r = require_login_or_redirect()
    if r:
        return r

    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return redirect_to_login()

    denied = require_admin_or_denied(me)
    if denied:
        return denied

    user = db.session.get(Usuario, user_id)
    if not user or user.eliminado:
        return render_template("usuario_no_encontrado.html", user_id=user_id)

    roles = db.session.query(Rol).order_by(Rol.nombre.asc()).all()

    if request.method == "GET":
        form_data = user_form_data(user=user)
        return render_template(
            "usuario_form.html",
            me=me,
            roles=roles,
            form_data=form_data,
            mode="edit",
            user_id=user.id,
        )

    # Leemos y validamos los datos enviados por el formulario.
    nombres = (request.form.get("nombres") or "").strip()
    apellido_paterno = (request.form.get("apellido_paterno") or "").strip()
    apellido_materno = (request.form.get("apellido_materno") or "").strip()
    calle = (request.form.get("calle") or "").strip()
    numero = (request.form.get("numero") or "").strip()
    colonia = (request.form.get("colonia") or "").strip()
    codigo_postal = (request.form.get("codigo_postal") or "").strip()
    estado = (request.form.get("estado") or "").strip()
    entidad = (request.form.get("entidad") or "").strip()
    correo = (request.form.get("correo") or "").strip().lower()
    telefono = (request.form.get("telefono") or "").strip()
    rol_id_raw = (request.form.get("rol_id") or "").strip()
    contrasena_nueva = request.form.get("contrasena") or ""
    activo = request.form.get("activo") == "on"

    nombre = full_name(nombres, apellido_paterno, apellido_materno)
    domicilio = full_address(calle, numero, colonia, codigo_postal, estado, entidad)
    form_data = user_form_data(request.form)

    errors = []

    if not nombres:
        errors.append("El nombre es obligatorio.")
    if not correo:
        errors.append("El correo es obligatorio.")
    elif not is_valid_email(correo):
        errors.append("El correo no tiene un formato válido.")
    if codigo_postal and not is_valid_cp(codigo_postal):
        errors.append("El C.P. debe tener exactamente 5 dígitos.")
    if not telefono:
        errors.append("El teléfono es obligatorio.")
    elif not is_valid_phone(telefono):
        errors.append("El teléfono debe tener un formato válido.")
    if not rol_id_raw:
        errors.append("El rol es obligatorio.")

    rol = None
    if rol_id_raw:
        try:
            rol = db.session.get(Rol, int(rol_id_raw))
            if not rol:
                errors.append("El rol seleccionado no existe.")
        except ValueError:
            errors.append("Rol inválido.")

    # Evitamos que el administrador se desactive a sí mismo.
    try:
        me_id = int(me.get("id"))
    except (TypeError, ValueError):
        me_id = None

    if me_id == user.id and not activo:
        errors.append("No puedes desactivarte a ti mismo.")

    if correo:
        correo_duplicado = (
            db.session.query(Usuario.id)
            .filter(func.lower(Usuario.correo) == correo.lower())
            .filter(Usuario.id != user.id)
            .first()
        )
        if correo_duplicado:
            errors.append("Ya existe un usuario con ese correo.")

    if contrasena_nueva.strip():
        errors.extend(
            validate_password(
                contrasena_nueva.strip(),
                correo=correo,
                nombre=nombre,
            )
        )

    if errors:
        for err in errors:
            flash(err, "error")
        return render_template(
            "usuario_form.html",
            me=me,
            roles=roles,
            form_data=form_data,
            mode="edit",
            user_id=user.id,
        )

    user.nombre = nombre
    user.nombres = nombres
    user.apellido_paterno = apellido_paterno or None
    user.apellido_materno = apellido_materno or None
    user.correo = correo
    user.calle = calle or None
    user.numero = numero or None
    user.colonia = colonia or None
    user.codigo_postal = codigo_postal or None
    user.estado = estado or None
    user.entidad = entidad or None
    user.domicilio = domicilio or None
    user.telefono = telefono or None
    user.rol_id = rol.id
    user.activo = activo

    if contrasena_nueva.strip():
        user.contrasena = generate_password_hash(contrasena_nueva.strip())

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Ya existe un usuario con ese correo.", "error")
        return render_template(
            "usuario_form.html",
            me=me,
            roles=roles,
            form_data=form_data,
            mode="edit",
            user_id=user.id,
        )

    flash("Usuario actualizado correctamente.", "success")
    return redirect(url_for("usuarios.usuarios_index", rol=tab_for_role_name(rol.nombre)))

@usuarios_bp.get("/usuarios/<int:user_id>")
def usuarios_detail(user_id: int):
    # Muestra el detalle de un usuario específico.
    r = require_login_or_redirect()
    if r:
        return r

    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return redirect_to_login()

    denied = require_admin_or_denied(me)
    if denied:
        return denied

    row = (
        db.session.query(Usuario, Rol.nombre.label("rol_nombre"))
        .join(Rol, Usuario.rol_id == Rol.id)
        .filter(Usuario.id == user_id, Usuario.eliminado.is_(False))
        .first()
    )

    if not row:
        return render_template("usuario_no_encontrado.html", user_id=user_id)

    return render_template("usuario_detalle.html", user=row)

@usuarios_bp.post("/usuarios/<int:user_id>/toggle")
def usuarios_toggle(user_id: int):
    # Activa o desactiva un usuario desde el panel de administración.
    r = require_login_or_redirect()
    if r:
        return r

    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return redirect_to_login()

    denied = require_admin_or_denied(me)
    if denied:
        return denied

    tab = request.args.get("rol") or "administradores"
    user = db.session.get(Usuario, user_id)

    if not user or user.eliminado:
        flash("Usuario no encontrado.", "error")
        return redirect(url_for("usuarios.usuarios_index", rol=tab))

    try:
        me_id = int(me.get("id"))
    except (TypeError, ValueError):
        me_id = None

    if me_id == user.id:
        flash("No puedes desactivarte a ti mismo.", "error")
        return redirect(url_for("usuarios.usuarios_index", rol=tab))

    user.activo = not bool(user.activo)
    db.session.commit()

    return redirect(url_for("usuarios.usuarios_index", rol=tab))
