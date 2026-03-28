from __future__ import annotations

from datetime import date, datetime, time, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy import and_, func
from sqlalchemy.orm import aliased

from app.extensions import db
from app.models import Cita, Mascota, RecordatorioCita, Rol, Usuario
from utils.auth_ui import get_current_user_from_api

citas_bp = Blueprint("citas", __name__)

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
REMINDER_OFFSET_OPTIONS = {24, 12, 2}
ABSENCE_REASON_OPTIONS = {
    "incapacidad": "Incapacidad",
    "vacaciones": "Vacaciones",
    "emergencia": "Emergencia",
    "otro": "Otro",
}


def _redirect_to_login():
    return redirect(url_for(LOGIN_GET_ENDPOINT))


def _require_login_or_redirect():
    if not session.get("access_token"):
        return _redirect_to_login()
    return None


def _get_me_or_logout():
    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return None
    return me


def _role_name(me) -> str:
    return (me.get("rol") or "").strip().lower()


def _allowed(me, hu_code: str) -> bool:
    return _role_name(me) in PERMISSIONS.get(hu_code, set())


def _redirect_client_to_portal(me):
    if _role_name(me) == ROLE_CLIENTE:
        return redirect(url_for("clientes.clientes_portal"))
    return None


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime_local(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def _parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _is_future_datetime(value: datetime) -> bool:
    return value > datetime.now()


def _not_canceled_clause():
    return and_(Cita.cancelada.is_(False), Cita.estado != "cancelada")


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
    return (
        db.session.query(Usuario)
        .join(Rol, Usuario.rol_id == Rol.id)
        .filter(func.lower(Rol.nombre) == nombre_rol.lower())
        .filter(Usuario.eliminado.is_(False), Usuario.activo.is_(True))
        .order_by(Usuario.nombre.asc())
        .all()
    )


def _get_mascotas_con_dueno_for_form(me):
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
            RecordatorioCita.anticipacion_horas.label("recordatorio_anticipacion_horas"),
            RecordatorioCita.programado_para.label("recordatorio_programado_para"),
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
    errors = []
    field_errors = {}

    fecha_hora_raw = form.get("fecha_hora") or ""
    motivo = (form.get("motivo") or "").strip()
    mascota_id = _parse_int(form.get("mascota_id"))
    veterinario_id = _parse_int(form.get("veterinario_id"))

    fecha_hora = _parse_datetime_local(fecha_hora_raw)
    cliente_id = None

    if not fecha_hora:
        field_errors["fecha_hora"] = "Este campo no puede estar vacío."
    else:
        today = date.today()
        if fecha_hora.date() <= today:
            field_errors["fecha_hora"] = "Debes seleccionar una fecha posterior a hoy."
        elif fecha_hora.year != today.year:
            field_errors["fecha_hora"] = "Solo puedes agendar citas dentro del año actual."

    if not motivo:
        field_errors["motivo"] = "Por favor ingresa el motivo de la cita para continuar."
    if not mascota_id:
        field_errors["mascota_id"] = "Este campo no puede estar vacío."
    if not veterinario_id:
        field_errors["veterinario_id"] = "Este campo no puede estar vacío."

    cliente = None
    mascota = None
    veterinario = None

    if mascota_id:
        mascota = db.session.get(Mascota, mascota_id)
        if not mascota:
            field_errors["mascota_id"] = "La mascota seleccionada no existe."
        else:
            cliente_id = mascota.dueno_id

    if cliente_id:
        cliente = (
            db.session.query(Usuario)
            .join(Rol, Usuario.rol_id == Rol.id)
            .filter(Usuario.id == cliente_id, Usuario.activo.is_(True), Usuario.eliminado.is_(False))
            .filter(func.lower(Rol.nombre) == ROLE_CLIENTE)
            .first()
        )
        if not cliente:
            field_errors["cliente_id"] = "El cliente asociado a la mascota no es válido."
    elif mascota_id:
        field_errors["cliente_id"] = "El cliente asociado a la mascota no es válido."

    if veterinario_id:
        veterinario = (
            db.session.query(Usuario)
            .join(Rol, Usuario.rol_id == Rol.id)
            .filter(Usuario.id == veterinario_id, Usuario.activo.is_(True), Usuario.eliminado.is_(False))
            .filter(func.lower(Rol.nombre) == ROLE_VETERINARIO)
            .first()
        )
        if not veterinario:
            field_errors["veterinario_id"] = "El veterinario seleccionado no es válido."

    if fecha_hora and veterinario_id:
        if not _is_veterinario_disponible(veterinario_id, fecha_hora, exclude_cita_id=editing_cita_id):
            field_errors["veterinario_id"] = "El veterinario no está disponible en la fecha/hora indicada."

    payload = {
        "fecha_hora": fecha_hora,
        "motivo": motivo,
        "mascota_id": mascota_id,
        "cliente_id": cliente_id,
        "veterinario_id": veterinario_id,
    }

    errors.extend(field_errors.values())
    return errors, field_errors, payload


def _default_form_data():
    return {
        "fecha_hora": "",
        "motivo": "",
        "mascota_id": "",
        "cliente_id": "",
        "cliente_nombre": "",
        "veterinario_id": "",
    }


def _owner_lookup(mascotas):
    # Crea un diccionario para resolver el dueño de una mascota en el formulario.
    return {
        str(mascota_id): {
            "cliente_id": str(dueno_id),
            "cliente_nombre": dueno_nombre,
        }
        for mascota_id, mascota_nombre, dueno_id, dueno_nombre in mascotas
    }


def _sync_form_client_from_pet(form_data, mascotas):
    owner_lookup = _owner_lookup(mascotas)
    owner = owner_lookup.get(str(form_data.get("mascota_id") or ""))
    if owner:
        form_data["cliente_id"] = owner["cliente_id"]
        form_data["cliente_nombre"] = owner["cliente_nombre"]
    else:
        form_data["cliente_id"] = ""
        form_data["cliente_nombre"] = ""
    return form_data


def _datetime_to_local_input(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M")


def _validate_cita_filters(fecha_inicio, fecha_fin):
    field_errors = {}
    today = date.today()

    if fecha_inicio and fecha_inicio > today:
        field_errors["fecha_inicio"] = "La fecha de inicio no puede ser posterior a hoy."

    if fecha_fin and fecha_inicio and fecha_fin < fecha_inicio:
        field_errors["fecha_fin"] = "La fecha de fin no puede ser previa a la fecha marcada como inicio."

    return field_errors


@citas_bp.get("/citas")
def citas_index():
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

    field_errors = _validate_cita_filters(fecha_inicio, fecha_fin)
    q = _build_cita_list_query(me)

    if not field_errors:
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
        field_errors=field_errors,
        can_create=_allowed(me, "hu005"),
        can_manage=_allowed(me, "hu006"),
        can_send_reminder=_allowed(me, "hu008"),
        now=datetime.now(),
    )


@citas_bp.route("/citas/nueva", methods=["GET", "POST"])
def citas_new():
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
        form_data = _sync_form_client_from_pet(form_data, mascotas)
        return render_template(
            "cita_form.html",
            me=me,
            active_nav="citas",
            mode="create",
            form_data=form_data,
            field_errors={},
            veterinarios=veterinarios,
            clientes=clientes,
            mascotas=mascotas,
        )
    errors, field_errors, payload = _validate_and_normalize_form(me, request.form)
    form_data = {
        "fecha_hora": request.form.get("fecha_hora") or "",
        "motivo": request.form.get("motivo") or "",
        "mascota_id": request.form.get("mascota_id") or "",
        "cliente_id": str(payload.get("cliente_id") or ""),
        "cliente_nombre": "",
        "veterinario_id": request.form.get("veterinario_id") or "",
    }
    form_data = _sync_form_client_from_pet(form_data, mascotas)

    if errors:
        return render_template(
            "cita_form.html",
            me=me,
            active_nav="citas",
            mode="create",
            form_data=form_data,
            field_errors=field_errors,
            veterinarios=veterinarios,
            clientes=clientes,
            mascotas=mascotas,
        )
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
            "cliente_nombre": "",
            "veterinario_id": str(cita.veterinario_id),
        }
        form_data = _sync_form_client_from_pet(form_data, mascotas)
        return render_template(
            "cita_form.html",
            me=me,
            active_nav="citas",
            mode="edit",
            cita_id=cita.id,
            form_data=form_data,
            field_errors={},
            veterinarios=veterinarios,
            clientes=clientes,
            mascotas=mascotas,
        )
    errors, field_errors, payload = _validate_and_normalize_form(me, request.form, editing_cita_id=cita.id)
    form_data = {
        "fecha_hora": request.form.get("fecha_hora") or "",
        "motivo": request.form.get("motivo") or "",
        "mascota_id": request.form.get("mascota_id") or "",
        "cliente_id": str(payload.get("cliente_id") or ""),
        "cliente_nombre": "",
        "veterinario_id": request.form.get("veterinario_id") or "",
    }
    form_data = _sync_form_client_from_pet(form_data, mascotas)

    if errors:
        return render_template(
            "cita_form.html",
            me=me,
            active_nav="citas",
            mode="edit",
            cita_id=cita.id,
            form_data=form_data,
            field_errors=field_errors,
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
def citas_schedule_reminder(cita_id: int):
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

    if cita.cancelada or cita.estado == "cancelada":
        flash("No se puede programar un recordatorio para una cita cancelada.", "error")
        return redirect(url_for("citas.citas_index"))

    if not _is_future_datetime(cita.fecha_hora):
        flash("Solo se pueden programar recordatorios para citas futuras.", "error")
        return redirect(url_for("citas.citas_index"))

    anticipacion_horas = _parse_int(request.form.get("anticipacion_horas"))
    if anticipacion_horas not in REMINDER_OFFSET_OPTIONS:
        flash("Debes seleccionar una anticipación válida para el recordatorio.", "error")
        return redirect(url_for("citas.citas_index"))

    programado_para = cita.fecha_hora - timedelta(hours=anticipacion_horas)
    if programado_para <= datetime.now():
        flash("La anticipación elegida ya no es válida para esta cita. Selecciona una opción menor.", "error")
        return redirect(url_for("citas.citas_index"))

    # Verificamos que el cliente tenga un correo disponible para el recordatorio.
    cliente = db.session.get(Usuario, cita.cliente_id)
    if not cliente or not (cliente.correo or "").strip():
        flash("No se puede programar: el cliente no tiene correo registrado.", "error")
        return redirect(url_for("citas.citas_index"))

    # Buscamos o creamos el registro que controlará el estado del recordatorio.
    reminder = db.session.query(RecordatorioCita).filter(RecordatorioCita.cita_id == cita.id).first()
    if not reminder:
        reminder = RecordatorioCita(cita_id=cita.id, estado="programado", confirmado=False)
        db.session.add(reminder)

    reminder.estado = "programado"
    reminder.enviado_en = None
    reminder.anticipacion_horas = anticipacion_horas
    reminder.programado_para = programado_para
    reminder.confirmado = False
    reminder.confirmado_en = None
    reminder.token_confirmacion = None
    db.session.commit()

    flash(
        f"Recordatorio programado correctamente para {programado_para.strftime('%Y-%m-%d %H:%M')} "
        f"({anticipacion_horas} horas antes).",
        "success",
    )
    return redirect(url_for("citas.citas_index"))


def _daily_slots(target_date: date):
    slots = []
    for hour in range(9, 19):
        slots.append(datetime.combine(target_date, time(hour=hour, minute=0)))
    return slots


def _slot_label(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def _next_available_suggestions(veterinario_id: int, base_dt: datetime, count: int = 5):
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
        "motivo_ausencia": "",
    }
    field_errors = {}

    if request.method == "POST":
        fecha = _parse_date(request.form.get("fecha") or "")
        cita_id = _parse_int(request.form.get("cita_id"))
        veterinario_original_id = _parse_int(request.form.get("veterinario_original_id"))
        veterinario_nuevo_id = _parse_int(request.form.get("veterinario_nuevo_id"))
        motivo_ausencia = (request.form.get("motivo_ausencia") or "").strip().lower()

        form_data = {
            "fecha": request.form.get("fecha") or "",
            "cita_id": str(cita_id or ""),
            "veterinario_original_id": str(veterinario_original_id or ""),
            "veterinario_nuevo_id": str(veterinario_nuevo_id or ""),
            "motivo_ausencia": motivo_ausencia,
        }

        errors = []

        if not fecha:
            field_errors["fecha"] = "Debes seleccionar la fecha de la cita."
        elif fecha <= date.today():
            field_errors["fecha"] = "La fecha debe ser futura."
        if not motivo_ausencia:
            field_errors["motivo_ausencia"] = "Debes seleccionar un motivo de ausencia."
        elif motivo_ausencia not in ABSENCE_REASON_OPTIONS:
            field_errors["motivo_ausencia"] = "El motivo de ausencia seleccionado no es válido."

        cita = db.session.get(Cita, cita_id) if cita_id else None
        if not cita:
            field_errors["cita_id"] = "Debes seleccionar la cita por reasignar."
        else:
            if not _user_can_touch_cita(me, cita):
                errors.append("No tienes permisos para reasignar esa cita.")
            if cita.cancelada or cita.estado == "cancelada":
                errors.append("La cita seleccionada está cancelada.")
            if not _is_future_datetime(cita.fecha_hora):
                errors.append("Solo se pueden reasignar citas futuras.")
            if fecha and cita.fecha_hora.date() != fecha:
                field_errors["cita_id"] = "La fecha indicada no coincide con la fecha de la cita seleccionada."

        if not veterinario_original_id:
            field_errors["veterinario_original_id"] = "Debes seleccionar el veterinario original."
        if not veterinario_nuevo_id:
            field_errors["veterinario_nuevo_id"] = "Debes seleccionar el veterinario nuevo."
        if veterinario_original_id and veterinario_nuevo_id and veterinario_original_id == veterinario_nuevo_id:
            field_errors["veterinario_nuevo_id"] = "El veterinario nuevo debe ser diferente al veterinario original."

        if cita and veterinario_original_id and cita.veterinario_id != veterinario_original_id:
            field_errors["veterinario_original_id"] = "La cita no corresponde al veterinario original seleccionado."

        if cita and veterinario_nuevo_id and not _is_veterinario_disponible(veterinario_nuevo_id, cita.fecha_hora, exclude_cita_id=cita.id):
            field_errors["veterinario_nuevo_id"] = "El veterinario nuevo no está disponible en la fecha/hora de la cita."

        filtered_q = citas_q
        if fecha:
            filtered_q = filtered_q.filter(
                Cita.fecha_hora >= datetime.combine(fecha, time.min),
                Cita.fecha_hora <= datetime.combine(fecha, time.max),
            )
        if veterinario_original_id:
            filtered_q = filtered_q.filter(Cita.veterinario_id == veterinario_original_id)
        citas_futuras = filtered_q.all()

        errors.extend(field_errors.values())
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            cita.veterinario_id = veterinario_nuevo_id
            db.session.commit()
            vet_original = db.session.get(Usuario, veterinario_original_id)
            vet_nuevo = db.session.get(Usuario, veterinario_nuevo_id)
            flash(
                "Cita reasignada correctamente. "
                f"La cita #{cita.id} pasó de "
                f"{(vet_original.nombre if vet_original else 'Veterinario original')} a "
                f"{(vet_nuevo.nombre if vet_nuevo else 'Veterinario nuevo')}.",
                "success",
            )
            return redirect(url_for("citas.citas_index"))

    return render_template(
        "citas_reasignar.html",
        me=me,
        active_nav="citas",
        veterinarios=veterinarios,
        citas_futuras=citas_futuras,
        form_data=form_data,
        field_errors=field_errors,
        absence_reason_options=ABSENCE_REASON_OPTIONS,
    )
