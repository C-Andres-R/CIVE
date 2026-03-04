from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy import and_, func
from sqlalchemy.orm import aliased

from app.extensions import db
from app.models import Cita, Mascota, RecordatorioCita, Rol, Usuario
from utils.auth_ui import get_current_user_from_api

citas_bp = Blueprint("citas", __name__)

# --- CONFIGURACION DE CITAS ---
LOGIN_GET_ENDPOINT = "pages.login_page"

ROLE_ADMIN = "administrador"
ROLE_CLIENTE = "cliente"
ROLE_VETERINARIO = "veterinario"

PERMISSIONS = {
    "hu005": {ROLE_ADMIN, ROLE_CLIENTE, ROLE_VETERINARIO},
    "hu006": {ROLE_ADMIN, ROLE_CLIENTE, ROLE_VETERINARIO},
    "hu007": {ROLE_ADMIN, ROLE_CLIENTE},
    "hu008": {ROLE_ADMIN},
    "hu009": {ROLE_ADMIN, ROLE_CLIENTE, ROLE_VETERINARIO},
    "hu010": {ROLE_ADMIN, ROLE_CLIENTE},
}


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


def _redirect_client_to_portal(me):
    # Redirige al cliente a su portal cuando la ruta no le corresponde.
    if _role_name(me) == ROLE_CLIENTE:
        return redirect(url_for("clientes.clientes_portal"))
    return None


def _parse_int(value):
    # Convierte un valor a entero y regresa None si no es válido.
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime_local(value: str):
    # Convierte un texto a fecha y hora local con el formato del formulario.
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def _parse_date(value: str):
    # Convierte un texto a fecha con el formato esperado.
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _is_future_datetime(value: datetime) -> bool:
    # Verifica que una fecha y hora sean futuras.
    return value > datetime.now()


def _not_canceled_clause():
    # Construye la condición para excluir citas canceladas.
    return and_(Cita.cancelada.is_(False), Cita.estado != "cancelada")


# --- CONSULTAS Y REGLAS DE NEGOCIO ---
def _is_veterinario_disponible(veterinario_id: int, fecha_hora: datetime, exclude_cita_id: int | None = None) -> bool:
    # Revisa si un veterinario está libre en una fecha y hora específicas.
    q = db.session.query(Cita.id).filter(
        Cita.veterinario_id == veterinario_id,
        Cita.fecha_hora == fecha_hora,
        _not_canceled_clause(),
    )
    if exclude_cita_id is not None:
        q = q.filter(Cita.id != exclude_cita_id)
    return q.first() is None


def _get_usuarios_por_rol(nombre_rol: str):
    # Obtiene los usuarios activos de un rol específico.
    return (
        db.session.query(Usuario)
        .join(Rol, Usuario.rol_id == Rol.id)
        .filter(func.lower(Rol.nombre) == nombre_rol.lower())
        .filter(Usuario.eliminado.is_(False), Usuario.activo.is_(True))
        .order_by(Usuario.nombre.asc())
        .all()
    )


def _get_mascotas_con_dueno_for_form(me):
    # Obtiene las mascotas disponibles para el formulario de citas.
    role = _role_name(me)
    q = (
        db.session.query(Mascota.id, Mascota.nombre, Mascota.dueno_id, Usuario.nombre.label("dueno_nombre"))
        .join(Usuario, Mascota.dueno_id == Usuario.id)
        .filter(Usuario.eliminado.is_(False))
    )
    if role == ROLE_CLIENTE:
        q = q.filter(Mascota.dueno_id == int(me["id"]))
    return q.order_by(Mascota.nombre.asc()).all()


def _user_can_touch_cita(me, cita: Cita) -> bool:
    # Verifica si el usuario actual puede modificar la cita indicada.
    role = _role_name(me)
    me_id = _parse_int(me.get("id"))
    if role == ROLE_ADMIN:
        return True
    if role == ROLE_CLIENTE and me_id is not None:
        return cita.cliente_id == me_id
    if role == ROLE_VETERINARIO and me_id is not None:
        return cita.veterinario_id == me_id
    return False


def _build_cita_list_query(me):
    # Construye la consulta base del listado de citas según el rol.
    cliente = aliased(Usuario)
    veterinario = aliased(Usuario)

    q = (
        db.session.query(
            Cita,
            cliente.nombre.label("cliente_nombre"),
            Mascota.nombre.label("mascota_nombre"),
            veterinario.nombre.label("veterinario_nombre"),
            RecordatorioCita.estado.label("recordatorio_estado"),
            RecordatorioCita.confirmado.label("recordatorio_confirmado"),
        )
        .join(cliente, Cita.cliente_id == cliente.id)
        .join(Mascota, Cita.mascota_id == Mascota.id)
        .join(veterinario, Cita.veterinario_id == veterinario.id)
        .outerjoin(RecordatorioCita, RecordatorioCita.cita_id == Cita.id)
        .filter(cliente.eliminado.is_(False), veterinario.eliminado.is_(False))
    )

    role = _role_name(me)
    me_id = _parse_int(me.get("id"))
    if role == ROLE_CLIENTE and me_id is not None:
        q = q.filter(Cita.cliente_id == me_id)
    elif role == ROLE_VETERINARIO and me_id is not None:
        q = q.filter(Cita.veterinario_id == me_id)

    return q


def _validate_and_normalize_form(me, form, *, editing_cita_id: int | None = None):
    # Valida y normaliza los datos capturados en el formulario de citas.
    errors = []

    fecha_hora_raw = form.get("fecha_hora") or ""
    motivo = (form.get("motivo") or "").strip()
    mascota_id = _parse_int(form.get("mascota_id"))
    cliente_id = _parse_int(form.get("cliente_id"))
    veterinario_id = _parse_int(form.get("veterinario_id"))

    fecha_hora = _parse_datetime_local(fecha_hora_raw)

    if _role_name(me) == ROLE_CLIENTE:
        cliente_id = _parse_int(me.get("id"))

    if not fecha_hora:
        errors.append("La fecha/hora es obligatoria y debe ser válida.")
    elif not _is_future_datetime(fecha_hora):
        errors.append("La fecha/hora debe ser futura.")

    if not motivo:
        errors.append("El motivo es obligatorio.")
    if not mascota_id:
        errors.append("La mascota es obligatoria.")
    if not cliente_id:
        errors.append("El cliente es obligatorio.")
    if not veterinario_id:
        errors.append("El veterinario es obligatorio.")

    cliente = None
    mascota = None
    veterinario = None

    if cliente_id:
        cliente = (
            db.session.query(Usuario)
            .join(Rol, Usuario.rol_id == Rol.id)
            .filter(Usuario.id == cliente_id, Usuario.activo.is_(True), Usuario.eliminado.is_(False))
            .filter(func.lower(Rol.nombre) == ROLE_CLIENTE)
            .first()
        )
        if not cliente:
            errors.append("El cliente seleccionado no es válido.")

    if mascota_id:
        mascota = db.session.get(Mascota, mascota_id)
        if not mascota:
            errors.append("La mascota seleccionada no existe.")

    if cliente and mascota and mascota.dueno_id != cliente.id:
        errors.append("La mascota seleccionada no pertenece al cliente indicado.")

    if veterinario_id:
        veterinario = (
            db.session.query(Usuario)
            .join(Rol, Usuario.rol_id == Rol.id)
            .filter(Usuario.id == veterinario_id, Usuario.activo.is_(True), Usuario.eliminado.is_(False))
            .filter(func.lower(Rol.nombre) == ROLE_VETERINARIO)
            .first()
        )
        if not veterinario:
            errors.append("El veterinario seleccionado no es válido.")

    if fecha_hora and veterinario_id:
        if not _is_veterinario_disponible(veterinario_id, fecha_hora, exclude_cita_id=editing_cita_id):
            errors.append("El veterinario no está disponible en la fecha/hora indicada.")

    payload = {
        "fecha_hora": fecha_hora,
        "motivo": motivo,
        "mascota_id": mascota_id,
        "cliente_id": cliente_id,
        "veterinario_id": veterinario_id,
    }

    return errors, payload


def _default_form_data():
    # Genera los valores iniciales del formulario de citas.
    return {
        "fecha_hora": "",
        "motivo": "",
        "mascota_id": "",
        "cliente_id": "",
        "veterinario_id": "",
    }


def _datetime_to_local_input(dt: datetime | None) -> str:
    # Convierte una fecha al formato usado por el campo datetime-local.
    if not dt:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M")


# --- RUTAS DE CITAS ---
@citas_bp.get("/citas")
def citas_index():
    # Muestra el listado general de citas.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    client_redirect = _redirect_client_to_portal(me)
    if client_redirect:
        return client_redirect

    if not _allowed(me, "hu007"):
        return render_template("acceso_denegado.html", me=me), 403

    estado = (request.args.get("estado") or "").strip().lower()
    fecha_inicio = _parse_date(request.args.get("fecha_inicio") or "")
    fecha_fin = _parse_date(request.args.get("fecha_fin") or "")
    veterinario_id = _parse_int(request.args.get("veterinario_id"))
    orden = (request.args.get("orden") or "asc").strip().lower()
    if orden not in {"asc", "desc"}:
        orden = "asc"

    q = _build_cita_list_query(me)

    if estado in {"pendiente", "confirmada", "cancelada"}:
        q = q.filter(Cita.estado == estado)

    if fecha_inicio:
        q = q.filter(Cita.fecha_hora >= datetime.combine(fecha_inicio, time.min))
    if fecha_fin:
        q = q.filter(Cita.fecha_hora <= datetime.combine(fecha_fin, time.max))

    if veterinario_id:
        q = q.filter(Cita.veterinario_id == veterinario_id)

    if orden == "desc":
        q = q.order_by(Cita.fecha_hora.desc())
    else:
        q = q.order_by(Cita.fecha_hora.asc())

    rows = q.all()
    veterinarios = _get_usuarios_por_rol(ROLE_VETERINARIO)

    return render_template(
        "citas_list.html",
        me=me,
        active_nav="citas",
        citas_rows=rows,
        veterinarios=veterinarios,
        filters={
            "estado": estado,
            "fecha_inicio": request.args.get("fecha_inicio") or "",
            "fecha_fin": request.args.get("fecha_fin") or "",
            "veterinario_id": str(veterinario_id or ""),
            "orden": orden,
        },
        can_create=_allowed(me, "hu005"),
        can_manage=_allowed(me, "hu006"),
        can_send_reminder=_allowed(me, "hu008"),
        now=datetime.now(),
    )


@citas_bp.route("/citas/nueva", methods=["GET", "POST"])
def citas_new():
    # Registra una nueva cita desde el formulario.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    client_redirect = _redirect_client_to_portal(me)
    if client_redirect:
        return client_redirect

    if not _allowed(me, "hu005"):
        return render_template("acceso_denegado.html", me=me), 403

    veterinarios = _get_usuarios_por_rol(ROLE_VETERINARIO)
    clientes = _get_usuarios_por_rol(ROLE_CLIENTE)
    mascotas = _get_mascotas_con_dueno_for_form(me)

    if request.method == "GET":
        form_data = _default_form_data()
        if _role_name(me) == ROLE_CLIENTE:
            form_data["cliente_id"] = str(me.get("id") or "")
        return render_template(
            "cita_form.html",
            me=me,
            active_nav="citas",
            mode="create",
            form_data=form_data,
            veterinarios=veterinarios,
            clientes=clientes,
            mascotas=mascotas,
        )

    # Validamos los datos antes de crear la cita.
    errors, payload = _validate_and_normalize_form(me, request.form)
    form_data = {
        "fecha_hora": request.form.get("fecha_hora") or "",
        "motivo": request.form.get("motivo") or "",
        "mascota_id": request.form.get("mascota_id") or "",
        "cliente_id": str(payload.get("cliente_id") or ""),
        "veterinario_id": request.form.get("veterinario_id") or "",
    }

    if errors:
        for error in errors:
            flash(error, "error")
        return render_template(
            "cita_form.html",
            me=me,
            active_nav="citas",
            mode="create",
            form_data=form_data,
            veterinarios=veterinarios,
            clientes=clientes,
            mascotas=mascotas,
        )

    # Guardamos la cita en la base de datos cuando el formulario es valido.
    cita = Cita(
        fecha_hora=payload["fecha_hora"],
        motivo=payload["motivo"],
        mascota_id=payload["mascota_id"],
        cliente_id=payload["cliente_id"],
        veterinario_id=payload["veterinario_id"],
        estado="pendiente",
        cancelada=False,
    )
    db.session.add(cita)
    db.session.commit()

    flash("Cita creada correctamente.", "success")
    return redirect(url_for("citas.citas_index"))


@citas_bp.route("/citas/<int:cita_id>/editar", methods=["GET", "POST"])
def citas_edit(cita_id: int):
    # Actualiza una cita existente.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    client_redirect = _redirect_client_to_portal(me)
    if client_redirect:
        return client_redirect

    if not _allowed(me, "hu006"):
        return render_template("acceso_denegado.html", me=me), 403

    cita = db.session.get(Cita, cita_id)
    if not cita:
        flash("La cita no existe.", "error")
        return redirect(url_for("citas.citas_index"))

    if not _user_can_touch_cita(me, cita):
        return render_template("acceso_denegado.html", me=me), 403

    if cita.cancelada or cita.estado == "cancelada":
        flash("No se puede modificar una cita cancelada.", "error")
        return redirect(url_for("citas.citas_index"))

    if not _is_future_datetime(cita.fecha_hora):
        flash("Solo se pueden modificar citas futuras.", "error")
        return redirect(url_for("citas.citas_index"))

    veterinarios = _get_usuarios_por_rol(ROLE_VETERINARIO)
    clientes = _get_usuarios_por_rol(ROLE_CLIENTE)
    mascotas = _get_mascotas_con_dueno_for_form(me)

    if request.method == "GET":
        form_data = {
            "fecha_hora": _datetime_to_local_input(cita.fecha_hora),
            "motivo": cita.motivo or "",
            "mascota_id": str(cita.mascota_id),
            "cliente_id": str(cita.cliente_id),
            "veterinario_id": str(cita.veterinario_id),
        }
        return render_template(
            "cita_form.html",
            me=me,
            active_nav="citas",
            mode="edit",
            cita_id=cita.id,
            form_data=form_data,
            veterinarios=veterinarios,
            clientes=clientes,
            mascotas=mascotas,
        )

    # Validamos los datos antes de actualizar la cita.
    errors, payload = _validate_and_normalize_form(me, request.form, editing_cita_id=cita.id)
    form_data = {
        "fecha_hora": request.form.get("fecha_hora") or "",
        "motivo": request.form.get("motivo") or "",
        "mascota_id": request.form.get("mascota_id") or "",
        "cliente_id": str(payload.get("cliente_id") or ""),
        "veterinario_id": request.form.get("veterinario_id") or "",
    }

    if errors:
        for error in errors:
            flash(error, "error")
        return render_template(
            "cita_form.html",
            me=me,
            active_nav="citas",
            mode="edit",
            cita_id=cita.id,
            form_data=form_data,
            veterinarios=veterinarios,
            clientes=clientes,
            mascotas=mascotas,
        )

    cita.fecha_hora = payload["fecha_hora"]
    cita.motivo = payload["motivo"]
    cita.mascota_id = payload["mascota_id"]
    cita.cliente_id = payload["cliente_id"]
    cita.veterinario_id = payload["veterinario_id"]

    if cita.estado == "cancelada":
        cita.estado = "pendiente"
        cita.cancelada = False

    db.session.commit()
    flash("Cita modificada correctamente.", "success")
    return redirect(url_for("citas.citas_index"))


@citas_bp.post("/citas/<int:cita_id>/cancelar")
def citas_cancel(cita_id: int):
    # Cancela una cita futura autorizada.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    client_redirect = _redirect_client_to_portal(me)
    if client_redirect:
        return client_redirect

    if not _allowed(me, "hu006"):
        return render_template("acceso_denegado.html", me=me), 403

    cita = db.session.get(Cita, cita_id)
    if not cita:
        flash("La cita no existe.", "error")
        return redirect(url_for("citas.citas_index"))

    if not _user_can_touch_cita(me, cita):
        return render_template("acceso_denegado.html", me=me), 403

    if not _is_future_datetime(cita.fecha_hora):
        flash("Solo se pueden cancelar citas futuras.", "error")
        return redirect(url_for("citas.citas_index"))

    cita.estado = "cancelada"
    cita.cancelada = True
    db.session.commit()

    flash("Cita cancelada correctamente.", "success")
    return redirect(url_for("citas.citas_index"))


@citas_bp.post("/citas/<int:cita_id>/recordatorio")
def citas_send_reminder(cita_id: int):
    # Envía por correo el recordatorio de una cita.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    client_redirect = _redirect_client_to_portal(me)
    if client_redirect:
        return client_redirect

    if not _allowed(me, "hu008"):
        return render_template("acceso_denegado.html", me=me), 403

    cita = db.session.get(Cita, cita_id)
    if not cita:
        flash("La cita no existe.", "error")
        return redirect(url_for("citas.citas_index"))

    # Verificamos que el cliente tenga un correo disponible para el recordatorio.
    cliente = db.session.get(Usuario, cita.cliente_id)
    if not cliente or not (cliente.correo or "").strip():
        flash("No se pudo enviar: el cliente no tiene correo registrado.", "error")
        return redirect(url_for("citas.citas_index"))

    # Buscamos o creamos el registro que controlara el estado del recordatorio.
    reminder = db.session.query(RecordatorioCita).filter(RecordatorioCita.cita_id == cita.id).first()
    if not reminder:
        reminder = RecordatorioCita(cita_id=cita.id, estado="programado", confirmado=False)
        db.session.add(reminder)

    # Generamos el enlace que permitira confirmar la recepcion del correo.
    token = secrets.token_urlsafe(32)
    confirm_url = url_for("chat.chat_confirm_reminder", token=token, _external=True)

    subject = "Recordatorio de cita - CIVE"
    body = (
        f"Hola {cliente.nombre or 'Cliente'},\n\n"
        "Este es un recordatorio de tu cita en CIVE.\n"
        f"Fecha y hora: {cita.fecha_hora}\n"
        f"Motivo: {cita.motivo or 'Sin motivo especificado'}\n\n"
        "Confirma recepción de este recordatorio en el siguiente enlace:\n"
        f"{confirm_url}\n"
    )

    from app.routes.chat import _send_email_smtp  # Reutiliza la lógica SMTP existente.

    # Enviamos el correo y detenemos el flujo si ocurre un error.
    sent_ok, sent_error = _send_email_smtp((cliente.correo or "").strip(), subject, body)
    if not sent_ok:
        db.session.commit()
        flash(f"No se pudo enviar el recordatorio: {sent_error}", "error")
        return redirect(url_for("citas.citas_index"))

    # Guardamos en la base de datos que el recordatorio ya fue enviado.
    reminder.estado = "enviado"
    reminder.enviado_en = datetime.now()
    reminder.confirmado = False
    reminder.confirmado_en = None
    reminder.token_confirmacion = token
    db.session.commit()

    flash("Recordatorio enviado correctamente.", "success")
    return redirect(url_for("citas.citas_index"))


# --- APOYO PARA DISPONIBILIDAD ---
def _daily_slots(target_date: date):
    # Genera los horarios base disponibles para un día.
    slots = []
    for hour in range(9, 19):
        slots.append(datetime.combine(target_date, time(hour=hour, minute=0)))
    return slots


def _slot_label(dt: datetime) -> str:
    # Convierte un horario a texto legible para la interfaz.
    return dt.strftime("%Y-%m-%d %H:%M")


def _next_available_suggestions(veterinario_id: int, base_dt: datetime, count: int = 5):
    # Busca los siguientes horarios libres para un veterinario.
    suggestions = []
    cursor_date = base_dt.date()

    for day_offset in range(0, 10):
        day = cursor_date + timedelta(days=day_offset)
        if day < date.today():
            continue

        for slot in _daily_slots(day):
            if slot <= datetime.now():
                continue
            if _is_veterinario_disponible(veterinario_id, slot):
                suggestions.append(slot)
            if len(suggestions) >= count:
                return suggestions

    return suggestions


@citas_bp.route("/citas/disponibilidad", methods=["GET", "POST"])
def citas_disponibilidad():
    # Consulta la disponibilidad de un veterinario en una fecha.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    client_redirect = _redirect_client_to_portal(me)
    if client_redirect:
        return client_redirect

    if not _allowed(me, "hu009"):
        return render_template("acceso_denegado.html", me=me), 403

    veterinarios = _get_usuarios_por_rol(ROLE_VETERINARIO)
    result = None
    form_data = {"veterinario_id": "", "fecha": ""}

    if request.method == "POST":
        veterinario_id = _parse_int(request.form.get("veterinario_id"))
        fecha = _parse_date(request.form.get("fecha") or "")
        form_data = {
            "veterinario_id": str(veterinario_id or ""),
            "fecha": request.form.get("fecha") or "",
        }

        errors = []

        vet = None
        if not veterinario_id:
            errors.append("Debes seleccionar un veterinario.")
        else:
            vet = (
                db.session.query(Usuario)
                .join(Rol, Usuario.rol_id == Rol.id)
                .filter(Usuario.id == veterinario_id, Usuario.activo.is_(True), Usuario.eliminado.is_(False))
                .filter(func.lower(Rol.nombre) == ROLE_VETERINARIO)
                .first()
            )
            if not vet:
                errors.append("El veterinario seleccionado no es válido.")

        if not fecha:
            errors.append("Debes capturar una fecha válida.")
        elif fecha <= date.today():
            errors.append("La fecha debe ser futura.")

        if errors:
            for e in errors:
                flash(e, "error")
        else:
            slots = _daily_slots(fecha)
            ocupados = {
                row[0]
                for row in db.session.query(Cita.fecha_hora)
                .filter(
                    Cita.veterinario_id == veterinario_id,
                    Cita.fecha_hora >= datetime.combine(fecha, time.min),
                    Cita.fecha_hora <= datetime.combine(fecha, time.max),
                    _not_canceled_clause(),
                )
                .all()
            }

            libres = [slot for slot in slots if slot not in ocupados and slot > datetime.now()]
            disponible = len(libres) > 0

            if disponible:
                sugerencias = libres[:5]
            else:
                sugerencias = _next_available_suggestions(veterinario_id, datetime.combine(fecha, time.min), count=5)

            result = {
                "disponible": disponible,
                "veterinario": vet,
                "fecha": fecha,
                "sugerencias": [_slot_label(s) for s in sugerencias],
            }

    return render_template(
        "citas_disponibilidad.html",
        me=me,
        active_nav="citas",
        veterinarios=veterinarios,
        form_data=form_data,
        result=result,
    )


@citas_bp.route("/citas/reasignar", methods=["GET", "POST"])
def citas_reasignar():
    # Reasigna una cita futura a otro veterinario disponible.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    client_redirect = _redirect_client_to_portal(me)
    if client_redirect:
        return client_redirect

    if not _allowed(me, "hu010"):
        return render_template("acceso_denegado.html", me=me), 403

    veterinarios = _get_usuarios_por_rol(ROLE_VETERINARIO)
    citas_q = (
        db.session.query(Cita)
        .filter(Cita.fecha_hora > datetime.now(), _not_canceled_clause())
        .order_by(Cita.fecha_hora.asc())
    )
    if _role_name(me) == ROLE_CLIENTE:
        me_id = _parse_int(me.get("id"))
        if me_id is not None:
            citas_q = citas_q.filter(Cita.cliente_id == me_id)
    citas_futuras = citas_q.all()

    form_data = {
        "fecha": "",
        "cita_id": "",
        "veterinario_original_id": "",
        "veterinario_nuevo_id": "",
        "ausencia_confirmada": False,
    }

    if request.method == "POST":
        fecha = _parse_date(request.form.get("fecha") or "")
        cita_id = _parse_int(request.form.get("cita_id"))
        veterinario_original_id = _parse_int(request.form.get("veterinario_original_id"))
        veterinario_nuevo_id = _parse_int(request.form.get("veterinario_nuevo_id"))
        ausencia_confirmada = request.form.get("ausencia_confirmada") == "on"

        form_data = {
            "fecha": request.form.get("fecha") or "",
            "cita_id": str(cita_id or ""),
            "veterinario_original_id": str(veterinario_original_id or ""),
            "veterinario_nuevo_id": str(veterinario_nuevo_id or ""),
            "ausencia_confirmada": ausencia_confirmada,
        }

        errors = []

        if not ausencia_confirmada:
            errors.append("Debes confirmar manualmente la ausencia del veterinario original.")
        if not fecha:
            errors.append("La fecha es obligatoria y debe ser válida.")
        elif fecha <= date.today():
            errors.append("La fecha debe ser futura.")

        cita = db.session.get(Cita, cita_id) if cita_id else None
        if not cita:
            errors.append("La cita seleccionada no existe.")
        else:
            if not _user_can_touch_cita(me, cita):
                errors.append("No tienes permisos para reasignar esa cita.")
            if cita.cancelada or cita.estado == "cancelada":
                errors.append("La cita seleccionada está cancelada.")
            if not _is_future_datetime(cita.fecha_hora):
                errors.append("Solo se pueden reasignar citas futuras.")
            if fecha and cita.fecha_hora.date() != fecha:
                errors.append("La fecha indicada no coincide con la fecha de la cita seleccionada.")

        if not veterinario_original_id:
            errors.append("Debes seleccionar veterinario original.")
        if not veterinario_nuevo_id:
            errors.append("Debes seleccionar veterinario nuevo.")
        if veterinario_original_id and veterinario_nuevo_id and veterinario_original_id == veterinario_nuevo_id:
            errors.append("El veterinario nuevo debe ser diferente al veterinario original.")

        if cita and veterinario_original_id and cita.veterinario_id != veterinario_original_id:
            errors.append("La cita no corresponde al veterinario original seleccionado.")

        if cita and veterinario_nuevo_id and not _is_veterinario_disponible(veterinario_nuevo_id, cita.fecha_hora, exclude_cita_id=cita.id):
            errors.append("El veterinario nuevo no está disponible en la fecha/hora de la cita.")

        if errors:
            for e in errors:
                flash(e, "error")
        else:
            cita.veterinario_id = veterinario_nuevo_id
            db.session.commit()
            flash("Cita reasignada correctamente.", "success")
            return redirect(url_for("citas.citas_index"))

    return render_template(
        "citas_reasignar.html",
        me=me,
        active_nav="citas",
        veterinarios=veterinarios,
        citas_futuras=citas_futuras,
        form_data=form_data,
    )
