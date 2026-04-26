from __future__ import annotations

import os
import re
import secrets
import smtplib
from datetime import datetime
from email.message import EmailMessage

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import MetaData, Table, and_, func, insert, select, true, update
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from utils.auth_ui import get_current_user_from_api

chat_bp = Blueprint("chat", __name__)

PREGUNTAS_FRECUENTES_PREDETERMINADAS = {
    "¿Cuál es el precio de la consulta?": "La consulta general tiene un costo base de $300 MXN.",
    "¿Cuáles son los horarios de la clínica?": "Nuestro horario es de lunes a sábado de 9:00 a 19:00 hrs.",
    "¿Cuál es la ubicación de la clínica?": "Estamos en Ecatepec, Estado de México. Te compartimos ubicación exacta por llamada o WhatsApp.",
}

OPCION_AGENDAR_LABEL = "Quiero agendar una cita"
OPCION_CITAS_PENDIENTES_LABEL = "Dime qué citas tengo agendadas"
MOTIVO_CITA_OPTIONS = {
    "1": "Consulta general",
    "2": "Seguimiento",
    "3": "Servicio de estetica",
    "4": "Otro",
}

CITA_SESSION_KEY = "chat_appt_state"
EVALUACION_SESSION_KEY = "chat_eval_state"
CITAS_PENDIENTES_SESSION_KEY = "chat_pending_appts_state"


def _preguntas_frecuentes_table() -> Table:
    metadata = MetaData()
    return Table("chatbot_faq", metadata, autoload_with=db.engine)


def _citas_table() -> Table:
    metadata = MetaData()
    return Table("citas", metadata, autoload_with=db.engine)


def _usuarios_table() -> Table:
    metadata = MetaData()
    return Table("usuarios", metadata, autoload_with=db.engine)


def _recordatorios_table() -> Table:
    metadata = MetaData()
    return Table("recordatorios_citas", metadata, autoload_with=db.engine)


def _encuestas_table() -> Table:
    metadata = MetaData()
    return Table("encuestas_satisfaccion", metadata, autoload_with=db.engine)


def _roles_table() -> Table:
    metadata = MetaData()
    return Table("roles", metadata, autoload_with=db.engine)


def _mascotas_table() -> Table:
    metadata = MetaData()
    return Table("mascotas", metadata, autoload_with=db.engine)



def _obtener_usuario_actual():
    if not session.get("access_token"):
        return None
    return get_current_user_from_api()


def _es_admin(user_info) -> bool:
    return bool(user_info and (user_info.get("rol") or "").strip().lower() == "administrador")


def _find_column(table: Table, candidates: list[str]):
    for name in candidates:
        if name in table.c:
            return table.c[name]
    return None


def _required_columns_without_default(table: Table):
    required = []
    for col in table.columns:
        if col.primary_key and col.autoincrement:
            continue
        if col.nullable:
            continue
        if col.default is not None or col.server_default is not None:
            continue
        required.append(col.name)
    return required


def _construir_insert_payload(table: Table, question: str, answer: str):
    payload: dict[str, object] = {}
    question_col = _find_column(table, ["pregunta", "question"])
    answer_col = _find_column(table, ["respuesta", "answer"])

    if question_col is None or answer_col is None:
        raise ValueError("La tabla chatbot_faq no tiene columnas esperadas de pregunta/respuesta.")

    payload[question_col.name] = question
    payload[answer_col.name] = answer

    required_cols = _required_columns_without_default(table)
    unknown_required = [c for c in required_cols if c not in payload and c not in ("id",)]
    if unknown_required:
        raise ValueError(
            "No se pudo insertar FAQ por columnas requeridas sin valor: "
            + ", ".join(unknown_required)
        )

    return payload


def _normalizar_texto_pregunta(value: str) -> str:
    # Normaliza una pregunta para compararla sin diferencias de formato.
    normalized = (value or "").strip().lower()
    normalized = re.sub(r"^[¿?¡!\s]+|[¿?¡!\s]+$", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _preguntas_frecuentes_pairs():
    table = _preguntas_frecuentes_table()
    question_col = _find_column(table, ["pregunta", "question"])
    answer_col = _find_column(table, ["respuesta", "answer"])
    if question_col is None or answer_col is None:
        return []

    rows = db.session.execute(
        select(question_col, answer_col).order_by(question_col.asc())
    ).all()
    return [{"pregunta": row[0], "respuesta": row[1]} for row in rows]


def _chat_quick_options():
    options = []
    seen = set()
    for row in _preguntas_frecuentes_pairs():
        question = (row.get("pregunta") or "").strip()
        if not question:
            continue
        key = _normalizar_texto_pregunta(question)
        if not key or key in seen:
            continue
        seen.add(key)
        options.append(question)

    options.append(OPCION_AGENDAR_LABEL)
    options.append(OPCION_CITAS_PENDIENTES_LABEL)
    return options


def _asegurar_preguntas_frecuentes_predeterminadas():
    # Inserta las preguntas frecuentes iniciales si todavía no existen.
    table = _preguntas_frecuentes_table()
    question_col = _find_column(table, ["pregunta", "question"])
    answer_col = _find_column(table, ["respuesta", "answer"])
    if question_col is None or answer_col is None:
        return

    existing_rows = db.session.execute(select(question_col)).all()
    existing_norm = {_normalizar_texto_pregunta((row[0] or "")) for row in existing_rows}

    for question, answer in PREGUNTAS_FRECUENTES_PREDETERMINADAS.items():
        if _normalizar_texto_pregunta(question) in existing_norm:
            continue
        payload = _construir_insert_payload(table, question, answer)
        db.session.execute(insert(table).values(**payload))
        existing_norm.add(_normalizar_texto_pregunta(question))
    db.session.commit()


def _preguntas_frecuentes_rows():
    table = _preguntas_frecuentes_table()
    id_col = _find_column(table, ["id"])
    question_col = _find_column(table, ["pregunta", "question"])
    answer_col = _find_column(table, ["respuesta", "answer"])
    if id_col is None or question_col is None or answer_col is None:
        return []

    rows = db.session.execute(
        select(id_col, question_col, answer_col).order_by(id_col.desc())
    ).all()
    return [
        {"id": row[0], "pregunta": row[1], "respuesta": row[2]}
        for row in rows
    ]


def _telefono_clinica() -> str:
    return os.getenv("CLINIC_PHONE", "No disponible")


def _reiniciar_cita_state() -> None:
    # Limpia el estado del flujo de agendado en la sesión.
    session.pop(CITA_SESSION_KEY, None)


def _guardar_cita_state(state: dict) -> None:
    # Guarda el estado actual del flujo de agendado en la sesión.
    session[CITA_SESSION_KEY] = state
    session.modified = True


def _obtener_cita_state() -> dict | None:
    # Recupera el estado del flujo de agendado desde la sesión.
    state = session.get(CITA_SESSION_KEY)
    return state if isinstance(state, dict) else None


def _reiniciar_evaluacion_state() -> None:
    # Limpia el estado de la evaluación de servicio en la sesión.
    session.pop(EVALUACION_SESSION_KEY, None)


def _guardar_evaluacion_state(state: dict) -> None:
    # Guarda el estado actual de la evaluación de servicio en la sesión.
    session[EVALUACION_SESSION_KEY] = state
    session.modified = True


def _obtener_evaluacion_state() -> dict | None:
    # Recupera el estado de la evaluación de servicio desde la sesión.
    state = session.get(EVALUACION_SESSION_KEY)
    return state if isinstance(state, dict) else None


def _reiniciar_citas_pendientes_state() -> None:
    # Limpia el estado del flujo de citas pendientes en la sesión.
    session.pop(CITAS_PENDIENTES_SESSION_KEY, None)


def _guardar_citas_pendientes_state(state: dict) -> None:
    # Guarda el estado actual del flujo de citas pendientes en la sesión.
    session[CITAS_PENDIENTES_SESSION_KEY] = state
    session.modified = True


def _obtener_citas_pendientes_state() -> dict | None:
    # Recupera el estado del flujo de citas pendientes desde la sesión.
    state = session.get(CITAS_PENDIENTES_SESSION_KEY)
    return state if isinstance(state, dict) else None



def _ultima_cita_id_para_cliente(cliente_id: int):
    citas = _citas_table()
    cita_id_col = _find_column(citas, ["id"])
    cita_cliente_col = _find_column(citas, ["cliente_id"])
    cita_fecha_col = _find_column(citas, ["fecha_hora"])
    if cita_id_col is None or cita_cliente_col is None:
        return None

    order_col = cita_fecha_col if cita_fecha_col is not None else cita_id_col
    row = db.session.execute(
        select(cita_id_col).where(cita_cliente_col == cliente_id).order_by(order_col.desc()).limit(1)
    ).first()
    return int(row[0]) if row else None


def _iniciar_evaluacion(cliente_id: int, cita_id=None):
    # Inicia el flujo de encuesta de satisfacción al terminar una cita.
    resolved_cita_id = cita_id if cita_id is not None else _ultima_cita_id_para_cliente(cliente_id)
    if resolved_cita_id is None:
        return None

    _guardar_evaluacion_state(
        {
            "step": "awaiting_rating",
            "cliente_id": int(cliente_id),
            "cita_id": resolved_cita_id,
        }
    )
    return jsonify(
        {
            "ok": True,
            "answer": "Antes de terminar, califica tu experiencia del 1 al 5.",
            "evaluation_step": "rating",
            "rating_options": [1, 2, 3, 4, 5],
        }
    )


def _guardar_evaluacion(cliente_id: int, cita_id, calificacion: int, comentario: str):
    # Guarda en la base de datos la encuesta de satisfacción respondida.
    encuestas = _encuestas_table()
    col_cliente = _find_column(encuestas, ["cliente_id"])
    col_cita = _find_column(encuestas, ["cita_id"])
    col_calif = _find_column(encuestas, ["calificacion"])
    col_coment = _find_column(encuestas, ["comentario"])
    col_fecha = _find_column(encuestas, ["fecha_envio"])
    col_resp = _find_column(encuestas, ["respondido"])

    if col_cliente is None or col_calif is None or col_coment is None:
        raise ValueError("La tabla encuestas_satisfaccion no tiene columnas mínimas requeridas.")
    if col_cita is None:
        raise ValueError("La tabla encuestas_satisfaccion requiere columna cita_id.")
    if cita_id is None:
        raise ValueError("No hay cita asociada para registrar la encuesta.")

    # Preparamos los datos que se van a guardar en la base de datos.
    payload = {
        col_cliente.name: int(cliente_id),
        col_cita.name: int(cita_id),
        col_calif.name: int(calificacion),
        col_coment.name: (comentario.strip() or None),
    }
    if col_fecha is not None:
        payload[col_fecha.name] = datetime.now()
    if col_resp is not None:
        payload[col_resp.name] = True

    db.session.execute(insert(encuestas).values(**payload))
    db.session.commit()


def _procesar_evaluacion_step(me, question: str):
    # Procesa cada paso de la evaluación de satisfacción en el chat.
    state = _obtener_evaluacion_state()
    if not state:
        return None

    if not me:
        _reiniciar_evaluacion_state()
        return jsonify({"ok": True, "answer": "Se canceló la evaluación por falta de sesión."})

    step = state.get("step")
    q = question.strip()
    if step == "awaiting_rating":
        try:
            rating = int(q)
        except ValueError:
            return jsonify(
                {
                    "ok": True,
                    "answer": "Calificación inválida. Debe ser un número del 1 al 5.",
                    "evaluation_step": "rating",
                    "rating_options": [1, 2, 3, 4, 5],
                }
            )

        if rating < 1 or rating > 5:
            return jsonify(
                {
                    "ok": True,
                    "answer": "Calificación inválida. Debe estar entre 1 y 5.",
                    "evaluation_step": "rating",
                    "rating_options": [1, 2, 3, 4, 5],
                }
            )

        state["calificacion"] = rating
        state["step"] = "awaiting_comment"
        _guardar_evaluacion_state(state)
        return jsonify(
            {
                "ok": True,
                "answer": "Por favor, escribe un comentario sobre el servicio.",
                "evaluation_step": "comment",
                "show_send_button": True,
            }
        )
    if step == "awaiting_comment":
        if not q:
            return jsonify(
                {
                    "ok": True,
                    "answer": "Escribe tu comentario para continuar.",
                    "evaluation_step": "comment",
                    "show_send_button": True,
                }
            )
        try:
            _guardar_evaluacion(
                cliente_id=int(state["cliente_id"]),
                cita_id=state.get("cita_id"),
                calificacion=int(state["calificacion"]),
                comentario=question,
            )
        except Exception:
            db.session.rollback()
            return jsonify({"ok": False, "message": "No se pudo guardar la evaluación."}), 500

        _reiniciar_evaluacion_state()
        return jsonify(
            {
                "ok": True,
                "answer": "Gracias por tu evaluación. Tu respuesta fue registrada.",
                "evaluation_step": "done",
            }
        )

    _reiniciar_evaluacion_state()
    return jsonify({"ok": True, "answer": "Reiniciamos la evaluación. Escribe una calificación del 1 al 5."})


def _citas_pendientes_para_cliente(cliente_id: int):
    citas = _citas_table()
    usuarios = _usuarios_table()
    mascotas = _mascotas_table()

    cita_id_col = _find_column(citas, ["id"])
    cita_fecha_col = _find_column(citas, ["fecha_hora"])
    cita_motivo_col = _find_column(citas, ["motivo"])
    cita_cliente_col = _find_column(citas, ["cliente_id"])
    cita_mascota_col = _find_column(citas, ["mascota_id"])
    cita_vet_col = _find_column(citas, ["veterinario_id"])
    cita_estado_col = _find_column(citas, ["estado", "estatus"])

    usuario_id_col = _find_column(usuarios, ["id"])
    user_name_col = _find_column(usuarios, ["nombre"])
    pet_id_col = _find_column(mascotas, ["id"])
    pet_name_col = _find_column(mascotas, ["nombre"])

    required = [
        cita_id_col,
        cita_fecha_col,
        cita_cliente_col,
        cita_mascota_col,
        cita_vet_col,
        usuario_id_col,
        user_name_col,
        pet_id_col,
        pet_name_col,
    ]
    if any(col is None for col in required):
        raise ValueError("La base de datos no tiene el esquema necesario para consultar citas pendientes.")

    stmt = (
        select(
            cita_id_col,
            cita_fecha_col,
            cita_motivo_col,
            pet_name_col,
            user_name_col,
            cita_estado_col if cita_estado_col is not None else cita_id_col,
        )
        .select_from(
            citas.join(mascotas, cita_mascota_col == pet_id_col).join(usuarios, cita_vet_col == usuario_id_col)
        )
        .where(
            and_(
                cita_cliente_col == cliente_id,
                cita_fecha_col >= datetime.now(),
                _condicion_no_cancelada(citas),
            )
        )
        .order_by(cita_fecha_col.asc())
    )
    rows = db.session.execute(stmt).all()
    data = []
    for row in rows:
        data.append(
            {
                "id": int(row[0]),
                "fecha_hora": row[1],
                "motivo": row[2] or "Sin motivo especificado",
                "mascota": row[3] or "Mascota",
                "veterinario": row[4] or "Veterinario",
                "estado": row[5] if cita_estado_col is not None else "pendiente",
            }
        )
    return data


def _formatear_citas_pendientes(rows: list[dict]) -> str:
    lines = ["Estas son tus citas pendientes:"]
    for idx, row in enumerate(rows, start=1):
        fecha_hora = row["fecha_hora"]
        fecha_label = fecha_hora.strftime("%Y-%m-%d %H:%M") if isinstance(fecha_hora, datetime) else str(fecha_hora)
        lines.append(
            f"{idx}. {fecha_label} | Mascota: {row['mascota']} | Vet: {row['veterinario']} | Motivo: {row['motivo']}"
        )
    return "\n".join(lines)


def _mensaje_confirmacion_citas_pendientes() -> str:
    # Devuelve el texto que guía la confirmación de envío por correo.
    return "¿Quieres que te envíe esta lista por correo?\n1. Sí\n2. No"


def _iniciar_citas_pendientes_flow(me):
    # Inicia el flujo para consultar y opcionalmente enviar por correo las citas pendientes.
    try:
        cliente_id = int(me.get("id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "No se pudo validar tu sesión para consultar citas."}), 401

    rows = _citas_pendientes_para_cliente(cliente_id)
    if not rows:
        _reiniciar_citas_pendientes_state()
        return jsonify({"ok": True, "answer": "No tienes citas pendientes por el momento."})

    _guardar_citas_pendientes_state({"step": "awaiting_correo_confirmation", "cliente_id": cliente_id})
    return jsonify(
        {
            "ok": True,
            "answer": _formatear_citas_pendientes(rows) + "\n\n" + _mensaje_confirmacion_citas_pendientes(),
            "choice_options": [
                {"value": "1", "label": "Sí"},
                {"value": "2", "label": "No"},
            ],
        }
    )


def _procesar_citas_pendientes_step(me, question: str):
    # Procesa la confirmación del usuario para enviar por correo la lista de citas pendientes.
    state = _obtener_citas_pendientes_state()
    if not state:
        return None

    if not me:
        _reiniciar_citas_pendientes_state()
        return jsonify({"ok": True, "answer": "Se canceló la consulta de citas pendientes por falta de sesión."})

    answer = _normalizar_texto_pregunta(question)
    if answer in {"1", "si", "sí"}:
        cliente_correo = (me.get("correo") or "").strip()
        if not cliente_correo:
            _reiniciar_citas_pendientes_state()
            return jsonify(
                {
                    "ok": True,
                    "answer": "No pude enviarte la lista porque tu cuenta no tiene un correo registrado.",
                }
            )

        rows = _citas_pendientes_para_cliente(int(state["cliente_id"]))
        if not rows:
            _reiniciar_citas_pendientes_state()
            return jsonify({"ok": True, "answer": "Tus citas pendientes cambiaron y ahora no hay ninguna por enviar."})

        subject = "Listado de citas pendientes - CIVE"
        body = _formatear_citas_pendientes(rows)
        sent_ok, sent_error = _enviar_email_smtp(cliente_correo, subject, body)
        _reiniciar_citas_pendientes_state()

        if not sent_ok:
            return jsonify(
                {
                    "ok": True,
                    "answer": f"No pude enviarte el correo en este momento: {sent_error}",
                }
            )

        return jsonify(
            {
                "ok": True,
                "answer": f"Listo. Envié el listado de tus citas pendientes al correo {cliente_correo}.",
            }
        )

    if answer in {"2", "no"}:
        _reiniciar_citas_pendientes_state()
        return jsonify({"ok": True, "answer": "De acuerdo. No enviaré la lista por correo."})

    return jsonify(
        {
            "ok": True,
            "answer": "Selecciona una de las opciones indicadas:\n¿Quieres que te envíe esta lista por correo?\n1. Sí\n2. No",
            "choice_options": [
                {"value": "1", "label": "Sí"},
                {"value": "2", "label": "No"},
            ],
        }
    )


def _mascotas_usuario(usuario_id: int):
    mascotas = _mascotas_table()
    id_col = _find_column(mascotas, ["id"])
    name_col = _find_column(mascotas, ["nombre"])
    owner_col = _find_column(mascotas, ["dueno_id", "cliente_id", "usuario_id"])
    status_col = _find_column(mascotas, ["estado", "estatus"])

    if id_col is None or name_col is None or owner_col is None:
        return []

    where_parts = [owner_col == usuario_id]
    if status_col is not None:
        where_parts.append(func.lower(status_col) == "activa")

    rows = db.session.execute(
        select(id_col, name_col).where(and_(*where_parts)).order_by(name_col.asc())
    ).all()

    return [{"id": int(r[0]), "nombre": r[1]} for r in rows]


def _normalizar_nombre_mascota(value: str) -> str:
    # Normaliza nombres de mascota para compararlos sin depender de mayúsculas o espacios extra.
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _mensaje_motivo_cita() -> str:
    # Devuelve el catalogo de motivos permitidos para el flujo de agendado.
    lines = ["Selecciona el motivo de la cita escribiendo el numero de una opcion:"]
    for key, label in MOTIVO_CITA_OPTIONS.items():
        lines.append(f"{key}. {label}")
    return "\n".join(lines)


def _condicion_no_cancelada(citas_table: Table):
    status_col = _find_column(citas_table, ["estado", "estatus"])
    canceled_col = _find_column(citas_table, ["cancelada"])

    clauses = []
    if status_col is not None:
        lowered = func.lower(func.trim(status_col))
        clauses.append(and_(lowered != "cancelada", lowered != "cancelado"))
    if canceled_col is not None:
        clauses.append(canceled_col.is_(False))

    if not clauses:
        return true()

    return and_(*clauses)


def _resolver_veterinario_id(fecha_hora: datetime):
    # Asigna un veterinario disponible para una fecha/hora específica basado en la carga de trabajo.
    citas = _citas_table()
    usuarios = _usuarios_table()
    roles = _roles_table()

    cita_fecha_col = _find_column(citas, ["fecha_hora"])
    cita_vet_col = _find_column(citas, ["veterinario_id"])
    if cita_fecha_col is None or cita_vet_col is None:
        return None

    usuario_id_col = _find_column(usuarios, ["id"])
    user_role_col = _find_column(usuarios, ["rol_id"])
    user_active_col = _find_column(usuarios, ["activo"])
    user_deleted_col = _find_column(usuarios, ["eliminado"])

    role_id_col = _find_column(roles, ["id"])
    role_name_col = _find_column(roles, ["nombre"])

    if any(col is None for col in (usuario_id_col, user_role_col, role_id_col, role_name_col)):
        return None

    vet_filters = [func.lower(role_name_col) == "veterinario"]
    if user_active_col is not None:
        vet_filters.append(user_active_col.is_(True))
    if user_deleted_col is not None:
        vet_filters.append(user_deleted_col.is_(False))

    vet_rows = db.session.execute(
        select(usuario_id_col)
        .select_from(usuarios.join(roles, user_role_col == role_id_col))
        .where(and_(*vet_filters))
    ).all()

    vet_ids = [int(r[0]) for r in vet_rows]
    if not vet_ids:
        return None

    not_canceled = _condicion_no_cancelada(citas)
    ranking = []

    for vet_id in vet_ids:
        last_dt = db.session.execute(
            select(func.max(cita_fecha_col)).where(and_(cita_vet_col == vet_id, not_canceled))
        ).scalar()

        ranking.append((0 if last_dt is None else 1, last_dt, vet_id))

    ranking.sort(key=lambda item: (item[0], item[1] or datetime(1900, 1, 1)))

    for _, _, vet_id in ranking:
        conflict = db.session.execute(
            select(cita_vet_col)
            .where(and_(cita_vet_col == vet_id, cita_fecha_col == fecha_hora, not_canceled))
            .limit(1)
        ).first()
        if not conflict:
            return vet_id

    return None


def _enviar_email_smtp(to_correo: str, subject: str, body: str):
    # Envía un correo usando la configuración SMTP del sistema.
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_use_tls = (os.getenv("SMTP_USE_TLS", "true").strip().lower() == "true")

    if not smtp_host or not smtp_user or not smtp_password:
        return False, "SMTP no configurado (SMTP_HOST/SMTP_USER/SMTP_PASSWORD)."

    msg = EmailMessage()
    msg["From"] = smtp_user
    msg["To"] = to_correo
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            if smtp_use_tls:
                server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        return True, "ok"
    except Exception as exc:  # pragma: no cover
        return False, str(exc)


def _iniciar_cita_flow(me):
    # Inicia el flujo guiado para agendar una cita desde el chat.
    try:
        usuario_id = int(me.get("id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "No se pudo validar tu sesión para agendar."}), 401

    pets = _mascotas_usuario(usuario_id)
    if not pets:
        _reiniciar_cita_state()
        return jsonify(
            {
                "ok": True,
                "answer": "No encontramos mascotas asociadas a tu cuenta. Registra una mascota primero para agendar.",
            }
        )

    _guardar_cita_state({"step": "awaiting_date", "cliente_id": usuario_id})
    return jsonify(
        {
            "ok": True,
            "answer": "Perfecto, comencemos. Indica la fecha de la cita en formato YYYY-MM-DD.",
        }
    )


def _finalizar_cita(me, state):
    # Guarda la cita solicitada y envía las notificaciones correspondientes.
    citas = _citas_table()

    fecha_col = _find_column(citas, ["fecha_hora"])
    motivo_col = _find_column(citas, ["motivo"])
    cliente_col = _find_column(citas, ["cliente_id"])
    mascota_col = _find_column(citas, ["mascota_id"])
    vet_col = _find_column(citas, ["veterinario_id"])

    if any(col is None for col in (fecha_col, motivo_col, cliente_col, mascota_col, vet_col)):
        _reiniciar_cita_state()
        return jsonify(
            {
                "ok": False,
                "message": "La tabla citas no tiene el esquema esperado (fecha_hora, motivo, cliente_id, mascota_id, veterinario_id).",
            }
        ), 500

    # Convertimos la fecha y la hora capturadas en un solo valor de cita.
    fecha_hora = datetime.strptime(f"{state['fecha']} {state['hora']}", "%Y-%m-%d %H:%M")
    if fecha_hora <= datetime.now():
        _reiniciar_cita_state()
        return jsonify(
            {
                "ok": True,
                "answer": "La fecha y hora seleccionadas ya pasaron. Inicia de nuevo y elige un horario futuro.",
            }
        )

    # Buscamos un veterinario disponible para el horario solicitado.
    vet_id = _resolver_veterinario_id(fecha_hora)
    if vet_id is None:
        _reiniciar_cita_state()
        return jsonify(
            {
                "ok": True,
                "answer": "No hay veterinarios disponibles en ese horario. Intenta con otra fecha u hora.",
            }
        )

    # Preparamos los datos que se van a guardar en la base de datos.
    payload = {
        fecha_col.name: fecha_hora,
        motivo_col.name: state["motivo"],
        cliente_col.name: state["cliente_id"],
        mascota_col.name: state["mascota_id"],
        vet_col.name: vet_id,
    }

    try:
        required_cols = _required_columns_without_default(citas)
        missing = [c for c in required_cols if c not in payload and c not in ("id",)]
        if missing:
            _reiniciar_cita_state()
            return jsonify(
                {
                    "ok": False,
                    "message": "No se pudo crear la cita porque faltan columnas requeridas: " + ", ".join(missing),
                }
            ), 500
        result = db.session.execute(insert(citas).values(**payload))
        db.session.commit()
        cita_id = result.inserted_primary_key[0] if result.inserted_primary_key else None
    except SQLAlchemyError:
        db.session.rollback()
        _reiniciar_cita_state()
        return jsonify({"ok": False, "message": "No se pudo registrar la cita en la base de datos."}), 500

    admin_correo = os.getenv("ADMIN_EMAIL", "").strip()
    cliente_correo = (me.get("correo") or "").strip()
    cliente_nombre = (me.get("nombre") or "Cliente").strip()

    mascotas = _mascotas_table()
    pet_name_col = _find_column(mascotas, ["nombre"])
    pet_id_col = _find_column(mascotas, ["id"])
    mascota_nombre = "N/A"
    if pet_name_col is not None and pet_id_col is not None:
        pet_row = db.session.execute(
            select(pet_name_col).where(pet_id_col == state["mascota_id"]).limit(1)
        ).first()
        if pet_row:
            mascota_nombre = pet_row[0]

    client_mail_ok = False
    admin_mail_ok = False

    # Enviamos la notificacion al cliente si tiene correo disponible.
    if cliente_correo:
        client_subject = "Solicitud de cita recibida - CIVE"
        client_body = (
            f"Hola {cliente_nombre},\n\n"
            "Recibimos tu solicitud de cita. Nuestro personal puede comunicarse contigo "
            "para confirmar o ajustar detalles.\n\n"
            f"Fecha/hora solicitada: {state['fecha']} {state['hora']}\n"
            f"Mascota: {mascota_nombre}\n"
            f"Motivo: {state['motivo']}\n"
        )
        client_mail_ok, _ = _enviar_email_smtp(cliente_correo, client_subject, client_body)

    # Avisamos al administrador para que revise la nueva solicitud.
    if admin_correo:
        admin_subject = "Nueva solicitud de cita - Acción requerida"
        admin_body = (
            "Se registró una nueva solicitud de cita.\n\n"
            f"Cliente: {cliente_nombre} ({cliente_correo or 'sin correo'})\n"
            f"Mascota: {mascota_nombre} (ID {state['mascota_id']})\n"
            f"Fecha/hora solicitadas: {state['fecha']} {state['hora']}\n"
            f"Motivo: {state['motivo']}\n\n"
            "Instrucción: aceptar/rechazar."
        )
        admin_mail_ok, _ = _enviar_email_smtp(admin_correo, admin_subject, admin_body)

    _reiniciar_cita_state()

    # Iniciamos la encuesta de satisfaccion despues de registrar la cita.
    return jsonify(
        {
            "ok": True,
            "answer": (
                "Tu solicitud de cita fue registrada correctamente. "
                "Te contactaremos para confirmar detalles."
            ),
            "cita_id": cita_id,
            "correo_cliente_enviado": client_mail_ok,
            "correo_admin_enviado": admin_mail_ok,
        }
    )


def _procesar_cita_step(me, question: str):
    # Procesa cada paso del flujo guiado para agendar una cita.
    state = _obtener_cita_state()
    if not state:
        return None

    if not me:
        _reiniciar_cita_state()
        return jsonify(
            {
                "ok": True,
                "answer": f"Para agendar necesitas iniciar sesión. También puedes hacerlo por llamada/WhatsApp al {_telefono_clinica()}.",
            }
        )

    step = state.get("step")
    q = question.strip()

    # Permitimos cancelar el flujo en cualquier momento.
    if q.lower() in {"cancelar", "cancelar cita", "salir"}:
        _reiniciar_cita_state()
        return jsonify({"ok": True, "answer": "Flujo de agendado cancelado."})
    if step == "awaiting_date":
        try:
            parsed = datetime.strptime(q, "%Y-%m-%d")
            if parsed.date() < datetime.now().date():
                return jsonify(
                    {
                        "ok": True,
                        "answer": "La fecha indicada ya pasó. Elige una fecha de hoy en adelante.",
                    }
                )
            state["fecha"] = parsed.strftime("%Y-%m-%d")
            state["step"] = "awaiting_time"
            _guardar_cita_state(state)
            return jsonify({"ok": True, "answer": "Ahora indica la hora en formato HH:MM (24 horas)."})
        except ValueError:
            return jsonify({"ok": True, "answer": "Fecha inválida. Usa formato YYYY-MM-DD."})
    if step == "awaiting_time":
        try:
            parsed = datetime.strptime(q, "%H:%M")
            requested_dt = datetime.strptime(f"{state['fecha']} {parsed.strftime('%H:%M')}", "%Y-%m-%d %H:%M")
            if requested_dt <= datetime.now():
                return jsonify(
                    {
                        "ok": True,
                        "answer": "La fecha y hora indicadas ya pasaron. Escribe una hora futura.",
                    }
                )
            state["hora"] = parsed.strftime("%H:%M")
            state["step"] = "awaiting_pet"
            _guardar_cita_state(state)

            pets = _mascotas_usuario(int(state["cliente_id"]))
            if not pets:
                _reiniciar_cita_state()
                return jsonify({"ok": True, "answer": "No encontramos mascotas activas asociadas a tu cuenta."})

            pet_lines = [f"- {p['nombre']}" for p in pets]
            return jsonify(
                {
                    "ok": True,
                    "answer": (
                        "Estas son tus mascotas registradas:\n"
                        + "\n".join(pet_lines)
                        + "\n\nEscribe el nombre de la mascota para continuar."
                    ),
                }
            )
        except ValueError:
            return jsonify({"ok": True, "answer": "Hora inválida. Usa formato HH:MM en 24 horas."})

    # Confirmamos que la mascota seleccionada pertenezca al cliente.
    if step == "awaiting_pet":
        pets = _mascotas_usuario(int(state["cliente_id"]))
        requested_name = _normalizar_nombre_mascota(q)
        matches = [p for p in pets if _normalizar_nombre_mascota(p["nombre"]) == requested_name]
        if not matches:
            pet_lines = [f"- {p['nombre']}" for p in pets]
            return jsonify(
                {
                    "ok": True,
                    "answer": (
                        "No encontré una mascota activa con ese nombre en tu cuenta.\n"
                        + "\n".join(pet_lines)
                        + "\n\nEscribe uno de esos nombres para continuar."
                    ),
                }
            )
        if len(matches) > 1:
            return jsonify(
                {
                    "ok": True,
                    "answer": (
                        "Encontré varias mascotas con ese nombre en tu cuenta. "
                        "Por favor agenda la cita desde el módulo de citas para seleccionar la mascota correcta."
                    ),
                }
            )

        state["mascota_id"] = matches[0]["id"]
        state["step"] = "awaiting_reason"
        _guardar_cita_state(state)
        return jsonify({"ok": True, "answer": _mensaje_motivo_cita()})
    if step == "awaiting_reason":
        if q not in MOTIVO_CITA_OPTIONS:
            return jsonify(
                {
                    "ok": True,
                    "answer": (
                        "Por favor, elige una de las opciones proporcionadas:\n"
                        + _mensaje_motivo_cita()
                    ),
                }
            )

        state["motivo"] = MOTIVO_CITA_OPTIONS[q]
        return _finalizar_cita(me, state)

    _reiniciar_cita_state()
    return jsonify({"ok": True, "answer": "Reiniciamos el flujo. Escribe: Quiero agendar una cita"})


@chat_bp.get("/chat")
def pagina_chat():
    me = _obtener_usuario_actual()
    es_admin = _es_admin(me)

    try:
        _asegurar_preguntas_frecuentes_predeterminadas()
    except Exception:
        db.session.rollback()
        if es_admin:
            flash("No se pudieron sincronizar las FAQs iniciales.", "error")

    preguntas_frecuentes_rows = []
    try:
        preguntas_frecuentes_rows = _preguntas_frecuentes_rows() if es_admin else []
    except SQLAlchemyError:
        db.session.rollback()
        if es_admin:
            flash("No se pudieron cargar las FAQs para administración.", "error")

    quick_options = []
    try:
        quick_options = _chat_quick_options()
    except SQLAlchemyError:
        db.session.rollback()
        quick_options = list(PREGUNTAS_FRECUENTES_PREDETERMINADAS.keys()) + [OPCION_AGENDAR_LABEL, OPCION_CITAS_PENDIENTES_LABEL]

    return render_template(
        "chat.html",
        me=me,
        active_nav="chat",
        quick_options=quick_options,
        opcion_agendar_label=OPCION_AGENDAR_LABEL,
        es_admin=es_admin,
        preguntas_frecuentes_rows=preguntas_frecuentes_rows,
    )


@chat_bp.post("/chat/ask")
def consultar_chat():
    # Procesa una pregunta del chat y devuelve la respuesta adecuada.
    raw_question = (request.get_json(silent=True) or {}).get("question", "")
    question = raw_question.strip()
    me = _obtener_usuario_actual()
    normalized_question = _normalizar_texto_pregunta(question)

    if not question:
        return jsonify({"ok": False, "message": "Pregunta vacía."}), 400

    pending_appts_response = _procesar_citas_pendientes_step(me, raw_question)
    if pending_appts_response is not None:
        return pending_appts_response

    in_flow_response = _procesar_cita_step(me, question)
    if in_flow_response is not None:
        return in_flow_response

    if normalized_question == _normalizar_texto_pregunta(OPCION_AGENDAR_LABEL):
        if not me:
            return jsonify(
                {
                    "ok": True,
                    "answer": (
                        "Para agendar una cita necesitas iniciar sesión. "
                        f"También puedes hacerlo por llamada/WhatsApp al {_telefono_clinica()}."
                    ),
                }
            )

        try:
            _citas_table()
        except Exception:
            return jsonify(
                {
                    "ok": False,
                    "message": "No se pudo iniciar el agendado porque la tabla citas no existe en esta base de datos.",
                }
            ), 500

        return _iniciar_cita_flow(me)

    if normalized_question == _normalizar_texto_pregunta(OPCION_CITAS_PENDIENTES_LABEL):
        if not me:
            return jsonify(
                {
                    "ok": True,
                    "answer": (
                        "Para consultar tus citas pendientes necesitas iniciar sesión. "
                        f"También puedes hacerlo por llamada/WhatsApp al {_telefono_clinica()}."
                    ),
                }
            )
        try:
            _citas_table()
        except Exception:
            return jsonify(
                {
                    "ok": False,
                    "message": "No se pudo consultar las citas porque la tabla citas no existe en esta base de datos.",
                }
            ), 500
        return _iniciar_citas_pendientes_flow(me)

    try:
        table = _preguntas_frecuentes_table()
        question_col = _find_column(table, ["pregunta", "question"])
        answer_col = _find_column(table, ["respuesta", "answer"])
        if question_col is None or answer_col is None:
            return jsonify({"ok": False, "message": "No fue posible consultar las FAQs."}), 500

        faq_answer = None
        rows = db.session.execute(select(question_col, answer_col)).all()
        for row in rows:
            normalized_question = _normalizar_texto_pregunta(row[0] or "")
            if normalized_question == _normalizar_texto_pregunta(question):
                faq_answer = row[1]
                break

        if faq_answer is None:
            return jsonify(
                {
                    "ok": True,
                    "answer": "No encontré una respuesta configurada para esa pregunta.",
                }
            )

        return jsonify({"ok": True, "answer": faq_answer})
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Error consultando base de datos."}), 500


@chat_bp.post("/chat/faqs")
def crear_faq_chat():
    # Crea una nueva pregunta frecuente desde el panel de administración.
    me = _obtener_usuario_actual()
    if not _es_admin(me):
        return render_template("acceso_denegado.html", me=me), 403

    question = (request.form.get("pregunta") or "").strip()
    answer = (request.form.get("respuesta") or "").strip()
    if not question or not answer:
        flash("Pregunta y respuesta son obligatorias.", "error")
        return redirect(url_for("chat.pagina_chat"))

    try:
        table = _preguntas_frecuentes_table()
        payload = _construir_insert_payload(table, question, answer)
        db.session.execute(insert(table).values(**payload))
        db.session.commit()
        flash("FAQ creada correctamente.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"No se pudo crear la FAQ: {exc}", "error")
    return redirect(url_for("chat.pagina_chat"))


@chat_bp.post("/chat/faqs/<int:faq_id>/editar")
def editar_faq_chat(faq_id: int):
    me = _obtener_usuario_actual()
    if not _es_admin(me):
        return render_template("acceso_denegado.html", me=me), 403

    question = (request.form.get("pregunta") or "").strip()
    answer = (request.form.get("respuesta") or "").strip()
    if not question or not answer:
        flash("Pregunta y respuesta son obligatorias.", "error")
        return redirect(url_for("chat.pagina_chat"))

    try:
        table = _preguntas_frecuentes_table()
        id_col = _find_column(table, ["id"])
        question_col = _find_column(table, ["pregunta", "question"])
        answer_col = _find_column(table, ["respuesta", "answer"])
        if id_col is None or question_col is None or answer_col is None:
            flash("No fue posible editar: columnas esperadas no encontradas.", "error")
            return redirect(url_for("chat.pagina_chat"))

        db.session.execute(
            update(table)
            .where(id_col == faq_id)
            .values({question_col.name: question, answer_col.name: answer})
        )
        db.session.commit()
        flash("FAQ actualizada correctamente.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        flash("No se pudo actualizar la FAQ.", "error")
    return redirect(url_for("chat.pagina_chat"))


@chat_bp.post("/chat/reminders/send/<int:cita_id>")
def enviar_reminder_chat(cita_id: int):
    # Envía desde el chat un recordatorio de cita por correo.
    me = _obtener_usuario_actual()
    if not _es_admin(me):
        return render_template("acceso_denegado.html", me=me), 403

    try:
        citas = _citas_table()
        usuarios = _usuarios_table()
        recordatorios = _recordatorios_table()

        cita_id_col = _find_column(citas, ["id"])
        cita_cliente_col = _find_column(citas, ["cliente_id"])
        cita_fecha_col = _find_column(citas, ["fecha_hora"])
        cita_motivo_col = _find_column(citas, ["motivo"])
        if cita_id_col is None or cita_cliente_col is None or cita_fecha_col is None:
            return jsonify({"ok": False, "message": "Esquema de citas inválido."}), 500

        usuario_id_col = _find_column(usuarios, ["id"])
        user_correo_col = _find_column(usuarios, ["correo"])
        user_name_col = _find_column(usuarios, ["nombre"])
        if usuario_id_col is None or user_correo_col is None:
            return jsonify({"ok": False, "message": "Esquema de usuarios inválido."}), 500

        rem_id_col = _find_column(recordatorios, ["id"])
        rem_cita_col = _find_column(recordatorios, ["cita_id"])
        rem_estado_col = _find_column(recordatorios, ["estado"])
        rem_enviado_col = _find_column(recordatorios, ["enviado_en"])
        rem_confirmado_col = _find_column(recordatorios, ["confirmado"])
        rem_confirmado_en_col = _find_column(recordatorios, ["confirmado_en"])
        rem_token_col = _find_column(recordatorios, ["token_confirmacion"])
        if (
            rem_id_col is None
            or rem_cita_col is None
            or rem_estado_col is None
            or rem_confirmado_col is None
            or rem_token_col is None
        ):
            return jsonify({"ok": False, "message": "Esquema de recordatorios inválido."}), 500

        cita = db.session.execute(
            select(cita_cliente_col, cita_fecha_col, cita_motivo_col).where(cita_id_col == cita_id).limit(1)
        ).first()
        if not cita:
            return jsonify({"ok": False, "message": "La cita no existe."}), 404

        cliente_id, fecha_hora, motivo = cita
        user = db.session.execute(
            select(user_correo_col, user_name_col).where(usuario_id_col == cliente_id).limit(1)
        ).first()
        if not user:
            return jsonify({"ok": False, "message": "No se encontró el cliente de la cita."}), 404

        cliente_correo = (user[0] or "").strip()
        cliente_nombre = (user[1] or "Cliente").strip()
        if not cliente_correo:
            return jsonify({"ok": False, "message": "El cliente no tiene correo registrado."}), 400

        reminder = db.session.execute(
            select(rem_id_col).where(rem_cita_col == cita_id).limit(1)
        ).first()

        if reminder:
            reminder_id = int(reminder[0])
            programmed_payload = {
                rem_estado_col.name: "programado",
                rem_confirmado_col.name: False,
            }
            if rem_confirmado_en_col is not None:
                programmed_payload[rem_confirmado_en_col.name] = None
            db.session.execute(
                update(recordatorios)
                .where(rem_id_col == reminder_id)
                .values(programmed_payload)
            )
        else:
            result = db.session.execute(
                insert(recordatorios).values(
                    {
                        rem_cita_col.name: cita_id,
                        rem_estado_col.name: "programado",
                        rem_confirmado_col.name: False,
                    }
                )
            )
            reminder_id = int(result.inserted_primary_key[0])

        token = secrets.token_urlsafe(32)
        confirm_url = url_for("chat.confirmar_reminder_chat", token=token, _external=True)

        subject = "Recordatorio de cita - CIVE"
        body = (
            f"Hola {cliente_nombre},\n\n"
            "Este es un recordatorio de tu cita en CIVE.\n"
            f"Fecha y hora: {fecha_hora}\n"
            f"Motivo: {motivo or 'Sin motivo especificado'}\n\n"
            "Confirma recepción de este recordatorio en el siguiente enlace:\n"
            f"{confirm_url}\n"
        )

        sent_ok, sent_error = _enviar_email_smtp(cliente_correo, subject, body)
        if not sent_ok:
            db.session.commit()
            return jsonify({"ok": False, "message": f"No se pudo enviar el recordatorio: {sent_error}"}), 500

        update_payload = {
            rem_estado_col.name: "enviado",
            rem_token_col.name: token,
            rem_confirmado_col.name: False,
        }
        if rem_enviado_col is not None:
            update_payload[rem_enviado_col.name] = datetime.now()
        if rem_confirmado_en_col is not None:
            update_payload[rem_confirmado_en_col.name] = None

        db.session.execute(
            update(recordatorios)
            .where(rem_id_col == reminder_id)
            .values(update_payload)
        )
        db.session.commit()

        return jsonify(
            {
                "ok": True,
                "message": "Recordatorio enviado correctamente.",
                "recordatorio_id": reminder_id,
                "confirm_url": confirm_url,
            }
        )
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Error de base de datos enviando recordatorio."}), 500


@chat_bp.get("/chat/reminders/confirm/<string:token>")
def confirmar_reminder_chat(token: str):
    # Confirma que el cliente recibió el recordatorio enviado.
    try:
        recordatorios = _recordatorios_table()
        rem_id_col = _find_column(recordatorios, ["id"])
        rem_token_col = _find_column(recordatorios, ["token_confirmacion"])
        rem_confirmado_col = _find_column(recordatorios, ["confirmado"])
        rem_confirmado_en_col = _find_column(recordatorios, ["confirmado_en"])

        if rem_id_col is None or rem_token_col is None or rem_confirmado_col is None:
            return "<h3>No se pudo validar el recordatorio.</h3>", 500

        row = db.session.execute(
            select(rem_id_col, rem_confirmado_col).where(rem_token_col == token).limit(1)
        ).first()

        if not row:
            return "<h3>Enlace de confirmación inválido o expirado.</h3>", 404

        reminder_id = int(row[0])
        already_confirmed = bool(row[1])
        if already_confirmed:
            return "<h3>Este recordatorio ya estaba confirmado. Gracias.</h3>", 200

        payload = {rem_confirmado_col.name: True}
        if rem_confirmado_en_col is not None:
            payload[rem_confirmado_en_col.name] = datetime.now()

        db.session.execute(
            update(recordatorios)
            .where(rem_id_col == reminder_id)
            .values(payload)
        )
        db.session.commit()

        return "<h3>Recordatorio confirmado correctamente. Gracias.</h3>", 200
    except SQLAlchemyError:
        db.session.rollback()
        return "<h3>Error al confirmar el recordatorio.</h3>", 500
