"""Gestión de citas, recordatorios y reasignaciones de agenda."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy import and_, func
from sqlalchemy.orm import aliased

from app.extensions import db
from app.followups import (
    enviar_seguimiento_ahora,
    eliminar_seguimiento,
    fecha_hora_seguimiento_a_formato,
    guardar_seguimiento,
    obtener_mapa_seguimientos_por_ids,
    obtener_seguimiento,
    usuario_puede_programar_seguimiento,
    validar_programacion_seguimiento,
)
from app.models import Cita, Mascota, RecordatorioCita, Rol, Usuario
from utils.auth_ui import get_current_user_from_api

citas_bp = Blueprint("citas", __name__)

LOGIN_GET_ENDPOINT = "pages.pagina_inicio_sesion"

ROLE_ADMIN = "administrador"
ROLE_CLIENTE = "cliente"
ROLE_VETERINARIO = "veterinario"

PERMISSIONS = {
    "hu005": {ROLE_ADMIN, ROLE_CLIENTE, ROLE_VETERINARIO},
    "hu006": {ROLE_ADMIN, ROLE_CLIENTE, ROLE_VETERINARIO},
    "hu007": {ROLE_ADMIN, ROLE_CLIENTE, ROLE_VETERINARIO},
    "hu008": {ROLE_ADMIN, ROLE_CLIENTE},
    "hu009": {ROLE_ADMIN, ROLE_CLIENTE, ROLE_VETERINARIO},
    "hu010": {ROLE_ADMIN, ROLE_CLIENTE},
}
REMINDER_OFFSET_OPTIONS = {24, 12, 2}
REMINDER_DEMO_OPTION = "demo_10s"
ABSENCE_REASON_OPTIONS = {
    "incapacidad": "Incapacidad",
    "vacaciones": "Vacaciones",
    "emergencia": "Emergencia",
    "otro": "Otro",
}


def _redirigir_a_inicio_sesion():
    """Envía al usuario a la pantalla de login cuando no hay sesión válida."""
    return redirect(url_for(LOGIN_GET_ENDPOINT))


def _requiere_inicio_sesion_o_redirige():
    """Valida si la sesión existe antes de continuar con la vista solicitada."""
    if not session.get("access_token"):
        return _redirigir_a_inicio_sesion()
    return None


def _obtener_usuario_o_cerrar_sesion():
    """Recupera el usuario actual desde la API y limpia sesión si ya no es válido."""
    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return None
    return me


def _nombre_rol(me) -> str:
    """Normaliza el nombre del rol del usuario actual."""
    return (me.get("rol") or "").strip().lower()


def _permitido(me, hu_code: str) -> bool:
    """Verifica si el rol actual tiene permiso para una historia de usuario dada."""
    return _nombre_rol(me) in PERMISSIONS.get(hu_code, set())


def _redirigir_cliente_a_portal(me):
    """Redirige al portal del cliente cuando intenta abrir vistas administrativas."""
    if _nombre_rol(me) == ROLE_CLIENTE:
        return redirect(url_for("clientes.clientes_portal"))
    return None


def _parsear_entero(value):
    """Convierte valores de formulario a entero cuando es posible."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parsear_fecha_hora_local(value: str):
    """Convierte un `datetime-local` del formulario a `datetime` de Python."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def _parsear_fecha(value: str):
    """Convierte una fecha de formulario a un objeto `date`."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _es_fecha_hora_futura(value: datetime) -> bool:
    """Indica si una cita quedó programada en una fecha futura."""
    return value > datetime.now()


def _condicion_no_cancelada():
    """Devuelve la condición SQL para filtrar citas que siguen vigentes."""
    return and_(Cita.cancelada.is_(False), Cita.estado != "cancelada")


def _es_veterinario_disponible(veterinario_id: int, fecha_hora: datetime, exclude_cita_id: int | None = None) -> bool:
    """Función para es veterinario disponible."""
    # Revisa si un veterinario está libre en una fecha y hora específicas.
    q = db.session.query(Cita.id).filter(
        Cita.veterinario_id == veterinario_id,
        Cita.fecha_hora == fecha_hora,
        _condicion_no_cancelada(),
    )
    if exclude_cita_id is not None:
        q = q.filter(Cita.id != exclude_cita_id)
    return q.first() is None


def _obtener_usuarios_por_rol(nombre_rol: str):
    """Función para obtener usuarios por rol."""
    return (
        db.session.query(Usuario)
        .join(Rol, Usuario.rol_id == Rol.id)
        .filter(func.lower(Rol.nombre) == nombre_rol.lower())
        .filter(Usuario.eliminado.is_(False), Usuario.activo.is_(True))
        .order_by(Usuario.nombre.asc())
        .all()
    )


def _obtener_mascotas_con_dueno_para_formulario(me):
    """Función para obtener mascotas con dueno para formulario."""
    role = _nombre_rol(me)
    q = (
        db.session.query(Mascota.id, Mascota.nombre, Mascota.dueno_id, Usuario.nombre.label("dueno_nombre"))
        .join(Usuario, Mascota.dueno_id == Usuario.id)
        .filter(
            Usuario.eliminado.is_(False),
            Mascota.estado == "activa",
        )
    )
    if role == ROLE_CLIENTE:
        q = q.filter(Mascota.dueno_id == int(me["id"]))
    return q.order_by(Mascota.nombre.asc()).all()


def _usuario_puede_modificar_cita(me, cita: Cita) -> bool:
    """Función para usuario puede modificar cita."""
    role = _nombre_rol(me)
    me_id = _parsear_entero(me.get("id"))
    if role == ROLE_ADMIN:
        return True
    if role == ROLE_CLIENTE and me_id is not None:
        return cita.cliente_id == me_id
    if role == ROLE_VETERINARIO and me_id is not None:
        return cita.veterinario_id == me_id
    return False


def _construir_consulta_lista_citas(me):
    """Función para construir consulta lista citas."""
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

    role = _nombre_rol(me)
    me_id = _parsear_entero(me.get("id"))
    if role == ROLE_CLIENTE and me_id is not None:
        q = q.filter(Cita.cliente_id == me_id)
    elif role == ROLE_VETERINARIO and me_id is not None:
        q = q.filter(Cita.veterinario_id == me_id)

    return q


def _validar_y_normalizar_formulario(me, form, *, editing_cita_id: int | None = None):
    """Función para validar y normalizar formulario."""
    errors = []
    errores_campo = {}

    fecha_hora_raw = form.get("fecha_hora") or ""
    motivo = (form.get("motivo") or "").strip()
    mascota_id = _parsear_entero(form.get("mascota_id"))
    veterinario_id = _parsear_entero(form.get("veterinario_id"))

    fecha_hora = _parsear_fecha_hora_local(fecha_hora_raw)
    cliente_id = None

    if not fecha_hora:
        errores_campo["fecha_hora"] = "Este campo no puede estar vacío."
    else:
        today = date.today()
        if fecha_hora.date() <= today:
            errores_campo["fecha_hora"] = "Debes seleccionar una fecha posterior a hoy."
        elif fecha_hora.year != today.year:
            errores_campo["fecha_hora"] = "Solo puedes agendar citas dentro del año actual."

    if not motivo:
        errores_campo["motivo"] = "Por favor ingresa el motivo de la cita para continuar."
    if not mascota_id:
        errores_campo["mascota_id"] = "Este campo no puede estar vacío."
    if not veterinario_id:
        errores_campo["veterinario_id"] = "Este campo no puede estar vacío."

    cliente = None
    mascota = None
    veterinario = None

    if mascota_id:
        mascota = db.session.get(Mascota, mascota_id)
        if not mascota:
            errores_campo["mascota_id"] = "La mascota seleccionada no existe."
        elif mascota.estado != "activa":
            errores_campo["mascota_id"] = "No se pueden agendar citas para mascotas inactivas."
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
            errores_campo["cliente_id"] = "El cliente asociado a la mascota no es válido."
    elif mascota_id:
        errores_campo["cliente_id"] = "El cliente asociado a la mascota no es válido."

    if veterinario_id:
        veterinario = (
            db.session.query(Usuario)
            .join(Rol, Usuario.rol_id == Rol.id)
            .filter(Usuario.id == veterinario_id, Usuario.activo.is_(True), Usuario.eliminado.is_(False))
            .filter(func.lower(Rol.nombre) == ROLE_VETERINARIO)
            .first()
        )
        if not veterinario:
            errores_campo["veterinario_id"] = "El veterinario seleccionado no es válido."

    if fecha_hora and veterinario_id:
        if not _es_veterinario_disponible(veterinario_id, fecha_hora, exclude_cita_id=editing_cita_id):
            errores_campo["veterinario_id"] = "El veterinario no está disponible en la fecha/hora indicada."

    payload = {
        "fecha_hora": fecha_hora,
        "motivo": motivo,
        "mascota_id": mascota_id,
        "cliente_id": cliente_id,
        "veterinario_id": veterinario_id,
        "veterinario": veterinario,
    }

    errors.extend(errores_campo.values())
    return errors, errores_campo, payload


def _default_datos_formulario():
    """Función para default datos formulario."""
    return {
        "fecha_hora": "",
        "motivo": "",
        "mascota_id": "",
        "cliente_id": "",
        "cliente_nombre": "",
        "veterinario_id": "",
        "cita_requiere_seguimiento": False,
        "cita_seguimiento_programado_para": "",
    }


def _mapa_duenos(mascotas):
    """Función para mapa duenos."""
    # Crea un diccionario para resolver el dueño de una mascota en el formulario.
    return {
        str(mascota_id): {
            "cliente_id": str(dueno_id),
            "cliente_nombre": dueno_nombre,
        }
        for mascota_id, mascota_nombre, dueno_id, dueno_nombre in mascotas
    }


def _sincronizar_cliente_formulario_desde_mascota(datos_formulario, mascotas):
    """Función para sincronizar cliente formulario desde mascota."""
    owner_lookup = _mapa_duenos(mascotas)
    owner = owner_lookup.get(str(datos_formulario.get("mascota_id") or ""))
    if owner:
        datos_formulario["cliente_id"] = owner["cliente_id"]
        datos_formulario["cliente_nombre"] = owner["cliente_nombre"]
    else:
        datos_formulario["cliente_id"] = ""
        datos_formulario["cliente_nombre"] = ""
    return datos_formulario


def _construir_datos_seguimiento_cita(form=None, seguimiento=None):
    """Función para construir datos seguimiento cita."""
    # Función de datos de seguimiento.
    form = form or {}
    if form:
        return {
            "cita_requiere_seguimiento": (form.get("cita_requiere_seguimiento") or "").strip().lower() in {"1", "true", "on", "yes"},
            "cita_seguimiento_programado_para": (form.get("cita_seguimiento_programado_para") or "").strip(),
        }
    return {
        "cita_requiere_seguimiento": seguimiento is not None,
        "cita_seguimiento_programado_para": fecha_hora_seguimiento_a_formato(seguimiento.programado_para if seguimiento else None),
    }


def _destinatarios_recordatorio(cliente: Usuario | None, veterinario: Usuario | None):
    """Función para destinatarios recordatorio."""
    # Función de recordatorio automático.
    destinatarios = []
    vistos = set()
    for usuario in (cliente, veterinario):
        correo = ((usuario.correo if usuario else "") or "").strip().lower()
        if correo and correo not in vistos:
            destinatarios.append(correo)
            vistos.add(correo)
    return destinatarios


def _descripcion_recordatorio(recordatorio: RecordatorioCita | None) -> str:
    """Función para descripcion recordatorio."""
    # Función de recordatorio automático.
    if not recordatorio:
        return ""
    if recordatorio.anticipacion_horas == 0:
        return "Demo 10 segundos"
    if recordatorio.anticipacion_horas:
        return f"{recordatorio.anticipacion_horas} horas antes"
    return "Programado"


def _redirigir_despues_recordatorio(me):
    """Función para redirigir despues recordatorio."""
    # Función de recordatorio automático.
    if _nombre_rol(me) == ROLE_CLIENTE:
        return redirect(url_for("clientes.clientes_portal"))
    return redirect(url_for("citas.citas_lista"))


def sincronizar_recordatorios_programados():
    """Función para sincronizar recordatorios programados."""
    # Función de recordatorio automático.
    from app.routes.chat import _enviar_email_smtp

    cliente = aliased(Usuario)
    veterinario = aliased(Usuario)
    now = datetime.now()
    rows = (
        db.session.query(
            RecordatorioCita,
            Cita,
            Mascota.nombre.label("mascota_nombre"),
            cliente,
            veterinario,
        )
        .join(Cita, RecordatorioCita.cita_id == Cita.id)
        .join(Mascota, Cita.mascota_id == Mascota.id)
        .join(cliente, Cita.cliente_id == cliente.id)
        .join(veterinario, Cita.veterinario_id == veterinario.id)
        .filter(RecordatorioCita.estado == "programado")
        .filter(RecordatorioCita.programado_para.isnot(None))
        .filter(RecordatorioCita.programado_para <= now)
        .filter(Cita.cancelada.is_(False), Cita.estado != "cancelada")
        .filter(Cita.fecha_hora > now)
        .filter(cliente.activo.is_(True), cliente.eliminado.is_(False))
        .filter(veterinario.activo.is_(True), veterinario.eliminado.is_(False))
        .order_by(RecordatorioCita.programado_para.asc(), RecordatorioCita.id.asc())
        .all()
    )

    for reminder, cita, mascota_nombre, cliente_row, veterinario_row in rows:
        destinatarios = _destinatarios_recordatorio(cliente_row, veterinario_row)
        if len(destinatarios) < 2:
            continue

        subject = "Recordatorio de cita - CIVE"
        body = (
            "Este es un recordatorio automático de una cita programada en CIVE.\n\n"
            f"Fecha y hora: {cita.fecha_hora.strftime('%Y-%m-%d %H:%M')}\n"
            f"Mascota: {mascota_nombre}\n"
            f"Cliente: {cliente_row.nombre}\n"
            f"Veterinario: {veterinario_row.nombre}\n"
            f"Motivo: {cita.motivo or 'Sin motivo especificado'}\n"
            f"Anticipación: {_descripcion_recordatorio(reminder)}\n\n"
            "Clínica CIVE"
        )

        sent_ok, _ = _enviar_email_smtp(", ".join(destinatarios), subject, body)
        if not sent_ok:
            continue

        reminder.estado = "enviado"
        reminder.enviado_en = now
        reminder.token_confirmacion = None

    db.session.commit()


def _fecha_hora_a_entrada_local(dt: datetime | None) -> str:
    """Función para fecha hora a entrada local."""
    if not dt:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M")


def _validar_filtros_citas(fecha_inicio, fecha_fin):
    """Función para validar filtros citas."""
    errores_campo = {}
    today = date.today()

    if fecha_inicio and fecha_inicio > today:
        errores_campo["fecha_inicio"] = "La fecha de inicio no puede ser posterior a hoy."

    if fecha_fin and fecha_inicio and fecha_fin < fecha_inicio:
        errores_campo["fecha_fin"] = "La fecha de fin no puede ser previa a la fecha marcada como inicio."

    return errores_campo


@citas_bp.get("/citas")
def citas_lista():
    """Función para citas lista."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    client_redirect = _redirigir_cliente_a_portal(me)
    if client_redirect:
        return client_redirect

    if not _permitido(me, "hu007"):
        return render_template("acceso_denegado.html", me=me), 403

    estado = (request.args.get("estado") or "").strip().lower()
    fecha_inicio = _parsear_fecha(request.args.get("fecha_inicio") or "")
    fecha_fin = _parsear_fecha(request.args.get("fecha_fin") or "")
    veterinario_id = _parsear_entero(request.args.get("veterinario_id"))
    orden = (request.args.get("orden") or "asc").strip().lower()
    if orden not in {"asc", "desc"}:
        orden = "asc"

    errores_campo = _validar_filtros_citas(fecha_inicio, fecha_fin)
    q = _construir_consulta_lista_citas(me)

    if not errores_campo:
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
    veterinarios = _obtener_usuarios_por_rol(ROLE_VETERINARIO)
    followup_map = obtener_mapa_seguimientos_por_ids("cita", [row[0].id for row in rows])

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
        errores_campo=errores_campo,
        can_create=_permitido(me, "hu005"),
        can_manage=_permitido(me, "hu006"),
        can_send_reminder=_permitido(me, "hu008"),
        can_add_to_expediente=_nombre_rol(me) in {ROLE_ADMIN, ROLE_VETERINARIO},
        followup_map=followup_map,
        now=datetime.now(),
    )


@citas_bp.post("/citas/<int:cita_id>/seguimiento/recordar-ahora")
def citas_recordar_seguimiento_ahora(cita_id: int):
    """Función para citas recordar seguimiento ahora."""
    # Botón temporal de demostración de seguimiento.
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not usuario_puede_programar_seguimiento(me):
        return render_template("acceso_denegado.html", me=me), 403

    seguimiento = obtener_seguimiento("cita", cita_id, "cita")
    if not seguimiento:
        flash("La cita no tiene seguimiento programado.", "error")
        return redirect(url_for("citas.citas_lista"))

    sent_ok, sent_error = enviar_seguimiento_ahora(seguimiento.id)
    if not sent_ok:
        flash(sent_error or "No fue posible enviar el seguimiento.", "error")
        return redirect(url_for("citas.citas_lista"))

    db.session.commit()
    flash("Seguimiento enviado correctamente por correo.", "success")
    return redirect(url_for("citas.citas_lista"))


@citas_bp.route("/citas/nueva", methods=["GET", "POST"])
def citas_nueva():
    """Función para citas nueva."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    client_redirect = _redirigir_cliente_a_portal(me)
    if client_redirect:
        return client_redirect

    if not _permitido(me, "hu005"):
        return render_template("acceso_denegado.html", me=me), 403

    veterinarios = _obtener_usuarios_por_rol(ROLE_VETERINARIO)
    clientes = _obtener_usuarios_por_rol(ROLE_CLIENTE)
    mascotas = _obtener_mascotas_con_dueno_para_formulario(me)

    if request.method == "GET":
        datos_formulario = _default_datos_formulario()
        datos_formulario = _sincronizar_cliente_formulario_desde_mascota(datos_formulario, mascotas)
        datos_formulario.update(_construir_datos_seguimiento_cita())
        return render_template(
            "cita_form.html",
            me=me,
            active_nav="citas",
            mode="create",
            datos_formulario=datos_formulario,
            errores_campo={},
            veterinarios=veterinarios,
            clientes=clientes,
            mascotas=mascotas,
            can_schedule_followup=usuario_puede_programar_seguimiento(me),
        )
    errors, errores_campo, payload = _validar_y_normalizar_formulario(me, request.form)
    datos_formulario = {
        "fecha_hora": request.form.get("fecha_hora") or "",
        "motivo": request.form.get("motivo") or "",
        "mascota_id": request.form.get("mascota_id") or "",
        "cliente_id": str(payload.get("cliente_id") or ""),
        "cliente_nombre": "",
        "veterinario_id": request.form.get("veterinario_id") or "",
    }
    datos_formulario.update(_construir_datos_seguimiento_cita(request.form))
    datos_formulario = _sincronizar_cliente_formulario_desde_mascota(datos_formulario, mascotas)

    seguimiento_cita = _construir_datos_seguimiento_cita(request.form)
    if usuario_puede_programar_seguimiento(me):
        seguimiento_result = validar_programacion_seguimiento(
            requiere=seguimiento_cita["cita_requiere_seguimiento"],
            programado_para_raw=seguimiento_cita["cita_seguimiento_programado_para"],
            veterinario=payload.get("veterinario"),
            errores_campo=errores_campo,
            error_field="cita_seguimiento_programado_para",
        )
        errors = list(errores_campo.values())
    else:
        seguimiento_result = {"requiere": False, "programado_para": None}

    if errors:
        return render_template(
            "cita_form.html",
            me=me,
            active_nav="citas",
            mode="create",
            datos_formulario=datos_formulario,
            errores_campo=errores_campo,
            veterinarios=veterinarios,
            clientes=clientes,
            mascotas=mascotas,
            can_schedule_followup=usuario_puede_programar_seguimiento(me),
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
    db.session.flush()
    if seguimiento_result["requiere"]:
        guardar_seguimiento(
            origen_tipo="cita",
            origen_id=cita.id,
            evento_tipo="cita",
            mascota_id=payload["mascota_id"],
            veterinario_id=payload["veterinario_id"],
            programado_para=seguimiento_result["programado_para"],
            descripcion=f"Seguimiento de cita para {payload['motivo'][:120]}",
        )
    db.session.commit()

    flash("Cita creada correctamente.", "success")
    return redirect(url_for("citas.citas_lista"))


@citas_bp.route("/citas/<int:cita_id>/editar", methods=["GET", "POST"])
def citas_editar(cita_id: int):
    """Función para citas editar."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    client_redirect = _redirigir_cliente_a_portal(me)
    if client_redirect:
        return client_redirect

    if not _permitido(me, "hu006"):
        return render_template("acceso_denegado.html", me=me), 403

    cita = db.session.get(Cita, cita_id)
    if not cita:
        flash("La cita no existe.", "error")
        return redirect(url_for("citas.citas_lista"))

    if not _usuario_puede_modificar_cita(me, cita):
        return render_template("acceso_denegado.html", me=me), 403

    if cita.cancelada or cita.estado == "cancelada":
        flash("No se puede modificar una cita cancelada.", "error")
        return redirect(url_for("citas.citas_lista"))

    if not _es_fecha_hora_futura(cita.fecha_hora):
        flash("Solo se pueden modificar citas futuras.", "error")
        return redirect(url_for("citas.citas_lista"))

    veterinarios = _obtener_usuarios_por_rol(ROLE_VETERINARIO)
    clientes = _obtener_usuarios_por_rol(ROLE_CLIENTE)
    mascotas = _obtener_mascotas_con_dueno_para_formulario(me)

    if request.method == "GET":
        seguimiento_cita = obtener_seguimiento("cita", cita.id, "cita")
        datos_formulario = {
            "fecha_hora": _fecha_hora_a_entrada_local(cita.fecha_hora),
            "motivo": cita.motivo or "",
            "mascota_id": str(cita.mascota_id),
            "cliente_id": str(cita.cliente_id),
            "cliente_nombre": "",
            "veterinario_id": str(cita.veterinario_id),
        }
        datos_formulario.update(_construir_datos_seguimiento_cita(seguimiento=seguimiento_cita))
        datos_formulario = _sincronizar_cliente_formulario_desde_mascota(datos_formulario, mascotas)
        return render_template(
            "cita_form.html",
            me=me,
            active_nav="citas",
            mode="edit",
            cita_id=cita.id,
            datos_formulario=datos_formulario,
            errores_campo={},
            veterinarios=veterinarios,
            clientes=clientes,
            mascotas=mascotas,
            can_schedule_followup=usuario_puede_programar_seguimiento(me),
        )
    errors, errores_campo, payload = _validar_y_normalizar_formulario(me, request.form, editing_cita_id=cita.id)
    datos_formulario = {
        "fecha_hora": request.form.get("fecha_hora") or "",
        "motivo": request.form.get("motivo") or "",
        "mascota_id": request.form.get("mascota_id") or "",
        "cliente_id": str(payload.get("cliente_id") or ""),
        "cliente_nombre": "",
        "veterinario_id": request.form.get("veterinario_id") or "",
    }
    datos_formulario.update(_construir_datos_seguimiento_cita(request.form))
    datos_formulario = _sincronizar_cliente_formulario_desde_mascota(datos_formulario, mascotas)

    seguimiento_cita = _construir_datos_seguimiento_cita(request.form)
    if usuario_puede_programar_seguimiento(me):
        seguimiento_result = validar_programacion_seguimiento(
            requiere=seguimiento_cita["cita_requiere_seguimiento"],
            programado_para_raw=seguimiento_cita["cita_seguimiento_programado_para"],
            veterinario=payload.get("veterinario"),
            errores_campo=errores_campo,
            error_field="cita_seguimiento_programado_para",
        )
        errors = list(errores_campo.values())
    else:
        seguimiento_result = {"requiere": False, "programado_para": None}

    if errors:
        return render_template(
            "cita_form.html",
            me=me,
            active_nav="citas",
            mode="edit",
            cita_id=cita.id,
            datos_formulario=datos_formulario,
            errores_campo=errores_campo,
            veterinarios=veterinarios,
            clientes=clientes,
            mascotas=mascotas,
            can_schedule_followup=usuario_puede_programar_seguimiento(me),
        )

    cita.fecha_hora = payload["fecha_hora"]
    cita.motivo = payload["motivo"]
    cita.mascota_id = payload["mascota_id"]
    cita.cliente_id = payload["cliente_id"]
    cita.veterinario_id = payload["veterinario_id"]

    if cita.estado == "cancelada":
        cita.estado = "pendiente"
        cita.cancelada = False

    if seguimiento_result["requiere"]:
        guardar_seguimiento(
            origen_tipo="cita",
            origen_id=cita.id,
            evento_tipo="cita",
            mascota_id=payload["mascota_id"],
            veterinario_id=payload["veterinario_id"],
            programado_para=seguimiento_result["programado_para"],
            descripcion=f"Seguimiento de cita para {payload['motivo'][:120]}",
        )
    else:
        eliminar_seguimiento(origen_tipo="cita", origen_id=cita.id, evento_tipo="cita")

    db.session.commit()
    flash("Cita modificada correctamente.", "success")
    return redirect(url_for("citas.citas_lista"))


@citas_bp.post("/citas/<int:cita_id>/cancelar")
def citas_cancelar(cita_id: int):
    """Función para citas cancelar."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _permitido(me, "hu006"):
        return render_template("acceso_denegado.html", me=me), 403

    cita = db.session.get(Cita, cita_id)
    if not cita:
        flash("La cita no existe.", "error")
        return redirect(url_for("citas.citas_lista"))

    if not _usuario_puede_modificar_cita(me, cita):
        return render_template("acceso_denegado.html", me=me), 403

    if not _es_fecha_hora_futura(cita.fecha_hora):
        flash("Solo se pueden cancelar citas futuras.", "error")
        return redirect(url_for("citas.citas_lista"))

    cita.estado = "cancelada"
    cita.cancelada = True
    db.session.commit()

    flash("Cita cancelada correctamente.", "success")
    if _nombre_rol(me) == ROLE_CLIENTE:
        return redirect(url_for("clientes.clientes_portal"))
    return redirect(url_for("citas.citas_lista"))


@citas_bp.post("/citas/<int:cita_id>/recordatorio")
def citas_programar_recordatorio(cita_id: int):
    """Función para citas programar recordatorio."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _permitido(me, "hu008"):
        return render_template("acceso_denegado.html", me=me), 403

    cita = db.session.get(Cita, cita_id)
    if not cita:
        flash("La cita no existe.", "error")
        return _redirigir_despues_recordatorio(me)

    if not _usuario_puede_modificar_cita(me, cita):
        return render_template("acceso_denegado.html", me=me), 403

    if cita.cancelada or cita.estado == "cancelada":
        flash("No se puede programar un recordatorio para una cita cancelada.", "error")
        return _redirigir_despues_recordatorio(me)

    if not _es_fecha_hora_futura(cita.fecha_hora):
        flash("Solo se pueden programar recordatorios para citas futuras.", "error")
        return _redirigir_despues_recordatorio(me)

    anticipacion_raw = (request.form.get("anticipacion_horas") or "").strip()
    if anticipacion_raw == REMINDER_DEMO_OPTION:
        if _nombre_rol(me) != ROLE_CLIENTE:
            flash("La opción de demostración solo está disponible para clientes.", "error")
            return _redirigir_despues_recordatorio(me)
        anticipacion_horas = 0
        programado_para = datetime.now() + timedelta(seconds=10)
    else:
        anticipacion_horas = _parsear_entero(anticipacion_raw)
        if anticipacion_horas not in REMINDER_OFFSET_OPTIONS:
            flash("Debes seleccionar una anticipación válida para el recordatorio.", "error")
            return _redirigir_despues_recordatorio(me)

        programado_para = cita.fecha_hora - timedelta(hours=anticipacion_horas)
        if programado_para <= datetime.now():
            flash("La anticipación elegida ya no es válida para esta cita. Selecciona una opción menor.", "error")
            return _redirigir_despues_recordatorio(me)

    # Verificamos que el cliente tenga un correo disponible para el recordatorio.
    cliente = db.session.get(Usuario, cita.cliente_id)
    veterinario = db.session.get(Usuario, cita.veterinario_id)
    if not cliente or not (cliente.correo or "").strip():
        flash("No se puede programar: el cliente no tiene correo registrado.", "error")
        return _redirigir_despues_recordatorio(me)
    if not veterinario or not (veterinario.correo or "").strip():
        flash("No se puede programar: el veterinario no tiene correo registrado.", "error")
        return _redirigir_despues_recordatorio(me)

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
        f"({_descripcion_recordatorio(reminder)}).",
        "success",
    )
    return _redirigir_despues_recordatorio(me)


def _bloques_diarios(target_date: date):
    """Función para bloques diarios."""
    slots = []
    for hour in range(9, 19):
        slots.append(datetime.combine(target_date, time(hour=hour, minute=0)))
    return slots


def _etiqueta_bloque(dt: datetime) -> str:
    """Función para etiqueta bloque."""
    return dt.strftime("%Y-%m-%d %H:%M")


def _siguientes_sugerencias_disponibles(veterinario_id: int, base_dt: datetime, count: int = 5):
    """Función para siguientes sugerencias disponibles."""
    suggestions = []
    cursor_date = base_dt.date()

    for day_offset in range(0, 10):
        day = cursor_date + timedelta(days=day_offset)
        if day < date.today():
            continue

        for slot in _bloques_diarios(day):
            if slot <= datetime.now():
                continue
            if _es_veterinario_disponible(veterinario_id, slot):
                suggestions.append(slot)
            if len(suggestions) >= count:
                return suggestions

    return suggestions


@citas_bp.route("/citas/disponibilidad", methods=["GET", "POST"])
def citas_disponibilidad():
    """Función para citas disponibilidad."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    client_redirect = _redirigir_cliente_a_portal(me)
    if client_redirect:
        return client_redirect

    if not _permitido(me, "hu009"):
        return render_template("acceso_denegado.html", me=me), 403

    veterinarios = _obtener_usuarios_por_rol(ROLE_VETERINARIO)
    result = None
    datos_formulario = {"veterinario_id": "", "fecha": ""}

    if request.method == "POST":
        veterinario_id = _parsear_entero(request.form.get("veterinario_id"))
        fecha = _parsear_fecha(request.form.get("fecha") or "")
        datos_formulario = {
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
            slots = _bloques_diarios(fecha)
            ocupados = {
                row[0]
                for row in db.session.query(Cita.fecha_hora)
                .filter(
                    Cita.veterinario_id == veterinario_id,
                    Cita.fecha_hora >= datetime.combine(fecha, time.min),
                    Cita.fecha_hora <= datetime.combine(fecha, time.max),
                    _condicion_no_cancelada(),
                )
                .all()
            }

            libres = [slot for slot in slots if slot not in ocupados and slot > datetime.now()]
            disponible = len(libres) > 0

            if disponible:
                sugerencias = libres[:5]
            else:
                sugerencias = _siguientes_sugerencias_disponibles(veterinario_id, datetime.combine(fecha, time.min), count=5)

            result = {
                "disponible": disponible,
                "veterinario": vet,
                "fecha": fecha,
                "sugerencias": [_etiqueta_bloque(s) for s in sugerencias],
            }

    return render_template(
        "citas_disponibilidad.html",
        me=me,
        active_nav="citas",
        veterinarios=veterinarios,
        datos_formulario=datos_formulario,
        result=result,
    )


@citas_bp.route("/citas/reasignar", methods=["GET", "POST"])
def citas_reasignar():
    """Función para citas reasignar."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    client_redirect = _redirigir_cliente_a_portal(me)
    if client_redirect:
        return client_redirect

    if not _permitido(me, "hu010"):
        return render_template("acceso_denegado.html", me=me), 403

    veterinarios = _obtener_usuarios_por_rol(ROLE_VETERINARIO)
    citas_q = (
        db.session.query(Cita)
        .filter(Cita.fecha_hora > datetime.now(), _condicion_no_cancelada())
        .order_by(Cita.fecha_hora.asc())
    )
    if _nombre_rol(me) == ROLE_CLIENTE:
        me_id = _parsear_entero(me.get("id"))
        if me_id is not None:
            citas_q = citas_q.filter(Cita.cliente_id == me_id)
    citas_futuras = citas_q.all()

    datos_formulario = {
        "fecha": "",
        "cita_id": "",
        "veterinario_original_id": "",
        "veterinario_nuevo_id": "",
        "motivo_ausencia": "",
    }
    errores_campo = {}

    if request.method == "POST":
        fecha = _parsear_fecha(request.form.get("fecha") or "")
        cita_id = _parsear_entero(request.form.get("cita_id"))
        veterinario_original_id = _parsear_entero(request.form.get("veterinario_original_id"))
        veterinario_nuevo_id = _parsear_entero(request.form.get("veterinario_nuevo_id"))
        motivo_ausencia = (request.form.get("motivo_ausencia") or "").strip().lower()

        datos_formulario = {
            "fecha": request.form.get("fecha") or "",
            "cita_id": str(cita_id or ""),
            "veterinario_original_id": str(veterinario_original_id or ""),
            "veterinario_nuevo_id": str(veterinario_nuevo_id or ""),
            "motivo_ausencia": motivo_ausencia,
        }

        errors = []

        if not fecha:
            errores_campo["fecha"] = "Debes seleccionar la fecha de la cita."
        elif fecha <= date.today():
            errores_campo["fecha"] = "La fecha debe ser futura."
        if not motivo_ausencia:
            errores_campo["motivo_ausencia"] = "Debes seleccionar un motivo de ausencia."
        elif motivo_ausencia not in ABSENCE_REASON_OPTIONS:
            errores_campo["motivo_ausencia"] = "El motivo de ausencia seleccionado no es válido."

        cita = db.session.get(Cita, cita_id) if cita_id else None
        if not cita:
            errores_campo["cita_id"] = "Debes seleccionar la cita por reasignar."
        else:
            if not _usuario_puede_modificar_cita(me, cita):
                errors.append("No tienes permisos para reasignar esa cita.")
            if cita.cancelada or cita.estado == "cancelada":
                errors.append("La cita seleccionada está cancelada.")
            if not _es_fecha_hora_futura(cita.fecha_hora):
                errors.append("Solo se pueden reasignar citas futuras.")
            if fecha and cita.fecha_hora.date() != fecha:
                errores_campo["cita_id"] = "La fecha indicada no coincide con la fecha de la cita seleccionada."

        if not veterinario_original_id:
            errores_campo["veterinario_original_id"] = "Debes seleccionar el veterinario original."
        if not veterinario_nuevo_id:
            errores_campo["veterinario_nuevo_id"] = "Debes seleccionar el veterinario nuevo."
        if veterinario_original_id and veterinario_nuevo_id and veterinario_original_id == veterinario_nuevo_id:
            errores_campo["veterinario_nuevo_id"] = "El veterinario nuevo debe ser diferente al veterinario original."

        if cita and veterinario_original_id and cita.veterinario_id != veterinario_original_id:
            errores_campo["veterinario_original_id"] = "La cita no corresponde al veterinario original seleccionado."

        if cita and veterinario_nuevo_id and not _es_veterinario_disponible(veterinario_nuevo_id, cita.fecha_hora, exclude_cita_id=cita.id):
            errores_campo["veterinario_nuevo_id"] = "El veterinario nuevo no está disponible en la fecha/hora de la cita."

        filtered_q = citas_q
        if fecha:
            filtered_q = filtered_q.filter(
                Cita.fecha_hora >= datetime.combine(fecha, time.min),
                Cita.fecha_hora <= datetime.combine(fecha, time.max),
            )
        if veterinario_original_id:
            filtered_q = filtered_q.filter(Cita.veterinario_id == veterinario_original_id)
        citas_futuras = filtered_q.all()

        errors.extend(errores_campo.values())
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
            return redirect(url_for("citas.citas_lista"))

    return render_template(
        "citas_reasignar.html",
        me=me,
        active_nav="citas",
        veterinarios=veterinarios,
        citas_futuras=citas_futuras,
        datos_formulario=datos_formulario,
        errores_campo=errores_campo,
        absence_reason_options=ABSENCE_REASON_OPTIONS,
    )
