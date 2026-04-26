from __future__ import annotations

from datetime import datetime

from sqlalchemy import inspect
from sqlalchemy.orm import aliased

from app.extensions import db
from app.models import AnalisisClinico, Cita, ConsultaMedica, Mascota, SeguimientoTratamiento, Usuario, VacunaAlergia

ROLE_ADMIN = "administrador"
ROLE_VETERINARIO = "veterinario"

EVENT_LABELS = {
    "cita": "cita",
    "medicamento": "medicamento",
    "vacuna": "vacuna",
    "analisis": "análisis clínico",
}


def asegurar_tabla_seguimientos():
    # Función de tabla de seguimientos.
    inspector = inspect(db.engine)
    if SeguimientoTratamiento.__tablename__ not in inspector.get_table_names():
        SeguimientoTratamiento.__table__.create(bind=db.engine, checkfirst=True)


def usuario_puede_programar_seguimiento(me) -> bool:
    # Función de permisos de seguimiento.
    return ((me.get("rol") or "").strip().lower()) in {ROLE_ADMIN, ROLE_VETERINARIO}


def parsear_fecha_hora_seguimiento(value: str):
    # Función de fecha de seguimiento.
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def fecha_hora_seguimiento_a_formato(value):
    # Función de fecha de seguimiento.
    if not value:
        return ""
    return value.strftime("%Y-%m-%dT%H:%M")


def obtener_mapa_seguimientos(origen_tipo: str, origen_id: int) -> dict[str, SeguimientoTratamiento]:
    # Función de consulta de seguimientos.
    rows = (
        db.session.query(SeguimientoTratamiento)
        .filter(
            SeguimientoTratamiento.origen_tipo == origen_tipo,
            SeguimientoTratamiento.origen_id == origen_id,
        )
        .all()
    )
    return {row.evento_tipo: row for row in rows}


def obtener_mapa_seguimientos_por_ids(origen_tipo: str, origen_ids: list[int]):
    # Función de consulta masiva de seguimientos.
    if not origen_ids:
        return {}
    rows = (
        db.session.query(SeguimientoTratamiento)
        .filter(
            SeguimientoTratamiento.origen_tipo == origen_tipo,
            SeguimientoTratamiento.origen_id.in_(origen_ids),
        )
        .all()
    )
    return {(row.origen_id, row.evento_tipo): row for row in rows}


def obtener_seguimiento(origen_tipo: str, origen_id: int, evento_tipo: str) -> SeguimientoTratamiento | None:
    # Función de consulta de seguimiento.
    return (
        db.session.query(SeguimientoTratamiento)
        .filter(
            SeguimientoTratamiento.origen_tipo == origen_tipo,
            SeguimientoTratamiento.origen_id == origen_id,
            SeguimientoTratamiento.evento_tipo == evento_tipo,
        )
        .first()
    )


def guardar_seguimiento(*, origen_tipo: str, origen_id: int, evento_tipo: str, mascota_id: int, veterinario_id: int, programado_para, descripcion: str = ""):
    # Función de programación de seguimiento.
    row = obtener_seguimiento(origen_tipo, origen_id, evento_tipo)
    if row is None:
        row = SeguimientoTratamiento(
            origen_tipo=origen_tipo,
            origen_id=origen_id,
            evento_tipo=evento_tipo,
        )
        db.session.add(row)

    row.mascota_id = mascota_id
    row.veterinario_id = veterinario_id
    row.programado_para = programado_para
    row.descripcion = (descripcion or "").strip() or None
    row.estado = "programado"
    row.enviado_en = None
    return row


def eliminar_seguimiento(*, origen_tipo: str, origen_id: int, evento_tipo: str):
    # Función de cancelación de seguimiento.
    row = obtener_seguimiento(origen_tipo, origen_id, evento_tipo)
    if row is not None:
        db.session.delete(row)


def validar_programacion_seguimiento(*, requiere: bool, programado_para_raw: str, veterinario: Usuario | None, errores_campo: dict, error_field: str):
    # Función de validación de seguimiento.
    if not requiere:
        return {"requiere": False, "programado_para": None}

    programado_para = parsear_fecha_hora_seguimiento(programado_para_raw)
    if not programado_para:
        errores_campo[error_field] = "Debes seleccionar una fecha y hora válidas para el seguimiento."
        return {"requiere": True, "programado_para": None}
    if programado_para <= datetime.now():
        errores_campo[error_field] = "Debes seleccionar una fecha y hora futura para el seguimiento."
        return {"requiere": True, "programado_para": None}

    correo = ((veterinario.correo if veterinario else "") or "").strip()
    if not correo:
        errores_campo[error_field] = "El veterinario seleccionado no tiene correo registrado para recibir el seguimiento."
        return {"requiere": True, "programado_para": None}

    return {"requiere": True, "programado_para": programado_para}


def sincronizar_seguimientos_programados():
    # Función de seguimiento automático.
    now = datetime.now()
    rows = (
        db.session.query(SeguimientoTratamiento.id)
        .filter(SeguimientoTratamiento.estado == "programado")
        .filter(SeguimientoTratamiento.programado_para <= now)
        .order_by(SeguimientoTratamiento.programado_para.asc(), SeguimientoTratamiento.id.asc())
        .all()
    )

    for row in rows:
        enviar_seguimiento_ahora(row[0], marcar_enviado=True)

    if rows:
        db.session.commit()


def _destinatarios_seguimiento(cliente: Usuario | None, veterinario: Usuario | None):
    # Función de destinatarios de seguimiento.
    destinatarios = []
    vistos = set()
    for usuario in (cliente, veterinario):
        correo = ((usuario.correo if usuario else "") or "").strip().lower()
        if correo and correo not in vistos:
            destinatarios.append(correo)
            vistos.add(correo)
    return destinatarios


def _detalle_origen_seguimiento(seguimiento: SeguimientoTratamiento):
    # Función de detalle clínico del seguimiento.
    diagnostico = "sin diagnóstico registrado"
    fecha_original = seguimiento.programado_para

    if seguimiento.origen_tipo == "cita":
        cita = db.session.get(Cita, seguimiento.origen_id)
        if cita:
            fecha_original = cita.fecha_hora or fecha_original
            diagnostico = (cita.motivo or "").strip() or diagnostico
    elif seguimiento.origen_tipo == "consulta":
        consulta = db.session.get(ConsultaMedica, seguimiento.origen_id)
        if consulta:
            fecha_original = consulta.fecha_consulta or fecha_original
            diagnostico = (consulta.diagnostico or "").strip() or diagnostico
    elif seguimiento.origen_tipo == "vacuna_alergia":
        vacuna = db.session.get(VacunaAlergia, seguimiento.origen_id)
        if vacuna:
            fecha_original = vacuna.fecha_registro or fecha_original
            diagnostico = (vacuna.nombre or vacuna.notas_adicionales or "").strip() or diagnostico
    elif seguimiento.origen_tipo == "analisis_clinico":
        analisis = db.session.get(AnalisisClinico, seguimiento.origen_id)
        if analisis:
            fecha_original = analisis.fecha_analisis or fecha_original
            diagnostico = (analisis.resultados or analisis.tipo_analisis or "").strip() or diagnostico

    return fecha_original, diagnostico


def enviar_seguimiento_ahora(seguimiento_id: int, *, marcar_enviado: bool = True):
    # Función de envío inmediato de seguimiento.
    from app.routes.chat import _enviar_email_smtp

    veterinario = aliased(Usuario)
    cliente = aliased(Usuario)
    row = (
        db.session.query(
            SeguimientoTratamiento,
            Mascota.nombre.label("mascota_nombre"),
            veterinario,
            cliente,
        )
        .join(Mascota, SeguimientoTratamiento.mascota_id == Mascota.id)
        .join(veterinario, SeguimientoTratamiento.veterinario_id == veterinario.id)
        .join(cliente, Mascota.dueno_id == cliente.id)
        .filter(SeguimientoTratamiento.id == seguimiento_id)
        .filter(veterinario.activo.is_(True), veterinario.eliminado.is_(False))
        .filter(cliente.activo.is_(True), cliente.eliminado.is_(False))
        .first()
    )
    if not row:
        return False, "El seguimiento solicitado no existe."

    seguimiento, mascota_nombre, veterinario_row, cliente_row = row
    destinatarios = _destinatarios_seguimiento(cliente_row, veterinario_row)
    if not destinatarios:
        return False, "No hay correos registrados para el seguimiento."

    fecha_original, diagnostico = _detalle_origen_seguimiento(seguimiento)
    fecha_original_texto = fecha_original.strftime("%Y-%m-%d %H:%M") if hasattr(fecha_original, "strftime") else str(fecha_original)
    subject = f"Recordatorio de seguimiento: {mascota_nombre}"
    body = (
        f"Te recordamos que {mascota_nombre} tiene agendada una reunión de seguimiento "
        f"derivada de la atención proporcionada el {fecha_original_texto} "
        f"relacionada con su diagnóstico de {diagnostico}."
    )
    sent_ok, sent_error = _enviar_email_smtp(", ".join(destinatarios), subject, body)
    if not sent_ok:
        return False, sent_error or "No fue posible enviar el seguimiento."

    if marcar_enviado:
        seguimiento.estado = "enviado"
        seguimiento.enviado_en = datetime.now()
    return True, "Seguimiento enviado correctamente."
