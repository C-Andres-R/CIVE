"""Módulo de usuarios."""

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

LOGIN_GET_ENDPOINT = "pages.pagina_inicio_sesion"

def redirigir_a_inicio_sesion():
    """Función para redirigir a inicio sesion."""
    return redirect(url_for(LOGIN_GET_ENDPOINT))

def requiere_inicio_sesion_o_redirige():
    """Función para requiere inicio sesion o redirige."""
    if not session.get("access_token"):
        return redirigir_a_inicio_sesion()
    return None

def requiere_administrador_o_deniega(me):
    """Función para requiere administrador o deniega."""
    if (me.get("rol") or "").lower() != "administrador":
        return render_template("acceso_denegado.html", me=me)
    return None

def es_correo_valido(correo: str) -> bool:
    """Función para es correo valido."""
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", correo or ""))


def es_telefono_valido(phone: str) -> bool:
    """Función para es telefono valido."""
    if not phone:
        return False
    if not re.match(r"^[0-9+\-()\s]{10,20}$", phone):
        return False
    digits = re.sub(r"\D", "", phone or "")
    return 10 <= len(digits) <= 15


def es_cp_valido(cp: str) -> bool:
    """Función para es cp valido."""
    if not cp:
        return True
    return bool(re.match(r"^\d{5}$", cp))


def es_nombre_persona_valido(value: str) -> bool:
    """Función para es nombre persona valido."""
    if not value:
        return False
    return bool(re.match(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+$", value))


def nombre_completo(nombres: str, apellido_paterno: str, apellido_materno: str) -> str:
    """Función para nombre completo."""
    parts = [nombres.strip(), apellido_paterno.strip(), apellido_materno.strip()]
    return " ".join(part for part in parts if part)


def direccion_completa(calle: str, numero: str, colonia: str, codigo_postal: str, estado: str, entidad: str) -> str:
    """Función para direccion completa."""
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


def datos_formulario_usuario(form=None, user: Usuario | None = None):
    """Función para datos formulario usuario."""
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


def validar_formulario_usuario(
    *,
    nombres: str,
    apellido_paterno: str,
    apellido_materno: str,
    codigo_postal: str,
    correo: str,
    telefono: str,
    contrasena: str,
    rol_id_raw: str,
    activo: bool,
    nombre_completo: str,
    current_usuario_id: int | None = None,
    editing_usuario_id: int | None = None,
):
    """Función para validar formulario usuario."""
    errores_campo = {}
    rol = None

    if not nombres:
        errores_campo["nombres"] = "El nombre es obligatorio."
    elif not es_nombre_persona_valido(nombres):
        errores_campo["nombres"] = "El campo no puede contener números."

    if not apellido_paterno:
        errores_campo["apellido_paterno"] = "Este campo no puede estar vacío."
    elif not es_nombre_persona_valido(apellido_paterno):
        errores_campo["apellido_paterno"] = "El campo no puede contener números."

    if not apellido_materno:
        errores_campo["apellido_materno"] = "Este campo no puede estar vacío."
    elif not es_nombre_persona_valido(apellido_materno):
        errores_campo["apellido_materno"] = "El campo no puede contener números."

    if not correo:
        errores_campo["correo"] = "El correo es obligatorio."
    elif not es_correo_valido(correo):
        errores_campo["correo"] = "El correo no tiene un formato válido."

    if codigo_postal and not es_cp_valido(codigo_postal):
        errores_campo["codigo_postal"] = "El C.P. debe tener exactamente 5 dígitos."

    if not telefono:
        errores_campo["telefono"] = "El teléfono es obligatorio."
    elif not es_telefono_valido(telefono):
        errores_campo["telefono"] = "El teléfono debe tener un formato válido."

    if editing_usuario_id is None and not contrasena:
        errores_campo["contrasena"] = "La contraseña es obligatoria."
    elif contrasena:
        password_errors = validate_password(contrasena, correo=correo, nombre=nombre_completo)
        if password_errors:
            errores_campo["contrasena"] = " ".join(password_errors)

    if not rol_id_raw:
        errores_campo["rol_id"] = "El rol es obligatorio."
    else:
        try:
            rol = db.session.get(Rol, int(rol_id_raw))
            if not rol:
                errores_campo["rol_id"] = "El rol seleccionado no existe."
        except ValueError:
            errores_campo["rol_id"] = "Rol inválido."

    if current_usuario_id is not None and editing_usuario_id is not None and current_usuario_id == editing_usuario_id and not activo:
        errores_campo["activo"] = "No puedes desactivarte a ti mismo."

    if correo:
        correo_duplicado_query = db.session.query(Usuario.id).filter(func.lower(Usuario.correo) == correo.lower())
        if editing_usuario_id is not None:
            correo_duplicado_query = correo_duplicado_query.filter(Usuario.id != editing_usuario_id)
        correo_duplicado = correo_duplicado_query.first()
        if correo_duplicado:
            errores_campo["correo"] = "Ya existe un usuario con ese correo."

    return errores_campo, rol

def pestana_para_nombre_rol(role_name: str) -> str:
    """Función para pestana para nombre rol."""
    role = (role_name or "").strip().lower()
    if role == "veterinario":
        return "veterinarios"
    if role == "cliente":
        return "clientes"
    return "administradores"

@usuarios_bp.get("/usuarios")
def usuarios_lista():
    """Función para usuarios lista."""
    # Verificamos la sesión antes de consultar cualquier dato.
    r = requiere_inicio_sesion_o_redirige()
    if r:
        return r
    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return redirigir_a_inicio_sesion()

    # Permitimos el acceso solo a administradores.
    denied = requiere_administrador_o_deniega(me)
    if denied:
        return denied

    # Identificamos la pestaña solicitada para mostrar solo ese tipo de usuario.
    tab = (request.args.get("rol") or "administradores").lower()
    tab_to_nombre_rol = {
        "administradores": "administrador",
        "veterinarios": "veterinario",
        "clientes": "cliente",
    }
    role_name = tab_to_nombre_rol.get(tab, "administrador")
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
def usuarios_nuevo():
    """Función para usuarios nuevo."""
    # Crea un nuevo usuario desde el formulario de administración.
    r = requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return redirigir_a_inicio_sesion()

    denied = requiere_administrador_o_deniega(me)
    if denied:
        return denied

    roles = db.session.query(Rol).order_by(Rol.nombre.asc()).all()

    if request.method == "GET":
        datos_formulario = datos_formulario_usuario()
        return render_template(
            "usuario_form.html",
            me=me,
            roles=roles,
            datos_formulario=datos_formulario,
            errores_campo={},
            mode="create",
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
    contrasena = request.form.get("contrasena") or ""
    telefono = (request.form.get("telefono") or "").strip()
    rol_id_raw = request.form.get("rol_id") or ""
    activo = request.form.get("activo") == "on"

    nombre = nombre_completo(nombres, apellido_paterno, apellido_materno)
    domicilio = direccion_completa(calle, numero, colonia, codigo_postal, estado, entidad)
    datos_formulario = datos_formulario_usuario(request.form)

    errores_campo, rol = validar_formulario_usuario(
        nombres=nombres,
        apellido_paterno=apellido_paterno,
        apellido_materno=apellido_materno,
        codigo_postal=codigo_postal,
        correo=correo,
        telefono=telefono,
        contrasena=contrasena,
        rol_id_raw=rol_id_raw,
        activo=activo,
        nombre_completo=nombre,
    )

    if errores_campo:
        return render_template(
            "usuario_form.html",
            me=me,
            roles=roles,
            datos_formulario=datos_formulario,
            errores_campo=errores_campo,
            mode="create",
        )

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
        return render_template(
            "usuario_form.html",
            me=me,
            roles=roles,
            datos_formulario=datos_formulario,
            errores_campo={"correo": "Ya existe un usuario con ese correo."},
            mode="create",
        )

    flash("Usuario creado correctamente.", "success")
    return redirect(url_for("usuarios.usuarios_lista", rol=pestana_para_nombre_rol(rol.nombre)))

@usuarios_bp.route("/usuarios/<int:usuario_id>/editar", methods=["GET", "POST"])
def usuarios_editar(usuario_id: int):
    """Función para usuarios editar."""
    r = requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return redirigir_a_inicio_sesion()

    denied = requiere_administrador_o_deniega(me)
    if denied:
        return denied

    user = db.session.get(Usuario, usuario_id)
    if not user or user.eliminado:
        return render_template("usuario_no_encontrado.html", usuario_id=usuario_id)

    roles = db.session.query(Rol).order_by(Rol.nombre.asc()).all()

    if request.method == "GET":
        datos_formulario = datos_formulario_usuario(user=user)
        return render_template(
            "usuario_form.html",
            me=me,
            roles=roles,
            datos_formulario=datos_formulario,
            errores_campo={},
            mode="edit",
            usuario_id=user.id,
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

    nombre = nombre_completo(nombres, apellido_paterno, apellido_materno)
    domicilio = direccion_completa(calle, numero, colonia, codigo_postal, estado, entidad)
    datos_formulario = datos_formulario_usuario(request.form)

    # Evitamos que el administrador se desactive a sí mismo.
    try:
        me_id = int(me.get("id"))
    except (TypeError, ValueError):
        me_id = None

    errores_campo, rol = validar_formulario_usuario(
        nombres=nombres,
        apellido_paterno=apellido_paterno,
        apellido_materno=apellido_materno,
        codigo_postal=codigo_postal,
        correo=correo,
        telefono=telefono,
        contrasena=contrasena_nueva.strip(),
        rol_id_raw=rol_id_raw,
        activo=activo,
        nombre_completo=nombre,
        current_usuario_id=me_id,
        editing_usuario_id=user.id,
    )

    if errores_campo:
        return render_template(
            "usuario_form.html",
            me=me,
            roles=roles,
            datos_formulario=datos_formulario,
            errores_campo=errores_campo,
            mode="edit",
            usuario_id=user.id,
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
        return render_template(
            "usuario_form.html",
            me=me,
            roles=roles,
            datos_formulario=datos_formulario,
            errores_campo={"correo": "Ya existe un usuario con ese correo."},
            mode="edit",
            usuario_id=user.id,
        )

    flash("Usuario actualizado correctamente.", "success")
    return redirect(url_for("usuarios.usuarios_lista", rol=pestana_para_nombre_rol(rol.nombre)))

@usuarios_bp.get("/usuarios/<int:usuario_id>")
def usuarios_detalle(usuario_id: int):
    """Función para usuarios detalle."""
    r = requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return redirigir_a_inicio_sesion()

    denied = requiere_administrador_o_deniega(me)
    if denied:
        return denied

    row = (
        db.session.query(Usuario, Rol.nombre.label("rol_nombre"))
        .join(Rol, Usuario.rol_id == Rol.id)
        .filter(Usuario.id == usuario_id, Usuario.eliminado.is_(False))
        .first()
    )

    if not row:
        return render_template("usuario_no_encontrado.html", usuario_id=usuario_id)

    return render_template("usuario_detalle.html", user=row)

@usuarios_bp.post("/usuarios/<int:usuario_id>/toggle")
def usuarios_alternar(usuario_id: int):
    """Función para usuarios alternar."""
    # Activa o desactiva un usuario desde el panel de administración.
    r = requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return redirigir_a_inicio_sesion()

    denied = requiere_administrador_o_deniega(me)
    if denied:
        return denied

    tab = request.args.get("rol") or "administradores"
    user = db.session.get(Usuario, usuario_id)

    if not user or user.eliminado:
        flash("Usuario no encontrado.", "error")
        return redirect(url_for("usuarios.usuarios_lista", rol=tab))

    try:
        me_id = int(me.get("id"))
    except (TypeError, ValueError):
        me_id = None

    if me_id == user.id:
        flash("No puedes desactivarte a ti mismo.", "error")
        return redirect(url_for("usuarios.usuarios_lista", rol=tab))

    user.activo = not bool(user.activo)
    db.session.commit()

    return redirect(url_for("usuarios.usuarios_lista", rol=tab))
