"""Módulo de encuestas."""

from __future__ import annotations

import os
import smtplib
from datetime import date, datetime, time, timedelta
from email.message import EmailMessage
from urllib.parse import quote

from flask import Blueprint, current_app, flash, has_request_context, redirect, render_template, request, session, url_for
from sqlalchemy import and_, func

from app.extensions import db
from app.models import Cita, EncuestaPregunta, EncuestaSatisfaccion, Mascota, Usuario
from utils.auth_ui import get_current_user_from_api

encuestas_bp = Blueprint("encuestas", __name__)

LOGIN_GET_ENDPOINT = "pages.pagina_inicio_sesion"

ROLE_ADMIN = "administrador"
ROLE_CLIENTE = "cliente"
ROLE_VETERINARIO = "veterinario"

QUESTION_DEFAULTS = {
    "conformidad": "¿Estás conforme con el servicio recibido?",
    "detalle_inconformidad": "Cuéntanos qué ocurrió para ayudarnos a mejorar.",
    "calificacion": "¿Cómo calificarías nuestro servicio?",
    "comentario": "Si tienes algún comentario adicional, compártelo con nosotros:",
}

MAX_COMMENT_LENGTH = 300


def _redirigir_a_inicio_sesion():
    """Función para redirigir a inicio sesion."""
    return redirect(url_for(LOGIN_GET_ENDPOINT))


def _redirigir_a_inicio_sesion_con_next(next_path: str):
    """Función para redirigir a inicio sesion con next."""
    return redirect(url_for(LOGIN_GET_ENDPOINT, next=next_path))


def _requiere_inicio_sesion_o_redirige():
    """Función para requiere inicio sesion o redirige."""
    if not session.get("access_token"):
        return _redirigir_a_inicio_sesion()
    return None


def _obtener_usuario_o_cerrar_sesion():
    """Función para obtener usuario o cerrar sesion."""
    if not session.get("access_token"):
        return None
    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return None
    return me


def _nombre_rol(me) -> str:
    """Función para nombre rol."""
    return (me.get("rol") or "").strip().lower()


def _parsear_entero(value):
    """Función para parsear entero."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parsear_fecha(value: str):
    """Función para parsear fecha."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _validar_periodo(fecha_inicio_raw: str, fecha_fin_raw: str):
    """Función para validar periodo."""
    errores_campo = {}
    fecha_inicio = _parsear_fecha(fecha_inicio_raw)
    fecha_fin = _parsear_fecha(fecha_fin_raw)
    hoy = date.today()

    if fecha_inicio_raw:
        if not fecha_inicio:
            errores_campo["fecha_inicio"] = "Debes seleccionar una fecha inicial válida."
        elif fecha_inicio > hoy:
            errores_campo["fecha_inicio"] = "La fecha inicial no puede ser posterior a hoy."

    if fecha_fin_raw:
        if not fecha_fin:
            errores_campo["fecha_fin"] = "Debes seleccionar una fecha final válida."
        elif fecha_fin > hoy:
            errores_campo["fecha_fin"] = "La fecha final no puede ser posterior a hoy."

    if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
        errores_campo["fecha_fin"] = "La fecha final no puede ser anterior a la fecha inicial."

    return errores_campo, fecha_inicio, fecha_fin


def _inicio_fin_datetime(fecha_inicio: date, fecha_fin: date):
    """Función para inicio fin datetime."""
    return (
        datetime.combine(fecha_inicio, time.min),
        datetime.combine(fecha_fin, time.max),
    )


def _clasificacion_por_calificacion(calificacion: int | None):
    """Función para clasificacion por calificacion."""
    if calificacion in {1, 2}:
        return "Experiencia negativa"
    if calificacion == 3:
        return "Experiencia neutral"
    if calificacion in {4, 5}:
        return "Experiencia positiva"
    return "-"


def _enviar_email_smtp(to_correo: str, subject: str, body: str):
    """Función para enviar email smtp."""
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


def _asegurar_preguntas_base():
    """Función para asegurar preguntas base."""
    changed = False
    for clave, texto in QUESTION_DEFAULTS.items():
        row = db.session.query(EncuestaPregunta).filter(EncuestaPregunta.clave == clave).first()
        if row:
            continue
        db.session.add(EncuestaPregunta(clave=clave, texto=texto))
        changed = True
    if changed:
        db.session.commit()


def _textos_preguntas():
    """Función para textos preguntas."""
    _asegurar_preguntas_base()
    rows = (
        db.session.query(EncuestaPregunta)
        .order_by(EncuestaPregunta.id.asc())
        .all()
    )
    preguntas = {row.clave: row.texto for row in rows}
    for clave, texto in QUESTION_DEFAULTS.items():
        preguntas.setdefault(clave, texto)
    return preguntas, rows


def _query_encuestas_base():
    """Función para query encuestas base."""
    return (
        db.session.query(
            EncuestaSatisfaccion,
            Cita,
            Mascota.nombre.label("mascota_nombre"),
            Usuario.nombre.label("cliente_nombre"),
        )
        .join(Cita, Cita.id == EncuestaSatisfaccion.cita_id)
        .join(Mascota, Mascota.id == Cita.mascota_id)
        .join(Usuario, Usuario.id == EncuestaSatisfaccion.cliente_id)
    )


def _encuestas_filtradas_por_periodo(rows, fecha_inicio: date | None, fecha_fin: date | None):
    """Función para encuestas filtradas por periodo."""
    filtered = []
    for encuesta, cita, mascota_nombre, cliente_nombre in rows:
        referencia = encuesta.fecha_respuesta or encuesta.fecha_programada_envio or cita.fecha_hora
        referencia_date = referencia.date() if isinstance(referencia, datetime) else referencia
        if fecha_inicio and referencia_date and referencia_date < fecha_inicio:
            continue
        if fecha_fin and referencia_date and referencia_date > fecha_fin:
            continue
        filtered.append((encuesta, cita, mascota_nombre, cliente_nombre))
    return filtered


def _resumen_dashboard(rows):
    """Función para resumen dashboard."""
    total = len(rows)
    respondidas = sum(1 for encuesta, *_ in rows if encuesta.respondido)
    pendientes = total - respondidas
    ratings = [encuesta.calificacion for encuesta, *_ in rows if encuesta.calificacion]
    promedio = round(sum(ratings) / len(ratings), 2) if ratings else None
    barras = []
    rating_counts = {score: 0 for score in range(1, 6)}
    sentiment_counts = {
        "Experiencia positiva": 0,
        "Experiencia neutral": 0,
        "Experiencia negativa": 0,
    }

    for encuesta, *_ in rows:
        if encuesta.calificacion in rating_counts:
            rating_counts[int(encuesta.calificacion)] += 1
            clasificacion = _clasificacion_por_calificacion(int(encuesta.calificacion))
            if clasificacion in sentiment_counts:
                sentiment_counts[clasificacion] += 1

    max_rating = max(rating_counts.values()) if rating_counts else 0
    for score in range(1, 6):
        value = rating_counts[score]
        barras.append(
            {
                "label": str(score),
                "value": value,
                "height_pct": (value / max_rating * 100) if max_rating else 0,
            }
        )

    max_sentiment = max(sentiment_counts.values()) if sentiment_counts else 0
    sentimientos = []
    for label, value in sentiment_counts.items():
        sentimientos.append(
            {
                "label": label,
                "value": value,
                "width_pct": (value / max_sentiment * 100) if max_sentiment else 0,
            }
        )

    return {
        "total": total,
        "respondidas": respondidas,
        "pendientes": pendientes,
        "promedio": promedio,
        "barras": barras,
        "sentimientos": sentimientos,
    }


def _path_encuesta(encuesta_id: int):
    """Función para path encuesta."""
    if has_request_context():
        return url_for("encuestas.encuesta_responder", encuesta_id=encuesta_id)
    with current_app.test_request_context():
        return url_for("encuestas.encuesta_responder", encuesta_id=encuesta_id)


def _login_url_para_encuesta(encuesta_id: int):
    """Función para login url para encuesta."""
    # URL pública de encuesta para correos.
    public_base_url = (current_app.config.get("PUBLIC_BASE_URL") or "").rstrip("/")
    next_path = _path_encuesta(encuesta_id)
    if public_base_url:
        return f"{public_base_url}/login?next={quote(next_path, safe='/')}"
    if has_request_context():
        return url_for(
            "pages.pagina_inicio_sesion",
            next=next_path,
            _external=True,
        )
    with current_app.test_request_context():
        return url_for(
            "pages.pagina_inicio_sesion",
            next=next_path,
            _external=True,
        )


def _generar_encuestas_pendientes(now: datetime):
    """Función para generar encuestas pendientes."""
    threshold = now - timedelta(hours=24)
    rows = (
        db.session.query(Cita)
        .outerjoin(EncuestaSatisfaccion, EncuestaSatisfaccion.cita_id == Cita.id)
        .filter(EncuestaSatisfaccion.id.is_(None))
        .filter(Cita.cancelada.is_(False), Cita.estado != "cancelada")
        .filter(Cita.fecha_hora <= threshold)
        .all()
    )
    created = False
    for cita in rows:
        db.session.add(
            EncuestaSatisfaccion(
                cita_id=cita.id,
                cliente_id=cita.cliente_id,
                fecha_programada_envio=cita.fecha_hora + timedelta(hours=24),
                respondido=False,
                correo_enviado=False,
            )
        )
        created = True
    if created:
        db.session.commit()


def _enviar_encuestas_programadas(now: datetime):
    """Función para enviar encuestas programadas."""
    rows = (
        _query_encuestas_base()
        .filter(EncuestaSatisfaccion.respondido.is_(False))
        .filter(EncuestaSatisfaccion.correo_enviado.is_(False))
        .filter(EncuestaSatisfaccion.fecha_programada_envio.isnot(None))
        .filter(EncuestaSatisfaccion.fecha_programada_envio <= now)
        .filter(Usuario.activo.is_(True), Usuario.eliminado.is_(False))
        .order_by(EncuestaSatisfaccion.fecha_programada_envio.asc(), EncuestaSatisfaccion.id.asc())
        .all()
    )

    for encuesta, cita, mascota_nombre, cliente_nombre in rows:
        cliente = db.session.get(Usuario, encuesta.cliente_id)
        correo = ((cliente.correo if cliente else "") or "").strip()
        if not correo:
            continue

        login_url = _login_url_para_encuesta(encuesta.id)
        subject = "Encuesta de satisfacción - CIVE"
        body = (
            f"Hola {cliente_nombre},\n\n"
            "Gracias por tu preferencia. Por favor, ayúdanos a mejorar respondiendo la siguiente encuesta:\n"
            f"{login_url}\n\n"
            f"Cita: {cita.fecha_hora.strftime('%Y-%m-%d %H:%M')}\n"
            f"Mascota: {mascota_nombre}\n\n"
            "Clínica CIVE"
        )
        sent_ok, _ = _enviar_email_smtp(correo, subject, body)
        if sent_ok:
            encuesta.correo_enviado = True
            encuesta.fecha_envio = now

    db.session.commit()


def sincronizar_encuestas_programadas():
    """Función para sincronizar encuestas programadas."""
    try:
        _asegurar_preguntas_base()
        now = datetime.now()
        _generar_encuestas_pendientes(now)
        _enviar_encuestas_programadas(now)
    except Exception:
        db.session.rollback()
        raise


def _datos_encuesta_para_cliente(cliente_id: int):
    """Función para datos encuesta para cliente."""
    return (
        _query_encuestas_base()
        .filter(EncuestaSatisfaccion.cliente_id == cliente_id)
        .order_by(EncuestaSatisfaccion.respondido.asc(), Cita.fecha_hora.desc())
        .all()
    )


def _encuesta_por_id(encuesta_id: int):
    """Función para encuesta por id."""
    return (
        _query_encuestas_base()
        .filter(EncuestaSatisfaccion.id == encuesta_id)
        .first()
    )


@encuestas_bp.get("/encuestas")
def encuestas_home():
    """Función para encuestas home."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    try:
        sincronizar_encuestas_programadas()
    except Exception:
        db.session.rollback()

    role = _nombre_rol(me)
    preguntas, preguntas_rows = _textos_preguntas()

    if role == ROLE_CLIENTE:
        cliente_id = _parsear_entero(me.get("id"))
        rows = _datos_encuesta_para_cliente(cliente_id) if cliente_id is not None else []
        summary = {
            "pendientes": sum(1 for encuesta, *_ in rows if not encuesta.respondido),
            "respondidas": sum(1 for encuesta, *_ in rows if encuesta.respondido),
            "enviadas": sum(1 for encuesta, *_ in rows if encuesta.correo_enviado),
        }
        return render_template(
            "encuestas_cliente.html",
            me=me,
            active_nav="encuestas",
            rows=rows,
            summary=summary,
            clasificacion_por_calificacion=_clasificacion_por_calificacion,
            preguntas=preguntas,
            now=datetime.now(),
        )

    if role not in {ROLE_ADMIN, ROLE_VETERINARIO}:
        return render_template("acceso_denegado.html", me=me), 403

    filters = {
        "fecha_inicio": (request.args.get("fecha_inicio") or "").strip(),
        "fecha_fin": (request.args.get("fecha_fin") or "").strip(),
    }
    errores_campo, fecha_inicio, fecha_fin = _validar_periodo(filters["fecha_inicio"], filters["fecha_fin"])

    rows = _query_encuestas_base().order_by(Cita.fecha_hora.desc(), EncuestaSatisfaccion.id.desc()).all()
    if not errores_campo:
        rows = _encuestas_filtradas_por_periodo(rows, fecha_inicio, fecha_fin)

    dashboard = _resumen_dashboard(rows)
    return render_template(
        "encuestas_dashboard.html",
        me=me,
        active_nav="encuestas",
        filters=filters,
        errores_campo=errores_campo,
        rows=rows,
        dashboard=dashboard,
        preguntas_rows=preguntas_rows,
        clasificacion_por_calificacion=_clasificacion_por_calificacion,
        can_edit_questions=role == ROLE_ADMIN,
    )


@encuestas_bp.post("/encuestas/preguntas")
def encuestas_actualizar_preguntas():
    """Función para encuestas actualizar preguntas."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if _nombre_rol(me) != ROLE_ADMIN:
        return render_template("acceso_denegado.html", me=me), 403

    _asegurar_preguntas_base()
    rows = db.session.query(EncuestaPregunta).all()
    for row in rows:
        nuevo_texto = (request.form.get(f"pregunta_{row.clave}") or "").strip()
        if not nuevo_texto:
            flash("Todas las preguntas deben tener texto.", "error")
            return redirect(url_for("encuestas.encuestas_home"))
        if len(nuevo_texto) > 255:
            flash("Cada pregunta debe tener un máximo de 255 caracteres.", "error")
            return redirect(url_for("encuestas.encuestas_home"))
        row.texto = nuevo_texto

    db.session.commit()
    flash("Preguntas actualizadas correctamente.", "success")
    return redirect(url_for("encuestas.encuestas_home"))


@encuestas_bp.route("/encuestas/<int:encuesta_id>/responder", methods=["GET", "POST"])
def encuesta_responder(encuesta_id: int):
    """Función para encuesta responder."""
    me = _obtener_usuario_o_cerrar_sesion()
    next_path = _path_encuesta(encuesta_id)
    if not me:
        return _redirigir_a_inicio_sesion_con_next(next_path)

    record = _encuesta_por_id(encuesta_id)
    if not record:
        flash("La encuesta no existe.", "error")
        return redirect(url_for("encuestas.encuestas_home"))

    encuesta, cita, mascota_nombre, cliente_nombre = record
    role = _nombre_rol(me)
    me_id = _parsear_entero(me.get("id"))

    if role == ROLE_CLIENTE and me_id != encuesta.cliente_id:
        return render_template("acceso_denegado.html", me=me), 403
    if role not in {ROLE_CLIENTE, ROLE_ADMIN, ROLE_VETERINARIO}:
        return render_template("acceso_denegado.html", me=me), 403

    preguntas, _ = _textos_preguntas()
    errors = {}
    form_data = {
        "conforme": "si" if encuesta.conforme is True else "no" if encuesta.conforme is False else "",
        "detalle_inconformidad": encuesta.detalle_inconformidad or "",
        "calificacion": str(encuesta.calificacion or ""),
        "comentario": encuesta.comentario or "",
    }

    if request.method == "POST":
        if role != ROLE_CLIENTE or encuesta.respondido:
            return render_template("acceso_denegado.html", me=me), 403

        conforme_raw = (request.form.get("conforme") or "").strip().lower()
        detalle_inconformidad = (request.form.get("detalle_inconformidad") or "").strip()
        calificacion = _parsear_entero(request.form.get("calificacion"))
        comentario = (request.form.get("comentario") or "").strip()
        form_data = {
            "conforme": conforme_raw,
            "detalle_inconformidad": detalle_inconformidad,
            "calificacion": request.form.get("calificacion") or "",
            "comentario": comentario,
        }

        if conforme_raw not in {"si", "no"}:
            errors["conforme"] = "Debes indicar si estás conforme con el servicio."

        if conforme_raw == "no" and not detalle_inconformidad:
            errors["detalle_inconformidad"] = "Debes explicar brevemente el motivo de tu inconformidad."
        if len(detalle_inconformidad) > MAX_COMMENT_LENGTH:
            errors["detalle_inconformidad"] = "El detalle de inconformidad no puede exceder 300 caracteres."

        if calificacion not in {1, 2, 3, 4, 5}:
            errors["calificacion"] = "Debes seleccionar una calificación válida."

        if len(comentario) > MAX_COMMENT_LENGTH:
            errors["comentario"] = "El comentario adicional no puede exceder 300 caracteres."

        if not errors:
            encuesta.conforme = conforme_raw == "si"
            encuesta.detalle_inconformidad = detalle_inconformidad or None
            encuesta.calificacion = calificacion
            encuesta.comentario = comentario or None
            encuesta.respondido = True
            encuesta.fecha_respuesta = datetime.now()
            db.session.commit()
            flash("Tu encuesta fue respondida correctamente.", "success")
            return redirect(url_for("encuestas.encuesta_responder", encuesta_id=encuesta.id))

    return render_template(
        "encuesta_form.html",
        me=me,
        active_nav="encuestas",
        encuesta=encuesta,
        cita=cita,
        mascota_nombre=mascota_nombre,
        cliente_nombre=cliente_nombre,
        preguntas=preguntas,
        errors=errors,
        form_data=form_data,
        read_only=encuesta.respondido or role in {ROLE_ADMIN, ROLE_VETERINARIO},
        clasificacion=_clasificacion_por_calificacion(encuesta.calificacion),
        now=datetime.now(),
    )
