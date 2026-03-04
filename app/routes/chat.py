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

# --- CONFIGURACION DEL CHAT ---
DEFAULT_FAQS = {
    "¿Cuál es el precio de la consulta?": "La consulta general tiene un costo base de $350 MXN.",
    "¿Cuáles son los horarios de la clínica?": "Nuestro horario es de lunes a sábado de 9:00 a 19:00 hrs.",
    "¿Cuál es la ubicación de la clínica?": "Estamos en Ecatepec, Estado de México. Te compartimos ubicación exacta por llamada o WhatsApp.",
}

SCHEDULE_OPTION_LABEL = "Quiero agendar una cita"

APPT_SESSION_KEY = "chat_appt_state"
EVAL_SESSION_KEY = "chat_eval_state"


# --- ACCESO DINAMICO A TABLAS ---
def _faq_table() -> Table:
    # Carga la tabla de preguntas frecuentes desde la base de datos.
    metadata = MetaData()
    return Table("chatbot_faq", metadata, autoload_with=db.engine)


def _citas_table() -> Table:
    # Carga la tabla de citas desde la base de datos.
    metadata = MetaData()
    return Table("citas", metadata, autoload_with=db.engine)


def _usuarios_table() -> Table:
    # Carga la tabla de usuarios desde la base de datos.
    metadata = MetaData()
    return Table("usuarios", metadata, autoload_with=db.engine)


def _recordatorios_table() -> Table:
    # Carga la tabla de recordatorios de citas desde la base de datos.
    metadata = MetaData()
    return Table("recordatorios_citas", metadata, autoload_with=db.engine)


def _encuestas_table() -> Table:
    # Carga la tabla de encuestas de satisfacción desde la base de datos.
    metadata = MetaData()
    return Table("encuestas_satisfaccion", metadata, autoload_with=db.engine)


def _roles_table() -> Table:
    # Carga la tabla de roles desde la base de datos.
    metadata = MetaData()
    return Table("roles", metadata, autoload_with=db.engine)


def _mascotas_table() -> Table:
    # Carga la tabla de mascotas desde la base de datos.
    metadata = MetaData()
    return Table("mascotas", metadata, autoload_with=db.engine)


# --- UTILIDADES DEL CHAT ---

def _get_current_user():
    # Obtiene al usuario autenticado desde la sesión actual.
    if not session.get("access_token"):
        return None
    return get_current_user_from_api()


def _is_admin(user_info) -> bool:
    # Verifica si el usuario actual tiene rol de administrador.
    return bool(user_info and (user_info.get("rol") or "").strip().lower() == "administrador")


def _find_col(table: Table, candidates: list[str]):
    # Busca la primera columna existente entre varios nombres posibles.
    for name in candidates:
        if name in table.c:
            return table.c[name]
    return None


def _required_columns_without_default(table: Table):
    # Obtiene las columnas obligatorias que requieren valor al insertar.
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


def _build_insert_payload(table: Table, question: str, answer: str):
    # Prepara los datos mínimos para guardar una pregunta frecuente.
    payload: dict[str, object] = {}
    question_col = _find_col(table, ["pregunta", "question"])
    answer_col = _find_col(table, ["respuesta", "answer"])

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


def _normalize_question_text(value: str) -> str:
    # Normaliza una pregunta para compararla sin diferencias de formato.
    normalized = (value or "").strip().lower()
    normalized = re.sub(r"^[¿?¡!\s]+|[¿?¡!\s]+$", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _faq_pairs():
    # Obtiene las preguntas frecuentes disponibles para el chat.
    table = _faq_table()
    question_col = _find_col(table, ["pregunta", "question"])
    answer_col = _find_col(table, ["respuesta", "answer"])
    if question_col is None or answer_col is None:
        return []

    rows = db.session.execute(
        select(question_col, answer_col).order_by(question_col.asc())
    ).all()
    return [{"pregunta": row[0], "respuesta": row[1]} for row in rows]


def _chat_quick_options():
    # Construye las opciones rápidas que se muestran en la interfaz del chat.
    options = []
    seen = set()
    for row in _faq_pairs():
        question = (row.get("pregunta") or "").strip()
        if not question:
            continue
        key = _normalize_question_text(question)
        if not key or key in seen:
            continue
        seen.add(key)
        options.append(question)

    options.append(SCHEDULE_OPTION_LABEL)
    return options


def _ensure_default_faqs():
    # Inserta las preguntas frecuentes iniciales si todavía no existen.
    table = _faq_table()
    question_col = _find_col(table, ["pregunta", "question"])
    answer_col = _find_col(table, ["respuesta", "answer"])
    if question_col is None or answer_col is None:
        return

    existing_rows = db.session.execute(select(question_col)).all()
    existing_norm = {_normalize_question_text((row[0] or "")) for row in existing_rows}

    for question, answer in DEFAULT_FAQS.items():
        if _normalize_question_text(question) in existing_norm:
            continue
        payload = _build_insert_payload(table, question, answer)
        db.session.execute(insert(table).values(**payload))
        existing_norm.add(_normalize_question_text(question))
    db.session.commit()


def _faq_rows():
    # Obtiene las preguntas frecuentes para su administración en pantalla.
    table = _faq_table()
    id_col = _find_col(table, ["id"])
    question_col = _find_col(table, ["pregunta", "question"])
    answer_col = _find_col(table, ["respuesta", "answer"])
    if id_col is None or question_col is None or answer_col is None:
        return []

    rows = db.session.execute(
        select(id_col, question_col, answer_col).order_by(id_col.desc())
    ).all()
    return [
        {"id": row[0], "pregunta": row[1], "respuesta": row[2]}
        for row in rows
    ]


def _clinic_phone() -> str:
    # Obtiene el teléfono configurado de la clínica.
    return os.getenv("CLINIC_PHONE", "No disponible")


def _reset_appt_state() -> None:
    # Limpia el estado del flujo de agendado en la sesión.
    session.pop(APPT_SESSION_KEY, None)


def _set_appt_state(state: dict) -> None:
    # Guarda el estado actual del flujo de agendado en la sesión.
    session[APPT_SESSION_KEY] = state
    session.modified = True


def _get_appt_state() -> dict | None:
    # Recupera el estado del flujo de agendado desde la sesión.
    state = session.get(APPT_SESSION_KEY)
    return state if isinstance(state, dict) else None


def _reset_eval_state() -> None:
    # Limpia el estado de la evaluación de servicio en la sesión.
    session.pop(EVAL_SESSION_KEY, None)


def _set_eval_state(state: dict) -> None:
    # Guarda el estado actual de la evaluación de servicio en la sesión.
    session[EVAL_SESSION_KEY] = state
    session.modified = True


def _get_eval_state() -> dict | None:
    # Recupera el estado de la evaluación de servicio desde la sesión.
    state = session.get(EVAL_SESSION_KEY)
    return state if isinstance(state, dict) else None


# --- FLUJO DE EVALUACION DE SERVICIO ---

def _latest_cita_id_for_cliente(cliente_id: int):
    # Obtiene la cita más reciente de un cliente.
    citas = _citas_table()
    cita_id_col = _find_col(citas, ["id"])
    cita_cliente_col = _find_col(citas, ["cliente_id"])
    cita_fecha_col = _find_col(citas, ["fecha_hora"])
    if cita_id_col is None or cita_cliente_col is None:
        return None

    order_col = cita_fecha_col if cita_fecha_col is not None else cita_id_col
    row = db.session.execute(
        select(cita_id_col).where(cita_cliente_col == cliente_id).order_by(order_col.desc()).limit(1)
    ).first()
    return int(row[0]) if row else None


def _start_evaluation(cliente_id: int, cita_id=None):
    # Inicia el flujo de encuesta de satisfacción al terminar una cita.
    resolved_cita_id = cita_id if cita_id is not None else _latest_cita_id_for_cliente(cliente_id)
    if resolved_cita_id is None:
        return None

    _set_eval_state(
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


def _save_evaluation(cliente_id: int, cita_id, calificacion: int, comentario: str):
    # Guarda en la base de datos la encuesta de satisfacción respondida.
    encuestas = _encuestas_table()
    col_cliente = _find_col(encuestas, ["cliente_id"])
    col_cita = _find_col(encuestas, ["cita_id"])
    col_calif = _find_col(encuestas, ["calificacion"])
    col_coment = _find_col(encuestas, ["comentario"])
    col_fecha = _find_col(encuestas, ["fecha_envio"])
    col_resp = _find_col(encuestas, ["respondido"])

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


def _handle_evaluation_step(me, question: str):
    # Procesa cada paso de la evaluación de satisfacción en el chat.
    state = _get_eval_state()
    if not state:
        return None

    if not me:
        _reset_eval_state()
        return jsonify({"ok": True, "answer": "Se canceló la evaluación por falta de sesión."})

    step = state.get("step")
    q = question.strip()

    # Validamos que la calificacion tenga un valor permitido.
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
        _set_eval_state(state)
        return jsonify(
            {
                "ok": True,
                "answer": "Por favor, escribe un comentario sobre el servicio.",
                "evaluation_step": "comment",
                "show_send_button": True,
            }
        )

    # Validamos y guardamos el comentario final de la encuesta.
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
            _save_evaluation(
                cliente_id=int(state["cliente_id"]),
                cita_id=state.get("cita_id"),
                calificacion=int(state["calificacion"]),
                comentario=question,
            )
        except Exception:
            db.session.rollback()
            return jsonify({"ok": False, "message": "No se pudo guardar la evaluación."}), 500

        _reset_eval_state()
        return jsonify(
            {
                "ok": True,
                "answer": "Gracias por tu evaluación. Tu respuesta fue registrada.",
                "evaluation_step": "done",
            }
        )

    _reset_eval_state()
    return jsonify({"ok": True, "answer": "Reiniciamos la evaluación. Escribe una calificación del 1 al 5."})


# --- FLUJO DE AGENDADO DE CITAS ---
def _user_pets(user_id: int):
    # Obtiene las mascotas activas asociadas al usuario actual.
    mascotas = _mascotas_table()
    id_col = _find_col(mascotas, ["id"])
    name_col = _find_col(mascotas, ["nombre"])
    owner_col = _find_col(mascotas, ["dueno_id", "cliente_id", "usuario_id"])
    status_col = _find_col(mascotas, ["estado", "estatus"])

    if id_col is None or name_col is None or owner_col is None:
        return []

    where_parts = [owner_col == user_id]
    if status_col is not None:
        where_parts.append(func.lower(status_col) == "activa")

    rows = db.session.execute(
        select(id_col, name_col).where(and_(*where_parts)).order_by(name_col.asc())
    ).all()

    return [{"id": int(r[0]), "nombre": r[1]} for r in rows]


def _not_canceled_clause(citas_table: Table):
    # Construye la condición para excluir citas canceladas.
    status_col = _find_col(citas_table, ["estado", "estatus"])
    canceled_col = _find_col(citas_table, ["cancelada"])

    clauses = []
    if status_col is not None:
        lowered = func.lower(func.trim(status_col))
        clauses.append(and_(lowered != "cancelada", lowered != "cancelado"))
    if canceled_col is not None:
        clauses.append(canceled_col.is_(False))

    if not clauses:
        return true()

    return and_(*clauses)


def _resolve_veterinario_id(fecha_hora: datetime):
    # Asigna un veterinario disponible para una fecha/hora específica basado en la carga de trabajo.
    citas = _citas_table()
    usuarios = _usuarios_table()
    roles = _roles_table()

    cita_fecha_col = _find_col(citas, ["fecha_hora"])
    cita_vet_col = _find_col(citas, ["veterinario_id"])
    if cita_fecha_col is None or cita_vet_col is None:
        return None

    user_id_col = _find_col(usuarios, ["id"])
    user_role_col = _find_col(usuarios, ["rol_id"])
    user_active_col = _find_col(usuarios, ["activo"])
    user_deleted_col = _find_col(usuarios, ["eliminado"])

    role_id_col = _find_col(roles, ["id"])
    role_name_col = _find_col(roles, ["nombre"])

    if any(col is None for col in (user_id_col, user_role_col, role_id_col, role_name_col)):
        return None

    vet_filters = [func.lower(role_name_col) == "veterinario"]
    if user_active_col is not None:
        vet_filters.append(user_active_col.is_(True))
    if user_deleted_col is not None:
        vet_filters.append(user_deleted_col.is_(False))

    vet_rows = db.session.execute(
        select(user_id_col)
        .select_from(usuarios.join(roles, user_role_col == role_id_col))
        .where(and_(*vet_filters))
    ).all()

    vet_ids = [int(r[0]) for r in vet_rows]
    if not vet_ids:
        return None

    not_canceled = _not_canceled_clause(citas)
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


def _send_email_smtp(to_email: str, subject: str, body: str):
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
    msg["To"] = to_email
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


def _start_appointment_flow(me):
    # Inicia el flujo guiado para agendar una cita desde el chat.
    try:
        user_id = int(me.get("id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "No se pudo validar tu sesión para agendar."}), 401

    pets = _user_pets(user_id)
    if not pets:
        _reset_appt_state()
        return jsonify(
            {
                "ok": True,
                "answer": "No encontramos mascotas asociadas a tu cuenta. Registra una mascota primero para agendar.",
            }
        )

    _set_appt_state({"step": "awaiting_date", "cliente_id": user_id})
    return jsonify(
        {
            "ok": True,
            "answer": "Perfecto, comencemos. Indica la fecha de la cita en formato YYYY-MM-DD.",
        }
    )


def _finalize_appointment(me, state):
    # Guarda la cita solicitada y envía las notificaciones correspondientes.
    citas = _citas_table()

    fecha_col = _find_col(citas, ["fecha_hora"])
    motivo_col = _find_col(citas, ["motivo"])
    cliente_col = _find_col(citas, ["cliente_id"])
    mascota_col = _find_col(citas, ["mascota_id"])
    vet_col = _find_col(citas, ["veterinario_id"])

    if any(col is None for col in (fecha_col, motivo_col, cliente_col, mascota_col, vet_col)):
        _reset_appt_state()
        return jsonify(
            {
                "ok": False,
                "message": "La tabla citas no tiene el esquema esperado (fecha_hora, motivo, cliente_id, mascota_id, veterinario_id).",
            }
        ), 500

    # Convertimos la fecha y la hora capturadas en un solo valor de cita.
    fecha_hora = datetime.strptime(f"{state['fecha']} {state['hora']}", "%Y-%m-%d %H:%M")

    # Buscamos un veterinario disponible para el horario solicitado.
    vet_id = _resolve_veterinario_id(fecha_hora)
    if vet_id is None:
        _reset_appt_state()
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
            _reset_appt_state()
            return jsonify(
                {
                    "ok": False,
                    "message": "No se pudo crear la cita porque faltan columnas requeridas: " + ", ".join(missing),
                }
            ), 500

        # Guardamos la cita y recuperamos su identificador.
        result = db.session.execute(insert(citas).values(**payload))
        db.session.commit()
        cita_id = result.inserted_primary_key[0] if result.inserted_primary_key else None
    except SQLAlchemyError:
        db.session.rollback()
        _reset_appt_state()
        return jsonify({"ok": False, "message": "No se pudo registrar la cita en la base de datos."}), 500

    admin_email = os.getenv("ADMIN_EMAIL", "").strip()
    cliente_email = (me.get("correo") or "").strip()
    cliente_nombre = (me.get("nombre") or "Cliente").strip()

    mascotas = _mascotas_table()
    pet_name_col = _find_col(mascotas, ["nombre"])
    pet_id_col = _find_col(mascotas, ["id"])
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
    if cliente_email:
        client_subject = "Solicitud de cita recibida - CIVE"
        client_body = (
            f"Hola {cliente_nombre},\n\n"
            "Recibimos tu solicitud de cita. Nuestro personal puede comunicarse contigo "
            "para confirmar o ajustar detalles.\n\n"
            f"Fecha/hora solicitada: {state['fecha']} {state['hora']}\n"
            f"Mascota: {mascota_nombre}\n"
            f"Motivo: {state['motivo']}\n"
        )
        client_mail_ok, _ = _send_email_smtp(cliente_email, client_subject, client_body)

    # Avisamos al administrador para que revise la nueva solicitud.
    if admin_email:
        admin_subject = "Nueva solicitud de cita - Acción requerida"
        admin_body = (
            "Se registró una nueva solicitud de cita.\n\n"
            f"Cliente: {cliente_nombre} ({cliente_email or 'sin correo'})\n"
            f"Mascota: {mascota_nombre} (ID {state['mascota_id']})\n"
            f"Fecha/hora solicitadas: {state['fecha']} {state['hora']}\n"
            f"Motivo: {state['motivo']}\n\n"
            "Instrucción: aceptar/rechazar."
        )
        admin_mail_ok, _ = _send_email_smtp(admin_email, admin_subject, admin_body)

    _reset_appt_state()

    # Iniciamos la encuesta de satisfaccion despues de registrar la cita.
    try:
        cliente_id_eval = int(state["cliente_id"])
        eval_response = _start_evaluation(cliente_id_eval, cita_id=cita_id)
        if eval_response is not None:
            eval_json = eval_response.get_json() or {}
            eval_json["answer"] = (
                "Tu solicitud de cita fue registrada correctamente. "
                "Te contactaremos para confirmar detalles.\n\n"
                + (eval_json.get("answer") or "")
            )
            eval_json["cita_id"] = cita_id
            eval_json["email_cliente_enviado"] = client_mail_ok
            eval_json["email_admin_enviado"] = admin_mail_ok
            return jsonify(eval_json)
    except Exception:
        pass

    return jsonify(
        {
            "ok": True,
            "answer": (
                "Tu solicitud de cita fue registrada correctamente. "
                "Te contactaremos para confirmar detalles."
            ),
            "cita_id": cita_id,
            "email_cliente_enviado": client_mail_ok,
            "email_admin_enviado": admin_mail_ok,
        }
    )


def _handle_appointment_step(me, question: str):
    # Procesa cada paso del flujo guiado para agendar una cita.
    state = _get_appt_state()
    if not state:
        return None

    if not me:
        _reset_appt_state()
        return jsonify(
            {
                "ok": True,
                "answer": f"Para agendar necesitas iniciar sesión. También puedes hacerlo por llamada/WhatsApp al {_clinic_phone()}.",
            }
        )

    step = state.get("step")
    q = question.strip()

    # Permitimos cancelar el flujo en cualquier momento.
    if q.lower() in {"cancelar", "cancelar cita", "salir"}:
        _reset_appt_state()
        return jsonify({"ok": True, "answer": "Flujo de agendado cancelado."})

    # Validamos la fecha que el cliente quiere reservar.
    if step == "awaiting_date":
        try:
            parsed = datetime.strptime(q, "%Y-%m-%d")
            state["fecha"] = parsed.strftime("%Y-%m-%d")
            state["step"] = "awaiting_time"
            _set_appt_state(state)
            return jsonify({"ok": True, "answer": "Ahora indica la hora en formato HH:MM (24 horas)."})
        except ValueError:
            return jsonify({"ok": True, "answer": "Fecha inválida. Usa formato YYYY-MM-DD."})

    # Validamos la hora y despues mostramos las mascotas disponibles.
    if step == "awaiting_time":
        try:
            parsed = datetime.strptime(q, "%H:%M")
            state["hora"] = parsed.strftime("%H:%M")
            state["step"] = "awaiting_pet"
            _set_appt_state(state)

            pets = _user_pets(int(state["cliente_id"]))
            if not pets:
                _reset_appt_state()
                return jsonify({"ok": True, "answer": "No encontramos mascotas activas asociadas a tu cuenta."})

            pet_lines = [f"{p['id']}: {p['nombre']}" for p in pets]
            return jsonify(
                {
                    "ok": True,
                    "answer": "Selecciona la mascota escribiendo su ID:\n" + "\n".join(pet_lines),
                }
            )
        except ValueError:
            return jsonify({"ok": True, "answer": "Hora inválida. Usa formato HH:MM en 24 horas."})

    # Confirmamos que la mascota seleccionada pertenezca al cliente.
    if step == "awaiting_pet":
        try:
            pet_id = int(q)
        except ValueError:
            return jsonify({"ok": True, "answer": "Debes escribir un ID numérico de mascota."})

        pets = _user_pets(int(state["cliente_id"]))
        pet_ids = {p["id"] for p in pets}
        if pet_id not in pet_ids:
            return jsonify({"ok": True, "answer": "La mascota indicada no pertenece a tu cuenta o no está activa."})

        state["mascota_id"] = pet_id
        state["step"] = "awaiting_reason"
        _set_appt_state(state)
        return jsonify({"ok": True, "answer": "Indica el motivo de la cita (obligatorio)."})

    # Guardamos el motivo y cerramos el agendado.
    if step == "awaiting_reason":
        if not q:
            return jsonify({"ok": True, "answer": "El motivo es obligatorio. Escríbelo para continuar."})

        state["motivo"] = q
        return _finalize_appointment(me, state)

    _reset_appt_state()
    return jsonify({"ok": True, "answer": "Reiniciamos el flujo. Escribe: Quiero agendar una cita"})


# --- RUTAS DEL CHAT ---
@chat_bp.get("/chat")
def chat_page():
    # Muestra la interfaz principal del chat y sus opciones rápidas.
    me = _get_current_user()
    is_admin = _is_admin(me)

    try:
        _ensure_default_faqs()
    except Exception:
        db.session.rollback()
        if is_admin:
            flash("No se pudieron sincronizar las FAQs iniciales.", "error")

    faq_rows = []
    try:
        faq_rows = _faq_rows() if is_admin else []
    except SQLAlchemyError:
        db.session.rollback()
        if is_admin:
            flash("No se pudieron cargar las FAQs para administración.", "error")

    quick_options = []
    try:
        quick_options = _chat_quick_options()
    except SQLAlchemyError:
        db.session.rollback()
        quick_options = list(DEFAULT_FAQS.keys()) + [SCHEDULE_OPTION_LABEL]

    return render_template(
        "chat.html",
        me=me,
        active_nav="chat",
        quick_options=quick_options,
        schedule_option_label=SCHEDULE_OPTION_LABEL,
        is_admin=is_admin,
        faq_rows=faq_rows,
    )


@chat_bp.post("/chat/ask")
def chat_ask():
    # Procesa una pregunta del chat y devuelve la respuesta adecuada.
    raw_question = (request.get_json(silent=True) or {}).get("question", "")
    question = raw_question.strip()
    me = _get_current_user()

    # Si el usuario cambia de opcion, reiniciamos la evaluacion para no mezclar flujos.
    eval_state = _get_eval_state()
    if eval_state and question:
        target = _normalize_question_text(question)
        faq_chip_selected = False
        try:
            table = _faq_table()
            question_col = _find_col(table, ["pregunta", "question"])
            if question_col is not None:
                rows = db.session.execute(select(question_col)).all()
                faq_chip_selected = any(
                    _normalize_question_text((row[0] or "")) == target for row in rows
                )
        except SQLAlchemyError:
            db.session.rollback()

        schedule_chip_selected = target == _normalize_question_text(SCHEDULE_OPTION_LABEL)
        if faq_chip_selected or schedule_chip_selected:
            _reset_eval_state()

    eval_response = _handle_evaluation_step(me, raw_question)
    if eval_response is not None:
        return eval_response

    if not question:
        return jsonify({"ok": False, "message": "Pregunta vacía."}), 400

    in_flow_response = _handle_appointment_step(me, question)
    if in_flow_response is not None:
        return in_flow_response

    if _normalize_question_text(question) == _normalize_question_text(SCHEDULE_OPTION_LABEL):
        if not me:
            return jsonify(
                {
                    "ok": True,
                    "answer": (
                        "Para agendar una cita necesitas iniciar sesión. "
                        f"También puedes hacerlo por llamada/WhatsApp al {_clinic_phone()}."
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

        return _start_appointment_flow(me)

    try:
        table = _faq_table()
        question_col = _find_col(table, ["pregunta", "question"])
        answer_col = _find_col(table, ["respuesta", "answer"])
        if question_col is None or answer_col is None:
            return jsonify({"ok": False, "message": "No fue posible consultar las FAQs."}), 500

        target = _normalize_question_text(question)
        faq_answer = None
        rows = db.session.execute(select(question_col, answer_col)).all()
        for row in rows:
            normalized_question = _normalize_question_text(row[0] or "")
            if normalized_question == target:
                faq_answer = row[1]
                break

        if faq_answer is None:
            return jsonify(
                {
                    "ok": True,
                    "answer": "No encontré una respuesta configurada para esa pregunta.",
                }
            )

        if me:
            try:
                cliente_id_eval = int(me.get("id"))
                eval_response = _start_evaluation(cliente_id_eval)
                if eval_response is not None:
                    eval_json = eval_response.get_json() or {}
                    eval_json["answer"] = f"{faq_answer}\n\n{eval_json.get('answer', '')}"
                    return jsonify(eval_json)
            except (TypeError, ValueError):
                pass

        return jsonify({"ok": True, "answer": faq_answer})
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "Error consultando base de datos."}), 500


@chat_bp.post("/chat/faqs")
def chat_faq_create():
    # Crea una nueva pregunta frecuente desde el panel de administración.
    me = _get_current_user()
    if not _is_admin(me):
        return render_template("acceso_denegado.html", me=me), 403

    question = (request.form.get("pregunta") or "").strip()
    answer = (request.form.get("respuesta") or "").strip()
    if not question or not answer:
        flash("Pregunta y respuesta son obligatorias.", "error")
        return redirect(url_for("chat.chat_page"))

    try:
        table = _faq_table()
        payload = _build_insert_payload(table, question, answer)
        db.session.execute(insert(table).values(**payload))
        db.session.commit()
        flash("FAQ creada correctamente.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"No se pudo crear la FAQ: {exc}", "error")
    return redirect(url_for("chat.chat_page"))


@chat_bp.post("/chat/faqs/<int:faq_id>/editar")
def chat_faq_edit(faq_id: int):
    # Actualiza una pregunta frecuente existente.
    me = _get_current_user()
    if not _is_admin(me):
        return render_template("acceso_denegado.html", me=me), 403

    question = (request.form.get("pregunta") or "").strip()
    answer = (request.form.get("respuesta") or "").strip()
    if not question or not answer:
        flash("Pregunta y respuesta son obligatorias.", "error")
        return redirect(url_for("chat.chat_page"))

    try:
        table = _faq_table()
        id_col = _find_col(table, ["id"])
        question_col = _find_col(table, ["pregunta", "question"])
        answer_col = _find_col(table, ["respuesta", "answer"])
        if id_col is None or question_col is None or answer_col is None:
            flash("No fue posible editar: columnas esperadas no encontradas.", "error")
            return redirect(url_for("chat.chat_page"))

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
    return redirect(url_for("chat.chat_page"))


@chat_bp.post("/chat/reminders/send/<int:cita_id>")
def chat_send_reminder(cita_id: int):
    # Envía desde el chat un recordatorio de cita por correo.
    me = _get_current_user()
    if not _is_admin(me):
        return render_template("acceso_denegado.html", me=me), 403

    try:
        citas = _citas_table()
        usuarios = _usuarios_table()
        recordatorios = _recordatorios_table()

        cita_id_col = _find_col(citas, ["id"])
        cita_cliente_col = _find_col(citas, ["cliente_id"])
        cita_fecha_col = _find_col(citas, ["fecha_hora"])
        cita_motivo_col = _find_col(citas, ["motivo"])
        if cita_id_col is None or cita_cliente_col is None or cita_fecha_col is None:
            return jsonify({"ok": False, "message": "Esquema de citas inválido."}), 500

        user_id_col = _find_col(usuarios, ["id"])
        user_email_col = _find_col(usuarios, ["correo"])
        user_name_col = _find_col(usuarios, ["nombre"])
        if user_id_col is None or user_email_col is None:
            return jsonify({"ok": False, "message": "Esquema de usuarios inválido."}), 500

        rem_id_col = _find_col(recordatorios, ["id"])
        rem_cita_col = _find_col(recordatorios, ["cita_id"])
        rem_estado_col = _find_col(recordatorios, ["estado"])
        rem_enviado_col = _find_col(recordatorios, ["enviado_en"])
        rem_confirmado_col = _find_col(recordatorios, ["confirmado"])
        rem_confirmado_en_col = _find_col(recordatorios, ["confirmado_en"])
        rem_token_col = _find_col(recordatorios, ["token_confirmacion"])
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
            select(user_email_col, user_name_col).where(user_id_col == cliente_id).limit(1)
        ).first()
        if not user:
            return jsonify({"ok": False, "message": "No se encontró el cliente de la cita."}), 404

        cliente_email = (user[0] or "").strip()
        cliente_nombre = (user[1] or "Cliente").strip()
        if not cliente_email:
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
        confirm_url = url_for("chat.chat_confirm_reminder", token=token, _external=True)

        subject = "Recordatorio de cita - CIVE"
        body = (
            f"Hola {cliente_nombre},\n\n"
            "Este es un recordatorio de tu cita en CIVE.\n"
            f"Fecha y hora: {fecha_hora}\n"
            f"Motivo: {motivo or 'Sin motivo especificado'}\n\n"
            "Confirma recepción de este recordatorio en el siguiente enlace:\n"
            f"{confirm_url}\n"
        )

        sent_ok, sent_error = _send_email_smtp(cliente_email, subject, body)
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
def chat_confirm_reminder(token: str):
    # Confirma que el cliente recibió el recordatorio enviado.
    try:
        recordatorios = _recordatorios_table()
        rem_id_col = _find_col(recordatorios, ["id"])
        rem_token_col = _find_col(recordatorios, ["token_confirmacion"])
        rem_confirmado_col = _find_col(recordatorios, ["confirmado"])
        rem_confirmado_en_col = _find_col(recordatorios, ["confirmado_en"])

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
