from __future__ import annotations

import re
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.auth.password_policy import validate_password
from app.extensions import db
from app.models import Cita, Facturacion, Mascota, Rol, Usuario
from utils.auth_ui import get_current_user_from_api

clientes_bp = Blueprint("clientes", __name__)

# --- CONFIGURACION DE CLIENTES ---
LOGIN_GET_ENDPOINT = "pages.login_page"

ROLE_ADMIN = "administrador"
ROLE_CLIENTE = "cliente"
ROLE_VETERINARIO = "veterinario"

PERMISSIONS = {
    "hu018": {ROLE_ADMIN},
    "hu019": {ROLE_ADMIN},
    "hu020": {ROLE_ADMIN},
    "hu021": {ROLE_ADMIN},
    "hu022": {ROLE_ADMIN, ROLE_CLIENTE, ROLE_VETERINARIO},
    "hu023": {ROLE_ADMIN, ROLE_CLIENTE},
    "hu024": {ROLE_CLIENTE},
}

PHONE_PATTERN = re.compile(r"^[0-9+\-()\s]{10,20}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CP_PATTERN = re.compile(r"^\d{5}$")


# --- UTILIDADES DE ACCESO Y VALIDACION ---
def _redirect_to_login():
    # Redirige al formulario de inicio de sesión.
    return redirect(url_for(LOGIN_GET_ENDPOINT))


def _require_login_or_redirect():
    # Verifica que exista una sesión activa antes de continuar.
    if not session.get("access_token"):
        return _redirect_to_login()
    return None


def _get_me_or_logout():
    # Obtiene al usuario autenticado y limpia la sesión si ya no es válida.
    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return None
    return me


def _role_name(me) -> str:
    # Obtiene el nombre del rol actual en formato uniforme.
    return (me.get("rol") or "").strip().lower()


def _allowed(me, hu_code: str) -> bool:
    # Indica si el rol actual puede usar la historia de usuario solicitada.
    return _role_name(me) in PERMISSIONS.get(hu_code, set())


def _parse_int(value):
    # Convierte un valor a entero y regresa None si no es válido.
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_valid_email(email: str) -> bool:
    # Valida que el correo tenga un formato aceptable.
    return bool(EMAIL_PATTERN.match(email or ""))


def _is_valid_phone(phone: str) -> bool:
    # Valida que el teléfono tenga un formato y longitud correctos.
    if not PHONE_PATTERN.match(phone or ""):
        return False
    digits = re.sub(r"\D", "", phone or "")
    return 10 <= len(digits) <= 15


def _full_name(nombres: str, apellido_paterno: str, apellido_materno: str) -> str:
    # Normaliza el nombre completo a partir de sus componentes.
    parts = [nombres.strip(), apellido_paterno.strip(), apellido_materno.strip()]
    return " ".join(part for part in parts if part)


def _full_address(calle: str, numero: str, colonia: str, codigo_postal: str, estado: str, entidad: str) -> str:
    # Construye una representación legible del domicilio para compatibilidad.
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


def _get_client_role():
    # Busca el rol de cliente en la base de datos.
    return (
        db.session.query(Rol)
        .filter(func.lower(Rol.nombre) == ROLE_CLIENTE)
        .first()
    )


def _get_client(client_id: int) -> Usuario | None:
    # Obtiene un usuario que pertenezca al rol de cliente.
    return (
        db.session.query(Usuario)
        .join(Rol, Usuario.rol_id == Rol.id)
        .filter(Usuario.id == client_id)
        .filter(func.lower(Rol.nombre) == ROLE_CLIENTE)
        .first()
    )


def _client_exists_for_access(client_id: int) -> Usuario | None:
    # Verifica que el cliente exista y no esté marcado como eliminado.
    client = _get_client(client_id)
    if not client or client.eliminado:
        return None
    return client


def _can_access_client_resource(me, client_id: int, hu_code: str) -> bool:
    # Revisa si el usuario actual puede consultar recursos de un cliente.
    if not _allowed(me, hu_code):
        return False
    role = _role_name(me)
    if role == ROLE_CLIENTE:
        return _parse_int(me.get("id")) == client_id
    return True


def _client_form_data(form=None, client: Usuario | None = None):
    # Prepara los datos del formulario de cliente para mostrar o reutilizar.
    form = form or {}
    client_nombres = (client.nombres if client else "") or ""
    client_apellido_paterno = (client.apellido_paterno if client else "") or ""
    client_apellido_materno = (client.apellido_materno if client else "") or ""
    if client and not client_nombres and client.nombre:
        parts = [p for p in (client.nombre or "").split() if p]
        if parts:
            client_nombres = parts[0]
        if len(parts) >= 2:
            client_apellido_paterno = parts[1]
        if len(parts) >= 3:
            client_apellido_materno = " ".join(parts[2:])

    return {
        "nombres": (form.get("nombres") if form else None) or client_nombres,
        "apellido_paterno": (form.get("apellido_paterno") if form else None) or client_apellido_paterno,
        "apellido_materno": (form.get("apellido_materno") if form else None) or client_apellido_materno,
        "calle": (form.get("calle") if form else None) or (client.calle if client else "") or "",
        "numero": (form.get("numero") if form else None) or (client.numero if client else "") or "",
        "colonia": (form.get("colonia") if form else None) or (client.colonia if client else "") or "",
        "codigo_postal": (form.get("codigo_postal") if form else None) or (client.codigo_postal if client else "") or "",
        "estado": (form.get("estado") if form else None) or (client.estado if client else "") or "",
        "entidad": (form.get("entidad") if form else None) or (client.entidad if client else "") or "",
        "telefono": (form.get("telefono") if form else None) or (client.telefono if client else "") or "",
        "correo": (form.get("correo") if form else None) or (client.correo if client else "") or "",
    }


def _validate_client_form(form, *, client_id: int | None = None, require_password: bool = True):
    # Valida y normaliza los datos capturados en el formulario de clientes.
    errors = []

    nombres = (form.get("nombres") or "").strip()
    apellido_paterno = (form.get("apellido_paterno") or "").strip()
    apellido_materno = (form.get("apellido_materno") or "").strip()
    calle = (form.get("calle") or "").strip()
    numero = (form.get("numero") or "").strip()
    colonia = (form.get("colonia") or "").strip()
    codigo_postal = (form.get("codigo_postal") or "").strip()
    estado = (form.get("estado") or "").strip()
    entidad = (form.get("entidad") or "").strip()
    telefono = (form.get("telefono") or "").strip()
    correo = (form.get("correo") or "").strip().lower()
    contrasena = form.get("contrasena") or ""

    if not nombres:
        errors.append("El nombre es obligatorio.")
    if codigo_postal and not CP_PATTERN.match(codigo_postal):
        errors.append("El C.P. debe tener exactamente 5 dígitos.")
    if not telefono:
        errors.append("El teléfono es obligatorio.")
    elif not _is_valid_phone(telefono):
        errors.append("El teléfono debe tener un formato válido.")
    if not correo:
        errors.append("El correo es obligatorio.")
    elif not _is_valid_email(correo):
        errors.append("El correo no tiene un formato válido.")

    if require_password and not contrasena:
        errors.append("La contraseña es obligatoria.")
    if contrasena:
        errors.extend(validate_password(contrasena, correo=correo, nombre=_full_name(nombres, apellido_paterno, apellido_materno)))

    if correo:
        duplicate_query = db.session.query(Usuario.id).filter(func.lower(Usuario.correo) == correo.lower())
        if client_id is not None:
            duplicate_query = duplicate_query.filter(Usuario.id != client_id)
        if duplicate_query.first():
            errors.append("Ya existe un cliente con ese correo.")

    nombre = _full_name(nombres, apellido_paterno, apellido_materno)
    domicilio = _full_address(calle, numero, colonia, codigo_postal, estado, entidad)

    payload = {
        "nombres": nombres,
        "apellido_paterno": apellido_paterno or None,
        "apellido_materno": apellido_materno or None,
        "nombre": nombre,
        "calle": calle or None,
        "numero": numero or None,
        "colonia": colonia or None,
        "codigo_postal": codigo_postal or None,
        "estado": estado or None,
        "entidad": entidad or None,
        "domicilio": domicilio,
        "telefono": telefono,
        "correo": correo,
        "contrasena": contrasena,
    }

    return errors, payload


# --- CONSULTAS Y TRANSFORMACIONES DE DATOS ---
def _clients_query():
    # Construye la consulta base del listado de clientes con conteo de mascotas.
    pet_counts = (
        db.session.query(
            Mascota.dueno_id.label("cliente_id"),
            func.count(Mascota.id).label("mascotas_count"),
        )
        .group_by(Mascota.dueno_id)
        .subquery()
    )

    return (
        db.session.query(
            Usuario,
            func.coalesce(pet_counts.c.mascotas_count, 0).label("mascotas_count"),
        )
        .join(Rol, Usuario.rol_id == Rol.id)
        .outerjoin(pet_counts, pet_counts.c.cliente_id == Usuario.id)
        .filter(func.lower(Rol.nombre) == ROLE_CLIENTE)
        .filter(Usuario.eliminado.is_(False))
        .order_by(Usuario.nombre.asc(), Usuario.id.asc())
    )


def _client_pets(client_id: int):
    # Obtiene las mascotas asociadas a un cliente.
    return (
        db.session.query(Mascota)
        .filter(Mascota.dueno_id == client_id)
        .order_by(Mascota.nombre.asc(), Mascota.id.asc())
        .all()
    )


def _client_appointments(client_id: int):
    # Obtiene las citas registradas para un cliente.
    return (
        db.session.query(Cita, Mascota.nombre.label("mascota_nombre"))
        .join(Mascota, Mascota.id == Cita.mascota_id)
        .filter(Cita.cliente_id == client_id)
        .order_by(Cita.fecha_hora.desc(), Cita.id.desc())
        .all()
    )


def _client_financial_rows(client_id: int):
    # Obtiene los movimientos de facturación de un cliente.
    return (
        db.session.query(Facturacion)
        .filter(Facturacion.cliente_id == client_id)
        .order_by(Facturacion.fecha_pago.desc(), Facturacion.id.desc())
        .all()
    )


def _financial_summary(rows: list[Facturacion]):
    # Resume los totales financieros de un cliente.
    total_pagado = sum((row.monto_pagado or Decimal("0")) for row in rows)
    total_descuento = sum((row.descuento or Decimal("0")) for row in rows)
    total_adeudo = sum((row.adeudo or Decimal("0")) for row in rows)
    total_facturado = sum((row.monto_total or Decimal("0")) for row in rows)
    pendientes = sum(1 for row in rows if row.estado in {"pendiente", "parcial"})
    return {
        "total_facturado": total_facturado,
        "total_pagado": total_pagado,
        "total_descuento": total_descuento,
        "total_adeudo": total_adeudo,
        "pendientes": pendientes,
    }


# --- RUTAS DE CLIENTES ---
@clientes_bp.get("/clientes")
def clientes_index():
    # Muestra el listado general de clientes.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    role = _role_name(me)
    if role == ROLE_CLIENTE:
        return redirect(url_for("clientes.clientes_portal"))

    if role not in {ROLE_ADMIN, ROLE_VETERINARIO}:
        return render_template("acceso_denegado.html", me=me)

    rows = _clients_query().all()
    return render_template(
        "clientes_list.html",
        me=me,
        active_nav="clientes",
        clientes_rows=rows,
        can_create=_allowed(me, "hu018"),
        can_edit=_allowed(me, "hu019"),
        can_inactivate=_allowed(me, "hu020"),
        can_notify=_allowed(me, "hu021"),
        can_view_pets=_allowed(me, "hu022"),
        can_view_finance=_allowed(me, "hu023"),
    )


@clientes_bp.route("/clientes/nuevo", methods=["GET", "POST"])
def clientes_new():
    # Registra un nuevo cliente en el sistema.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    if not _allowed(me, "hu018"):
        return render_template("acceso_denegado.html", me=me)

    if request.method == "GET":
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="create",
            form_data=_client_form_data(),
        )

    errors, payload = _validate_client_form(request.form, require_password=True)
    form_data = _client_form_data(request.form)

    if errors:
        for err in errors:
            flash(err, "error")
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="create",
            form_data=form_data,
        )

    role = _get_client_role()
    if not role:
        flash("No existe el rol cliente en la base de datos.", "error")
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="create",
            form_data=form_data,
        )

    client = Usuario(
        nombres=payload["nombres"],
        apellido_paterno=payload["apellido_paterno"],
        apellido_materno=payload["apellido_materno"],
        nombre=payload["nombre"],
        correo=payload["correo"],
        contrasena=generate_password_hash(payload["contrasena"]),
        calle=payload["calle"],
        numero=payload["numero"],
        colonia=payload["colonia"],
        codigo_postal=payload["codigo_postal"],
        estado=payload["estado"],
        entidad=payload["entidad"],
        domicilio=payload["domicilio"],
        telefono=payload["telefono"],
        razon_inactivacion=None,
        activo=True,
        eliminado=False,
        rol_id=role.id,
    )
    db.session.add(client)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("No fue posible registrar el cliente por un conflicto de datos.", "error")
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="create",
            form_data=form_data,
        )

    flash("Cliente registrado correctamente.", "success")
    return redirect(url_for("clientes.clientes_index"))


@clientes_bp.route("/clientes/<int:client_id>/editar", methods=["GET", "POST"])
def clientes_edit(client_id: int):
    # Actualiza la información de un cliente existente.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    if not _allowed(me, "hu019"):
        return render_template("acceso_denegado.html", me=me)

    client = _client_exists_for_access(client_id)
    if not client:
        return render_template("cliente_no_encontrado.html", me=me, active_nav="clientes", client_id=client_id)

    if request.method == "GET":
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="edit",
            client=client,
            client_id=client.id,
            form_data=_client_form_data(client=client),
        )

    errors, payload = _validate_client_form(request.form, client_id=client.id, require_password=False)
    form_data = _client_form_data(request.form, client)

    if errors:
        for err in errors:
            flash(err, "error")
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="edit",
            client=client,
            client_id=client.id,
            form_data=form_data,
        )

    client.nombres = payload["nombres"]
    client.apellido_paterno = payload["apellido_paterno"]
    client.apellido_materno = payload["apellido_materno"]
    client.nombre = payload["nombre"]
    client.calle = payload["calle"]
    client.numero = payload["numero"]
    client.colonia = payload["colonia"]
    client.codigo_postal = payload["codigo_postal"]
    client.estado = payload["estado"]
    client.entidad = payload["entidad"]
    client.domicilio = payload["domicilio"]
    client.telefono = payload["telefono"]
    client.correo = payload["correo"]
    if payload["contrasena"]:
        client.contrasena = generate_password_hash(payload["contrasena"])

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("No fue posible actualizar el cliente por un conflicto de datos.", "error")
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="edit",
            client=client,
            client_id=client.id,
            form_data=form_data,
        )

    flash("Cliente actualizado correctamente.", "success")
    return redirect(url_for("clientes.clientes_index"))


@clientes_bp.route("/clientes/<int:client_id>/inactivar", methods=["GET", "POST"])
def clientes_inactivar(client_id: int):
    # Inactiva un cliente y guarda la razón indicada.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    if not _allowed(me, "hu020"):
        return render_template("acceso_denegado.html", me=me)

    client = _client_exists_for_access(client_id)
    if not client:
        return render_template("cliente_no_encontrado.html", me=me, active_nav="clientes", client_id=client_id)

    if request.method == "GET":
        return render_template(
            "cliente_inactivar.html",
            me=me,
            active_nav="clientes",
            client=client,
        )

    razon = (request.form.get("razon_inactivacion") or "").strip()
    confirmacion = request.form.get("confirmar") == "si"

    errors = []
    if not razon:
        errors.append("La razón de inactivación es obligatoria.")
    if not confirmacion:
        errors.append("Debes confirmar la inactivación.")

    if errors:
        for err in errors:
            flash(err, "error")
        return render_template(
            "cliente_inactivar.html",
            me=me,
            active_nav="clientes",
            client=client,
        )

    client.activo = False
    client.eliminado = False
    client.razon_inactivacion = razon
    db.session.commit()

    flash("Cliente inactivado correctamente.", "success")
    return redirect(url_for("clientes.clientes_index"))


@clientes_bp.route("/clientes/<int:client_id>/notificar", methods=["GET", "POST"])
def clientes_notificar(client_id: int):
    # Envía una notificación por correo a un cliente.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    if not _allowed(me, "hu021"):
        return render_template("acceso_denegado.html", me=me)

    client = _client_exists_for_access(client_id)
    if not client:
        return render_template("cliente_no_encontrado.html", me=me, active_nav="clientes", client_id=client_id)

    default_subject = f"Notificación de CIVE para {client.nombre}"
    default_message = (
        f"Hola {client.nombre},\n\n"
        "Te contactamos desde CIVE para compartirte una notificación sobre tu cuenta.\n\n"
        "Quedamos atentos.\n"
        "Clínica CIVE"
    )

    if request.method == "GET":
        return render_template(
            "cliente_notificar.html",
            me=me,
            active_nav="clientes",
            client=client,
            form_data={"asunto": default_subject, "mensaje": default_message},
        )

    subject = (request.form.get("asunto") or "").strip()
    body = (request.form.get("mensaje") or "").strip()

    if not subject or not body:
        flash("El asunto y el mensaje son obligatorios.", "error")
        return render_template(
            "cliente_notificar.html",
            me=me,
            active_nav="clientes",
            client=client,
            form_data={"asunto": subject, "mensaje": body},
        )

    if not (client.correo or "").strip():
        flash("El cliente no tiene correo registrado.", "error")
        return render_template(
            "cliente_notificar.html",
            me=me,
            active_nav="clientes",
            client=client,
            form_data={"asunto": subject, "mensaje": body},
        )

    from app.routes.chat import _send_email_smtp

    # Enviamos el correo y mostramos el error si el servicio no responde.
    sent_ok, sent_error = _send_email_smtp(client.correo.strip(), subject, body)
    if not sent_ok:
        flash(sent_error or "No fue posible enviar el correo.", "error")
        return render_template(
            "cliente_notificar.html",
            me=me,
            active_nav="clientes",
            client=client,
            form_data={"asunto": subject, "mensaje": body},
        )

    flash("Notificación enviada correctamente.", "success")
    return redirect(url_for("clientes.clientes_index"))


@clientes_bp.get("/clientes/<int:client_id>/mascotas")
def clientes_mascotas(client_id: int):
    # Muestra las mascotas asociadas a un cliente.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    if not _can_access_client_resource(me, client_id, "hu022"):
        return render_template("acceso_denegado.html", me=me)

    client = _client_exists_for_access(client_id)
    if not client:
        return render_template("cliente_no_encontrado.html", me=me, active_nav="clientes", client_id=client_id)

    pets = _client_pets(client.id)
    return render_template(
        "cliente_mascotas.html",
        me=me,
        active_nav="clientes",
        client=client,
        pets=pets,
    )


@clientes_bp.get("/clientes/<int:client_id>/finanzas")
def clientes_finanzas(client_id: int):
    # Muestra el resumen financiero de un cliente.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    if not _can_access_client_resource(me, client_id, "hu023"):
        return render_template("acceso_denegado.html", me=me)

    client = _client_exists_for_access(client_id)
    if not client:
        return render_template("cliente_no_encontrado.html", me=me, active_nav="clientes", client_id=client_id)

    rows = _client_financial_rows(client.id)
    return render_template(
        "cliente_finanzas.html",
        me=me,
        active_nav="clientes",
        client=client,
        financial_rows=rows,
        summary=_financial_summary(rows),
    )


@clientes_bp.get("/portal-cliente")
def clientes_portal():
    # Muestra el portal de autoservicio para clientes.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    if not _allowed(me, "hu024"):
        return render_template("acceso_denegado.html", me=me)

    client_id = _parse_int(me.get("id"))
    client = _client_exists_for_access(client_id) if client_id is not None else None
    if not client:
        return render_template("cliente_no_encontrado.html", me=me, active_nav="clientes", client_id=client_id)

    pets = _client_pets(client.id)
    appointments = _client_appointments(client.id)
    financial_rows = _client_financial_rows(client.id)
    pending_rows = [row for row in financial_rows if row.estado in {"pendiente", "parcial"}]

    return render_template(
        "cliente_portal.html",
        me=me,
        active_nav="clientes",
        client=client,
        pets=pets,
        appointments=appointments,
        financial_rows=financial_rows,
        pending_rows=pending_rows,
        summary=_financial_summary(financial_rows),
    )
