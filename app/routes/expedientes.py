"""Módulo de expedientes."""

from __future__ import annotations

import os
import secrets
from io import BytesIO
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for, send_file
from PIL import Image as PilImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.utils import ImageReader
from sqlalchemy import func, or_
from sqlalchemy.orm import aliased
from werkzeug.utils import secure_filename

from app.extensions import db
from app.captcha import build_captcha, validate_captcha
from app.followups import (
    enviar_seguimiento_ahora,
    eliminar_seguimiento,
    fecha_hora_seguimiento_a_formato,
    guardar_seguimiento,
    obtener_mapa_seguimientos,
    obtener_mapa_seguimientos_por_ids,
    usuario_puede_programar_seguimiento,
    validar_programacion_seguimiento,
)
from app.models import (
    AnalisisClinico,
    Cita,
    ConsultaMedica,
    InsumoClinico,
    Mascota,
    Rol,
    Usuario,
    VacunaAlergia,
)
from utils.auth_ui import get_current_user_from_api

expedientes_bp = Blueprint("expedientes", __name__)

LOGIN_GET_ENDPOINT = "pages.pagina_inicio_sesion"

ROLE_ADMIN = "administrador"
ROLE_CLIENTE = "cliente"
ROLE_VETERINARIO = "veterinario"

PERMISSIONS = {
    "hu025": {ROLE_ADMIN, ROLE_VETERINARIO},
    "hu026": {ROLE_ADMIN, ROLE_VETERINARIO},
    "hu027": {ROLE_ADMIN, ROLE_CLIENTE, ROLE_VETERINARIO},
    "hu028": {ROLE_ADMIN, ROLE_CLIENTE, ROLE_VETERINARIO},
    "hu029": {ROLE_ADMIN, ROLE_VETERINARIO},
    "hu031": {ROLE_ADMIN, ROLE_VETERINARIO},
    "hu032": {ROLE_ADMIN},
}

MAX_FILE_SIZE = 2 * 1024 * 1024
ALLOWED_ANALISIS_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}
TIPO_ANALISIS_OPTIONS = [
    "Biometría hemática",
    "Química sanguínea",
    "Examen general de orina",
    "Coprológico",
    "Radiografía",
    "Ultrasonido",
    "Otro",
]
CONSULTA_BASE_PRICE = Decimal("300.00")
MAX_INSUMO_NOMBRE_LENGTH = 120
MAX_INVENTARIO_CANTIDAD = 99999
MAX_PRECIO = Decimal("30000.00")
MAX_CONSULTA_TEXTO_LENGTH = 300
MAX_OBSERVACIONES_LENGTH = 300
MAX_DOSIS_CANTIDAD = 100
MAX_PERIODO_ADMINISTRACION_LENGTH = 120
MAX_PERIODO_ADMINISTRACION_WORDS = 100
MAX_ALERGIA_NOMBRE_LENGTH = 120
MAX_REACCION_LENGTH = 300
MAX_NOTAS_ADICIONALES_LENGTH = 300
MAX_RESULTADOS_LENGTH = 300
MAX_NOTAS_ADJUNTO_LENGTH = 300
DOSIS_UNIDADES_OPTIONS = [
    "pastillas",
    "tabletas",
    "cápsulas",
    "gramos",
    "miligramos",
    "ml",
    "gotas",
    "ampolletas",
    "inyecciones",
    "sobres",
]


def _validar_longitud_maxima(value: str, field_name: str, max_length: int, errores_campo: dict, label: str):
    """Función para validar longitud maxima."""
    if value and len(value.strip()) > max_length:
        errores_campo[field_name] = f"{label} no puede exceder {max_length} caracteres."


def _contar_palabras(value: str) -> int:
    """Cuenta palabras usando espacios en blanco como separador."""
    return len((value or "").strip().split())


def _descomponer_dosis(dosis: str | None) -> tuple[str, str]:
    """Separa una dosis almacenada como texto en cantidad y unidad."""
    value = (dosis or "").strip()
    if not value:
        return "", ""
    parts = value.split(maxsplit=1)
    if len(parts) != 2:
        return value, ""
    cantidad, unidad = parts
    return cantidad.strip(), unidad.strip()


def _normalizar_dosis(cantidad_raw: str, unidad_raw: str) -> str:
    """Construye la dosis normalizada para persistencia."""
    cantidad = (cantidad_raw or "").strip()
    unidad = (unidad_raw or "").strip()
    if not cantidad or not unidad:
        return ""
    return f"{cantidad} {unidad}"


def _captcha_scope_inventario_create() -> str:
    """Construye el scope del captcha para alta de inventario."""
    return "inventario-create"


def _captcha_scope_inventario_edit(insumo_id: int) -> str:
    """Construye el scope del captcha para edición de inventario."""
    return f"inventario-edit-{insumo_id}"


def _captcha_scope_consulta_create(mascota_id: int) -> str:
    """Construye el scope del captcha para alta de consulta."""
    return f"consultas-create:{mascota_id}"


def _captcha_scope_consulta_edit(consulta_id: int) -> str:
    """Construye el scope del captcha para edición de consulta."""
    return f"consultas-edit:{consulta_id}"


def _captcha_scope_vacuna_create(mascota_id: int) -> str:
    """Construye el scope del captcha para alta de vacuna o alergia."""
    return f"vacunas-create:{mascota_id}"


def _captcha_scope_vacuna_edit(registro_id: int) -> str:
    """Construye el scope del captcha para edición de vacuna o alergia."""
    return f"vacunas-edit:{registro_id}"


def _captcha_scope_analisis_create(mascota_id: int) -> str:
    """Construye el scope del captcha para alta de análisis."""
    return f"analisis-create:{mascota_id}"


def _captcha_scope_analisis_edit(analisis_id: int) -> str:
    """Construye el scope del captcha para edición de análisis."""
    return f"analisis-edit:{analisis_id}"


def _build_pdf_styles():
    """Función para build pdf styles."""
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReporteTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#21272a"),
            alignment=TA_LEFT,
            spaceAfter=10,
        ),
        "subtitle": ParagraphStyle(
            "ReporteSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#697077"),
            spaceAfter=12,
        ),
        "section": ParagraphStyle(
            "ReporteSection",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#21272a"),
            spaceBefore=10,
            spaceAfter=6,
        ),
        "cell": ParagraphStyle(
            "ReporteCell",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#21272a"),
        ),
        "cell_bold": ParagraphStyle(
            "ReporteCellBold",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#21272a"),
        ),
        "cell_header": ParagraphStyle(
            "ReporteCellHeader",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=11,
            textColor=colors.white,
        ),
    }


def _pdf_paragraph(value, style):
    """Función para pdf paragraph."""
    text = str(value or "-").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
    return Paragraph(text, style)


def _pdf_table(headers, rows, widths, styles):
    """Función para pdf table."""
    data = [[_pdf_paragraph(header, styles["cell_header"]) for header in headers]]
    if rows:
        for row in rows:
            data.append([_pdf_paragraph(cell, styles["cell"]) for cell in row])
    else:
        data.append([_pdf_paragraph("Sin registros disponibles.", styles["cell"]) ] + [""] * (len(headers) - 1))

    table = Table(data, colWidths=widths, repeatRows=1)
    table_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f62fe")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dde1e6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    if not rows:
        table_style.extend([
            ("SPAN", (0, 1), (-1, 1)),
            ("ALIGN", (0, 1), (-1, 1), "LEFT"),
        ])
    table.setStyle(TableStyle(table_style))
    return table


def _header_with_logo(*, mascota, generated_at, styles):
    """Función para header with logo."""
    left_content = [
        _pdf_paragraph(f"Reporte clínico de {mascota.nombre}", styles["title"]),
        _pdf_paragraph(f"Generado el {generated_at.strftime('%Y-%m-%d %H:%M')}", styles["subtitle"]),
    ]

    left_table = Table([[left_content[0]], [left_content[1]]], colWidths=[110 * mm])
    left_table.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    logo_cell = ""
    logo_buffer, logo_size = _build_pdf_logo_asset()
    if logo_buffer and logo_size:
        try:
            img_width, img_height = logo_size
            target_width = 28 * mm
            scale = target_width / float(img_width or 1)
            target_height = img_height * scale
            logo_cell = Image(logo_buffer, width=target_width, height=target_height)
            logo_cell.hAlign = "RIGHT"
        except Exception:
            logo_cell = ""

    header = Table([[left_table, logo_cell]], colWidths=[120 * mm, 50 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return header


def _build_pdf_logo_asset():
    """Función para build pdf logo asset."""
    logo_path = os.path.join(current_app.root_path, "static", "images", "logo-cive.png")
    if not os.path.exists(logo_path):
        return None, None

    try:
        image = PilImage.open(logo_path).convert("RGBA")
        image.putalpha(int(255 * 0.6))

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)

        width, height = image.size
        return buffer, (width, height)
    except Exception:
        return None, None


def _construir_pdf_reporte_clinico(*, mascota, dueno_nombre, generated_at, edad_anos, consultas_rows, vacunas_rows, analisis_rows):
    """Función para construir pdf reporte clinico."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )
    styles = _build_pdf_styles()
    story = []

    story.append(_header_with_logo(mascota=mascota, generated_at=generated_at, styles=styles))
    story.append(Spacer(1, 8))

    story.append(_pdf_paragraph("Datos de la mascota", styles["section"]))
    pet_rows = [
        ["Nombre", mascota.nombre],
        ["Fecha de nacimiento", mascota.fecha_nacimiento.strftime("%Y-%m-%d") if mascota.fecha_nacimiento else "-"],
        ["Peso", f"{(mascota.peso or 0):.2f} kg"],
        ["Edad", f"{edad_anos} años" if edad_anos is not None else "-"],
        ["Raza", mascota.raza or "-"],
        ["Género", (mascota.sexo or "-").capitalize()],
        ["Dueño", dueno_nombre],
    ]
    story.append(_pdf_table(["Campo", "Valor"], pet_rows, [55 * mm, 115 * mm], styles))

    story.append(_pdf_paragraph("Historial de consultas y tratamientos", styles["section"]))
    consultas_data = [
        [
            consulta.fecha_consulta.strftime("%Y-%m-%d") if consulta.fecha_consulta else "-",
            veterinario_nombre,
            consulta.sintomas,
            consulta.diagnostico,
            consulta.tratamiento,
        ]
        for consulta, veterinario_nombre, medicamento_nombre in consultas_rows
    ]
    story.append(_pdf_table(
        ["Fecha", "Veterinario", "Síntomas", "Diagnóstico", "Tratamiento"],
        consultas_data,
        [22 * mm, 33 * mm, 38 * mm, 38 * mm, 39 * mm],
        styles,
    ))

    story.append(_pdf_paragraph("Medicamentos administrados", styles["section"]))
    meds_data = [
        [
            medicamento_nombre or consulta.medicamentos_administrados or "-",
            consulta.fecha_administracion.strftime("%Y-%m-%d") if consulta.fecha_administracion else "-",
            consulta.dosis or "-",
            consulta.periodo_administracion or "-",
            consulta.observaciones or "-",
        ]
        for consulta, veterinario_nombre, medicamento_nombre in consultas_rows
        if medicamento_nombre or consulta.medicamentos_administrados
    ]
    story.append(_pdf_table(
        ["Medicamento", "Fecha", "Dosis", "Período", "Observaciones"],
        meds_data,
        [35 * mm, 23 * mm, 22 * mm, 38 * mm, 52 * mm],
        styles,
    ))

    story.append(_pdf_paragraph("Vacunas aplicadas", styles["section"]))
    vacunas_data = [
        [
            vacuna.nombre,
            vacuna.fecha_registro.strftime("%Y-%m-%d") if vacuna.fecha_registro else "-",
            vacuna.notas_adicionales or "-",
        ]
        for vacuna in vacunas_rows
    ]
    story.append(_pdf_table(["Vacuna", "Fecha de administración", "Notas"], vacunas_data, [55 * mm, 40 * mm, 75 * mm], styles))

    story.append(_pdf_paragraph("Análisis clínicos", styles["section"]))
    analisis_data = [
        [
            analisis.fecha_analisis.strftime("%Y-%m-%d") if analisis.fecha_analisis else "-",
            analisis.tipo_analisis,
            analisis.resultados,
        ]
        for analisis in analisis_rows
    ]
    story.append(_pdf_table(["Fecha", "Tipo", "Resultados"], analisis_data, [28 * mm, 48 * mm, 94 * mm], styles))

    doc.build(story)
    buffer.seek(0)
    return buffer


def _redirigir_a_inicio_sesion():
    """Función para redirigir a inicio sesion."""
    return redirect(url_for(LOGIN_GET_ENDPOINT))


def _requiere_inicio_sesion_o_redirige():
    """Función para requiere inicio sesion o redirige."""
    if not session.get("access_token"):
        return _redirigir_a_inicio_sesion()
    return None


def _obtener_usuario_o_cerrar_sesion():
    """Función para obtener usuario o cerrar sesion."""
    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return None
    return me


def _nombre_rol(me) -> str:
    """Función para nombre rol."""
    return (me.get("rol") or "").strip().lower()


def _permitido(me, hu_code: str) -> bool:
    """Función para permitido."""
    return _nombre_rol(me) in PERMISSIONS.get(hu_code, set())


def _parsear_entero(value):
    """Función para parsear entero."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parsear_decimal(value: str):
    """Función para parsear decimal."""
    if value is None:
        return None
    raw = str(value).strip().replace(",", "")
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _parsear_fecha(value: str):
    """Función para parsear fecha."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _obtener_veterinarios_activos():
    """Función para obtener veterinarios activos."""
    return (
        db.session.query(Usuario)
        .join(Rol, Usuario.rol_id == Rol.id)
        .filter(func.lower(Rol.nombre) == ROLE_VETERINARIO)
        .filter(Usuario.eliminado.is_(False), Usuario.activo.is_(True))
        .order_by(Usuario.nombre.asc())
        .all()
    )


def _obtener_insumos(tipo: str | None = None, *, solo_activos: bool = False):
    """Función para obtener insumos."""
    q = db.session.query(InsumoClinico)
    if tipo in {"medicamento", "vacuna"}:
        q = q.filter(InsumoClinico.tipo_insumo == tipo)
    if solo_activos:
        q = q.filter(InsumoClinico.activo.is_(True), InsumoClinico.fecha_caducidad >= date.today())
    return q.order_by(InsumoClinico.nombre.asc()).all()


def _obtener_mascota_con_dueno(mascota_id: int):
    """Función para obtener mascota con dueno."""
    dueno = aliased(Usuario)
    return (
        db.session.query(
            Mascota,
            dueno.nombre.label("dueno_nombre"),
            dueno.correo.label("dueno_correo"),
            dueno.id.label("dueno_id"),
            dueno.activo.label("dueno_activo"),
        )
        .join(dueno, Mascota.dueno_id == dueno.id)
        .filter(Mascota.id == mascota_id)
        .first()
    )


def _usuario_puede_ver_mascota(me, mascota: Mascota) -> bool:
    """Función para usuario puede ver mascota."""
    role = _nombre_rol(me)
    me_id = _parsear_entero(me.get("id"))
    if role in {ROLE_ADMIN, ROLE_VETERINARIO}:
        return True
    if role == ROLE_CLIENTE and me_id is not None:
        return mascota.dueno_id == me_id
    return False


def _obtener_mascota_o_responder(me, mascota_id: int):
    """Función para obtener mascota o responder."""
    mascota_row = _obtener_mascota_con_dueno(mascota_id)
    if not mascota_row:
        flash("La mascota no existe.", "error")
        return None, redirect(url_for("expedientes.expedientes_lista"))

    mascota = mascota_row[0]
    if not _usuario_puede_ver_mascota(me, mascota):
        return None, render_template("acceso_denegado.html", me=me)

    return mascota_row, None


def _validar_fecha_no_futura(fecha, field_name: str, errores_campo: dict):
    """Función para validar fecha no futura."""
    if not fecha:
        errores_campo[field_name] = "Este campo no puede estar vacío."
        return
    if fecha > date.today():
        errores_campo[field_name] = "La fecha no puede ser posterior a hoy."


def _validar_veterinario(veterinario_id: int):
    """Función para validar veterinario."""
    if not veterinario_id:
        return None, "Este campo no puede estar vacío."

    veterinario = (
        db.session.query(Usuario)
        .join(Rol, Usuario.rol_id == Rol.id)
        .filter(Usuario.id == veterinario_id, Usuario.activo.is_(True), Usuario.eliminado.is_(False))
        .filter(func.lower(Rol.nombre) == ROLE_VETERINARIO)
        .first()
    )
    if not veterinario:
        return None, "El veterinario seleccionado no es válido."
    return veterinario, None


def _validar_archivo_analisis(uploaded):
    """Función para validar archivo analisis."""
    if not uploaded or not uploaded.filename:
        return None

    filename = secure_filename(uploaded.filename or "")
    if not filename:
        return "Debes seleccionar un archivo válido."

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_ANALISIS_EXTENSIONS:
        return "Solo puedes adjuntar archivos PDF, PNG, JPG o JPEG."

    uploaded.stream.seek(0, os.SEEK_END)
    size = uploaded.stream.tell()
    uploaded.stream.seek(0)
    if size > MAX_FILE_SIZE:
        return "El archivo adjunto no puede exceder 2MB."

    return None


def _guardar_archivo_analisis(uploaded, mascota_id: int):
    """Función para guardar archivo analisis."""
    filename = secure_filename(uploaded.filename or "")
    ext = filename.rsplit(".", 1)[-1].lower()
    token = secrets.token_hex(6)
    new_name = f"{token}.{ext}" if ext else f"{token}_{filename}"
    upload_dir = os.path.join(current_app.root_path, "private_uploads", "analisis", str(mascota_id))
    os.makedirs(upload_dir, exist_ok=True)
    abs_path = os.path.join(upload_dir, new_name)
    rel_path = os.path.join("analisis", str(mascota_id), new_name).replace("\\", "/")
    uploaded.save(abs_path)
    return rel_path, filename


def _resolver_archivo_analisis(rel_path: str | None):
    """Función para resolver archivo analisis."""
    if not rel_path:
        return None

    normalized = os.path.normpath(rel_path).replace("\\", "/").lstrip("/")
    if normalized.startswith(".."):
        return None

    candidates = [os.path.join(current_app.root_path, "private_uploads", normalized)]
    if normalized.startswith("uploads/"):
        candidates.append(os.path.join(current_app.root_path, "static", normalized))
    else:
        candidates.append(os.path.join(current_app.root_path, "static", "uploads", normalized))

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def _resumen_por_mascota(rows):
    """Función para resumen por mascota."""
    summary = {}
    for mascota_id, total in rows:
        summary[int(mascota_id)] = total
    return summary


def _ajustar_existencia_por_cambio(prev_insumo_id: int | None, new_insumo_id: int | None, field_name: str, errores_campo: dict):
    """Función para ajustar existencia por cambio."""
    if prev_insumo_id == new_insumo_id:
        return

    if prev_insumo_id:
        prev_insumo = db.session.get(InsumoClinico, prev_insumo_id)
        if prev_insumo:
            prev_insumo.cantidad_existencia = (prev_insumo.cantidad_existencia or 0) + 1

    if new_insumo_id:
        new_insumo = db.session.get(InsumoClinico, new_insumo_id)
        if not new_insumo or not new_insumo.activo:
            errores_campo[field_name] = "El insumo seleccionado no es válido."
            return
        if new_insumo.fecha_caducidad and new_insumo.fecha_caducidad < date.today():
            errores_campo[field_name] = "El insumo seleccionado está caducado."
            return
        if (new_insumo.cantidad_existencia or 0) <= 0:
            errores_campo[field_name] = "No hay existencias disponibles del insumo seleccionado."
            return
        new_insumo.cantidad_existencia = (new_insumo.cantidad_existencia or 0) - 1


def _datos_formulario_consulta(form=None, consulta: ConsultaMedica | None = None):
    """Función para datos formulario consulta."""
    form = form or {}
    if consulta is not None and not form:
        dosis_numero, dosis_unidad = _descomponer_dosis(consulta.dosis)
        return {
            "fecha_consulta": consulta.fecha_consulta.isoformat() if consulta.fecha_consulta else "",
            "veterinario_id": str(consulta.veterinario_id or ""),
            "sintomas": consulta.sintomas or "",
            "diagnostico": consulta.diagnostico or "",
            "tratamiento": consulta.tratamiento or "",
            "incluye_medicamento": bool(consulta.insumo_clinico_id),
            "insumo_clinico_id": str(consulta.insumo_clinico_id or ""),
            "fecha_administracion": consulta.fecha_administracion.isoformat() if consulta.fecha_administracion else "",
            "dosis": consulta.dosis or "",
            "dosis_numero": dosis_numero,
            "dosis_unidad": dosis_unidad,
            "periodo_administracion": consulta.periodo_administracion or "",
            "incluye_vacuna": bool(consulta.vacuna_insumo_id),
            "vacuna_insumo_id": str(consulta.vacuna_insumo_id or ""),
            "incluye_analisis": bool(consulta.tipo_analisis_relacionado),
            "tipo_analisis_relacionado": consulta.tipo_analisis_relacionado or "",
            "observaciones": consulta.observaciones or "",
            "medicamento_requiere_seguimiento": False,
            "medicamento_seguimiento_programado_para": "",
            "vacuna_requiere_seguimiento": False,
            "vacuna_seguimiento_programado_para": "",
            "analisis_requiere_seguimiento": False,
            "analisis_seguimiento_programado_para": "",
        }

    return {
        "fecha_consulta": (form.get("fecha_consulta") or "").strip(),
        "veterinario_id": str(_parsear_entero(form.get("veterinario_id")) or ""),
        "sintomas": (form.get("sintomas") or "").strip(),
        "diagnostico": (form.get("diagnostico") or "").strip(),
        "tratamiento": (form.get("tratamiento") or "").strip(),
        "incluye_medicamento": (form.get("incluye_medicamento") or "").strip().lower() in {"1", "true", "on", "yes"},
        "insumo_clinico_id": str(_parsear_entero(form.get("insumo_clinico_id")) or ""),
        "fecha_administracion": (form.get("fecha_administracion") or "").strip(),
        "dosis_numero": (form.get("dosis_numero") or "").strip(),
        "dosis_unidad": (form.get("dosis_unidad") or "").strip(),
        "dosis": _normalizar_dosis(form.get("dosis_numero") or "", form.get("dosis_unidad") or ""),
        "periodo_administracion": (form.get("periodo_administracion") or "").strip(),
        "incluye_vacuna": (form.get("incluye_vacuna") or "").strip().lower() in {"1", "true", "on", "yes"},
        "vacuna_insumo_id": str(_parsear_entero(form.get("vacuna_insumo_id")) or ""),
        "incluye_analisis": (form.get("incluye_analisis") or "").strip().lower() in {"1", "true", "on", "yes"},
        "tipo_analisis_relacionado": (form.get("tipo_analisis_relacionado") or "").strip(),
        "observaciones": (form.get("observaciones") or "").strip(),
        "medicamento_requiere_seguimiento": (form.get("medicamento_requiere_seguimiento") or "").strip().lower() in {"1", "true", "on", "yes"},
        "medicamento_seguimiento_programado_para": (form.get("medicamento_seguimiento_programado_para") or "").strip(),
        "vacuna_requiere_seguimiento": (form.get("vacuna_requiere_seguimiento") or "").strip().lower() in {"1", "true", "on", "yes"},
        "vacuna_seguimiento_programado_para": (form.get("vacuna_seguimiento_programado_para") or "").strip(),
        "analisis_requiere_seguimiento": (form.get("analisis_requiere_seguimiento") or "").strip().lower() in {"1", "true", "on", "yes"},
        "analisis_seguimiento_programado_para": (form.get("analisis_seguimiento_programado_para") or "").strip(),
    }


def _datos_formulario_vacuna(form=None, registro: VacunaAlergia | None = None):
    """Función para datos formulario vacuna."""
    form = form or {}
    if registro is not None and not form:
        return {
            "tipo_registro": registro.tipo_registro or "",
            "fecha_registro": registro.fecha_registro.isoformat() if registro.fecha_registro else "",
            "veterinario_id": str(registro.veterinario_id or ""),
            "insumo_clinico_id": str(registro.insumo_clinico_id or ""),
            "nombre": registro.nombre or "",
            "tiene_reaccion": bool(registro.reaccion_identificada),
            "reaccion_identificada": registro.reaccion_identificada or "",
            "notas_adicionales": registro.notas_adicionales or "",
            "vacuna_requiere_seguimiento": False,
            "vacuna_seguimiento_programado_para": "",
        }

    return {
        "tipo_registro": ((form.get("tipo_registro") or "").strip().lower()),
        "fecha_registro": (form.get("fecha_registro") or "").strip(),
        "veterinario_id": str(_parsear_entero(form.get("veterinario_id")) or ""),
        "insumo_clinico_id": str(_parsear_entero(form.get("insumo_clinico_id")) or ""),
        "nombre": (form.get("nombre") or "").strip(),
        "tiene_reaccion": (form.get("tiene_reaccion") or "").strip().lower() in {"1", "true", "on", "yes"},
        "reaccion_identificada": (form.get("reaccion_identificada") or "").strip(),
        "notas_adicionales": (form.get("notas_adicionales") or "").strip(),
        "vacuna_requiere_seguimiento": (form.get("vacuna_requiere_seguimiento") or "").strip().lower() in {"1", "true", "on", "yes"},
        "vacuna_seguimiento_programado_para": (form.get("vacuna_seguimiento_programado_para") or "").strip(),
    }


def _datos_formulario_analisis(form=None, analisis: AnalisisClinico | None = None):
    """Función para datos formulario analisis."""
    form = form or {}
    if analisis is not None and not form:
        return {
            "fecha_analisis": analisis.fecha_analisis.isoformat() if analisis.fecha_analisis else "",
            "veterinario_id": str(analisis.veterinario_id or ""),
            "tipo_analisis": analisis.tipo_analisis or "",
            "resultados": analisis.resultados or "",
            "precio": f"{(analisis.precio or Decimal('0')):.2f}",
            "documentos_adjuntos": analisis.documentos_adjuntos or "",
            "nombre_archivo": analisis.nombre_archivo or "",
            "analisis_requiere_seguimiento": False,
            "analisis_seguimiento_programado_para": "",
        }

    return {
        "fecha_analisis": (form.get("fecha_analisis") or "").strip(),
        "veterinario_id": str(_parsear_entero(form.get("veterinario_id")) or ""),
        "tipo_analisis": (form.get("tipo_analisis") or "").strip(),
        "resultados": (form.get("resultados") or "").strip(),
        "precio": (form.get("precio") or "").strip(),
        "documentos_adjuntos": (form.get("documentos_adjuntos") or "").strip(),
        "nombre_archivo": "",
        "analisis_requiere_seguimiento": (form.get("analisis_requiere_seguimiento") or "").strip().lower() in {"1", "true", "on", "yes"},
        "analisis_seguimiento_programado_para": (form.get("analisis_seguimiento_programado_para") or "").strip(),
    }


def _hidratar_datos_consulta_con_seguimientos(datos_formulario, consulta_id: int | None = None):
    """Función para hidratar datos consulta con seguimientos."""
    # Función de seguimiento clínico.
    if consulta_id is None:
        return datos_formulario
    seguimientos = obtener_mapa_seguimientos("consulta", consulta_id)
    datos_formulario["medicamento_requiere_seguimiento"] = "medicamento" in seguimientos
    datos_formulario["medicamento_seguimiento_programado_para"] = fecha_hora_seguimiento_a_formato(
        seguimientos.get("medicamento").programado_para if seguimientos.get("medicamento") else None
    )
    datos_formulario["vacuna_requiere_seguimiento"] = "vacuna" in seguimientos
    datos_formulario["vacuna_seguimiento_programado_para"] = fecha_hora_seguimiento_a_formato(
        seguimientos.get("vacuna").programado_para if seguimientos.get("vacuna") else None
    )
    datos_formulario["analisis_requiere_seguimiento"] = "analisis" in seguimientos
    datos_formulario["analisis_seguimiento_programado_para"] = fecha_hora_seguimiento_a_formato(
        seguimientos.get("analisis").programado_para if seguimientos.get("analisis") else None
    )
    return datos_formulario


def _hidratar_datos_vacuna_con_seguimiento(datos_formulario, registro_id: int | None = None):
    """Función para hidratar datos vacuna con seguimiento."""
    # Función de seguimiento clínico.
    if registro_id is None:
        return datos_formulario
    seguimiento = obtener_mapa_seguimientos("vacuna_alergia", registro_id).get("vacuna")
    datos_formulario["vacuna_requiere_seguimiento"] = seguimiento is not None
    datos_formulario["vacuna_seguimiento_programado_para"] = fecha_hora_seguimiento_a_formato(
        seguimiento.programado_para if seguimiento else None
    )
    return datos_formulario


def _hidratar_datos_analisis_con_seguimiento(datos_formulario, analisis_id: int | None = None):
    """Función para hidratar datos analisis con seguimiento."""
    # Función de seguimiento clínico.
    if analisis_id is None:
        return datos_formulario
    seguimiento = obtener_mapa_seguimientos("analisis_clinico", analisis_id).get("analisis")
    datos_formulario["analisis_requiere_seguimiento"] = seguimiento is not None
    datos_formulario["analisis_seguimiento_programado_para"] = fecha_hora_seguimiento_a_formato(
        seguimiento.programado_para if seguimiento else None
    )
    return datos_formulario


def _datos_formulario_insumo(form=None, insumo: InsumoClinico | None = None):
    """Función para datos formulario insumo."""
    form = form or {}
    if insumo is not None and not form:
        return {
            "nombre": insumo.nombre or "",
            "tipo_insumo": insumo.tipo_insumo or "",
            "fecha_caducidad": insumo.fecha_caducidad.isoformat() if insumo.fecha_caducidad else "",
            "cantidad_existencia": str(insumo.cantidad_existencia if insumo.cantidad_existencia is not None else ""),
            "precio": f"{(insumo.precio or Decimal('0')):.2f}",
            "activo": insumo.activo,
        }

    return {
        "nombre": (form.get("nombre") or "").strip(),
        "tipo_insumo": ((form.get("tipo_insumo") or "").strip().lower()),
        "fecha_caducidad": (form.get("fecha_caducidad") or "").strip(),
        "cantidad_existencia": (form.get("cantidad_existencia") or "").strip(),
        "precio": (form.get("precio") or "").strip(),
        "activo": (not form) or ((form.get("activo") or "").strip().lower() in {"1", "true", "on", "yes"}),
    }


@expedientes_bp.get("/expedientes")
def expedientes_lista():
    """Función para expedientes lista."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _permitido(me, "hu027"):
        return render_template("acceso_denegado.html", me=me)

    estado = ((request.args.get("estado") or "").strip().lower())
    busqueda = (request.args.get("q") or "").strip()

    dueno = aliased(Usuario)
    q = (
        db.session.query(
            Mascota,
            dueno.nombre.label("dueno_nombre"),
            dueno.activo.label("dueno_activo"),
        )
        .join(dueno, Mascota.dueno_id == dueno.id)
        .filter(dueno.eliminado.is_(False))
    )

    me_id = _parsear_entero(me.get("id"))
    if _nombre_rol(me) == ROLE_CLIENTE and me_id is not None:
        q = q.filter(Mascota.dueno_id == me_id)

    if estado in {"activa", "inactiva"}:
        q = q.filter(Mascota.estado == estado)

    if busqueda:
        pattern = f"%{busqueda}%"
        q = q.filter(or_(Mascota.nombre.ilike(pattern), Mascota.raza.ilike(pattern), dueno.nombre.ilike(pattern)))

    mascotas_rows = q.order_by(Mascota.nombre.asc()).all()
    mascota_ids = [mascota.id for mascota, _, _ in mascotas_rows]

    consultas_summary = {}
    vacunas_summary = {}
    analisis_summary = {}
    ultimas_consultas = {}

    if mascota_ids:
        consultas_summary = _resumen_por_mascota(
            db.session.query(ConsultaMedica.mascota_id, func.count(ConsultaMedica.id))
            .filter(ConsultaMedica.mascota_id.in_(mascota_ids))
            .group_by(ConsultaMedica.mascota_id)
            .all()
        )
        vacunas_summary = _resumen_por_mascota(
            db.session.query(VacunaAlergia.mascota_id, func.count(VacunaAlergia.id))
            .filter(VacunaAlergia.mascota_id.in_(mascota_ids))
            .group_by(VacunaAlergia.mascota_id)
            .all()
        )
        analisis_summary = _resumen_por_mascota(
            db.session.query(AnalisisClinico.mascota_id, func.count(AnalisisClinico.id))
            .filter(AnalisisClinico.mascota_id.in_(mascota_ids))
            .group_by(AnalisisClinico.mascota_id)
            .all()
        )
        for row in (
            db.session.query(ConsultaMedica.mascota_id, func.max(ConsultaMedica.fecha_consulta))
            .filter(ConsultaMedica.mascota_id.in_(mascota_ids))
            .group_by(ConsultaMedica.mascota_id)
            .all()
        ):
            ultimas_consultas[int(row[0])] = row[1]

    return render_template(
        "expedientes_list.html",
        me=me,
        active_nav="expedientes",
        mascotas_rows=mascotas_rows,
        filters={"estado": estado, "q": busqueda},
        consultas_summary=consultas_summary,
        vacunas_summary=vacunas_summary,
        analisis_summary=analisis_summary,
        ultimas_consultas=ultimas_consultas,
        can_manage_consultas=_permitido(me, "hu025"),
        can_manage_vacunas=_permitido(me, "hu029"),
        can_manage_analisis=_permitido(me, "hu031"),
        can_manage_inventory=_permitido(me, "hu032"),
    )


@expedientes_bp.get("/expedientes/inventario")
def inventario_lista():
    """Función para inventario lista."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _permitido(me, "hu032"):
        return render_template("acceso_denegado.html", me=me)

    tipo = ((request.args.get("tipo") or "").strip().lower())
    q = db.session.query(InsumoClinico)
    if tipo in {"medicamento", "vacuna"}:
        q = q.filter(InsumoClinico.tipo_insumo == tipo)

    insumos = q.order_by(InsumoClinico.tipo_insumo.asc(), InsumoClinico.nombre.asc()).all()
    return render_template(
        "inventario_clinico_list.html",
        me=me,
        active_nav="expedientes",
        insumos=insumos,
        filters={"tipo": tipo},
    )


@expedientes_bp.route("/expedientes/inventario/nuevo", methods=["GET", "POST"])
def inventario_nuevo():
    """Función para inventario nuevo."""
    return _guardar_insumo()


@expedientes_bp.route("/expedientes/inventario/<int:insumo_id>/editar", methods=["GET", "POST"])
def inventario_editar(insumo_id: int):
    """Función para inventario editar."""
    return _guardar_insumo(insumo_id=insumo_id)


def _guardar_insumo(insumo_id: int | None = None):
    """Función para guardar insumo."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _permitido(me, "hu032"):
        return render_template("acceso_denegado.html", me=me)

    insumo = db.session.get(InsumoClinico, insumo_id) if insumo_id is not None else None
    if insumo_id is not None and not insumo:
        flash("El insumo clínico solicitado no existe.", "error")
        return redirect(url_for("expedientes.inventario_lista"))

    if request.method == "GET":
        captcha_scope = _captcha_scope_inventario_edit(insumo.id) if insumo else _captcha_scope_inventario_create()
        return render_template(
            "inventario_clinico_form.html",
            me=me,
            active_nav="expedientes",
            mode="edit" if insumo else "create",
            insumo_id=insumo.id if insumo else None,
            datos_formulario=_datos_formulario_insumo(insumo=insumo),
            errores_campo={},
            captcha=build_captcha(captcha_scope),
        )

    datos_formulario = _datos_formulario_insumo(request.form)
    errores_campo = {}
    captcha_scope = _captcha_scope_inventario_edit(insumo.id) if insumo else _captcha_scope_inventario_create()

    if not datos_formulario["nombre"]:
        errores_campo["nombre"] = "Debes capturar el nombre para continuar."
    else:
        _validar_longitud_maxima(datos_formulario["nombre"], "nombre", MAX_INSUMO_NOMBRE_LENGTH, errores_campo, "El nombre")

    if datos_formulario["tipo_insumo"] not in {"medicamento", "vacuna"}:
        errores_campo["tipo_insumo"] = "Debes seleccionar un tipo de insumo válido."

    fecha_caducidad = _parsear_fecha(datos_formulario["fecha_caducidad"])
    if not fecha_caducidad:
        errores_campo["fecha_caducidad"] = "Este campo no puede estar vacío."
    elif fecha_caducidad < date.today():
        errores_campo["fecha_caducidad"] = "La fecha de caducidad no puede ser anterior a hoy."

    cantidad_existencia = _parsear_entero(datos_formulario["cantidad_existencia"])
    if cantidad_existencia is None:
        errores_campo["cantidad_existencia"] = "Debes capturar una cantidad válida."
    elif cantidad_existencia < 0:
        errores_campo["cantidad_existencia"] = "La cantidad no puede ser menor a 0."
    elif cantidad_existencia > MAX_INVENTARIO_CANTIDAD:
        errores_campo["cantidad_existencia"] = f"La cantidad no puede exceder {MAX_INVENTARIO_CANTIDAD} unidades."

    precio = _parsear_decimal(datos_formulario["precio"])
    if precio is None:
        errores_campo["precio"] = "Debes capturar un precio válido."
    elif precio < 0:
        errores_campo["precio"] = "El precio no puede ser menor a 0."
    elif precio > MAX_PRECIO:
        errores_campo["precio"] = f"El precio no puede exceder ${MAX_PRECIO}."

    captcha_answer = (request.form.get("captcha_answer") or "").strip()
    if not captcha_answer:
        errores_campo["captcha"] = "Debes resolver el captcha para continuar."
    elif not validate_captcha(captcha_scope, captcha_answer):
        errores_campo["captcha"] = "Respuesta errónea. Intenta nuevamente para completar la acción"

    if errores_campo:
        return render_template(
            "inventario_clinico_form.html",
            me=me,
            active_nav="expedientes",
            mode="edit" if insumo else "create",
            insumo_id=insumo.id if insumo else None,
            datos_formulario=datos_formulario,
            errores_campo=errores_campo,
            captcha=build_captcha(captcha_scope),
        )

    if insumo is None:
        insumo = InsumoClinico()
        db.session.add(insumo)

    insumo.nombre = datos_formulario["nombre"]
    insumo.tipo_insumo = datos_formulario["tipo_insumo"]
    insumo.fecha_caducidad = fecha_caducidad
    insumo.cantidad_existencia = cantidad_existencia
    insumo.precio = precio
    insumo.activo = datos_formulario["activo"]

    db.session.commit()
    flash("Insumo clínico actualizado correctamente." if insumo_id else "Insumo clínico registrado correctamente.", "success")
    return redirect(url_for("expedientes.inventario_lista"))


@expedientes_bp.get("/expedientes/<int:mascota_id>")
@expedientes_bp.get("/expedientes/<int:mascota_id>/editar")
def expedientes_detalle(mascota_id: int):
    """Función para expedientes detalle."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _permitido(me, "hu027"):
        return render_template("acceso_denegado.html", me=me)

    mascota_row, response = _obtener_mascota_o_responder(me, mascota_id)
    if response:
        return response

    mascota = mascota_row[0]
    cliente = aliased(Usuario)
    veterinario_cita = aliased(Usuario)
    veterinario_consulta = aliased(Usuario)
    veterinario_vacuna = aliased(Usuario)
    veterinario_analisis = aliased(Usuario)
    insumo_medicamento = aliased(InsumoClinico)
    insumo_vacuna = aliased(InsumoClinico)

    citas_rows = (
        db.session.query(
            Cita,
            cliente.nombre.label("cliente_nombre"),
            veterinario_cita.nombre.label("veterinario_nombre"),
        )
        .join(cliente, Cita.cliente_id == cliente.id)
        .join(veterinario_cita, Cita.veterinario_id == veterinario_cita.id)
        .filter(Cita.mascota_id == mascota.id)
        .order_by(Cita.fecha_hora.desc(), Cita.id.desc())
        .all()
    )

    consultas_rows = (
        db.session.query(
            ConsultaMedica,
            veterinario_consulta.nombre.label("veterinario_nombre"),
            insumo_medicamento.nombre.label("medicamento_nombre"),
            insumo_vacuna.nombre.label("vacuna_nombre"),
        )
        .join(veterinario_consulta, ConsultaMedica.veterinario_id == veterinario_consulta.id)
        .outerjoin(insumo_medicamento, ConsultaMedica.insumo_clinico_id == insumo_medicamento.id)
        .outerjoin(insumo_vacuna, ConsultaMedica.vacuna_insumo_id == insumo_vacuna.id)
        .filter(ConsultaMedica.mascota_id == mascota.id)
        .order_by(ConsultaMedica.fecha_consulta.desc(), ConsultaMedica.id.desc())
        .all()
    )

    vacunas_rows = (
        db.session.query(VacunaAlergia, veterinario_vacuna.nombre.label("veterinario_nombre"))
        .join(veterinario_vacuna, VacunaAlergia.veterinario_id == veterinario_vacuna.id)
        .filter(VacunaAlergia.mascota_id == mascota.id)
        .order_by(VacunaAlergia.fecha_registro.desc(), VacunaAlergia.id.desc())
        .all()
    )

    analisis_rows = (
        db.session.query(AnalisisClinico, veterinario_analisis.nombre.label("veterinario_nombre"))
        .join(veterinario_analisis, AnalisisClinico.veterinario_id == veterinario_analisis.id)
        .filter(AnalisisClinico.mascota_id == mascota.id)
        .order_by(AnalisisClinico.fecha_analisis.desc(), AnalisisClinico.id.desc())
        .all()
    )
    consulta_followups = obtener_mapa_seguimientos_por_ids("consulta", [row[0].id for row in consultas_rows])
    vacuna_followups = obtener_mapa_seguimientos_por_ids("vacuna_alergia", [row[0].id for row in vacunas_rows])
    analisis_followups = obtener_mapa_seguimientos_por_ids("analisis_clinico", [row[0].id for row in analisis_rows])

    return render_template(
        "expediente_detalle.html",
        me=me,
        active_nav="expedientes",
        mascota=mascota,
        dueno_nombre=mascota_row.dueno_nombre,
        dueno_correo=mascota_row.dueno_correo,
        dueno_activo=mascota_row.dueno_activo,
        citas_rows=citas_rows,
        consultas_rows=consultas_rows,
        vacunas_rows=vacunas_rows,
        analisis_rows=analisis_rows,
        consulta_followups=consulta_followups,
        vacuna_followups=vacuna_followups,
        analisis_followups=analisis_followups,
        can_manage_consultas=_permitido(me, "hu025"),
        can_manage_vacunas=_permitido(me, "hu029"),
        can_manage_analisis=_permitido(me, "hu031"),
        can_manage_inventory=_permitido(me, "hu032"),
        can_print_report=_permitido(me, "hu028"),
        can_edit_expediente=_nombre_rol(me) in {ROLE_ADMIN, ROLE_VETERINARIO},
        can_behavior=_nombre_rol(me) in {ROLE_ADMIN, ROLE_VETERINARIO},
        can_multimedia=_nombre_rol(me) in {ROLE_ADMIN, ROLE_VETERINARIO},
        can_schedule_followup=usuario_puede_programar_seguimiento(me),
    )


@expedientes_bp.post("/expedientes/seguimientos/<int:seguimiento_id>/recordar-ahora")
def expedientes_recordar_seguimiento_ahora(seguimiento_id: int):
    """Función para expedientes recordar seguimiento ahora."""
    # Botón temporal de demostración de seguimiento.
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not usuario_puede_programar_seguimiento(me):
        return render_template("acceso_denegado.html", me=me)

    sent_ok, sent_error = enviar_seguimiento_ahora(seguimiento_id)
    if not sent_ok:
        flash(sent_error or "No fue posible enviar el seguimiento.", "error")
    else:
        db.session.commit()
        flash("Seguimiento enviado correctamente por correo.", "success")

    mascota_id = _parsear_entero(request.form.get("mascota_id"))
    if mascota_id:
        return redirect(url_for("expedientes.expedientes_detalle", mascota_id=mascota_id))
    return redirect(url_for("expedientes.expedientes_lista"))


@expedientes_bp.get("/expedientes/<int:mascota_id>/reporte")
def expedientes_reporte(mascota_id: int):
    """Función para expedientes reporte."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _permitido(me, "hu028"):
        return render_template("acceso_denegado.html", me=me)

    mascota_row, response = _obtener_mascota_o_responder(me, mascota_id)
    if response:
        return response

    mascota = mascota_row[0]
    generated_at = datetime.now()
    edad_anos = None
    if mascota.fecha_nacimiento:
        edad_anos = max((generated_at.date() - mascota.fecha_nacimiento).days // 365, 0)
    veterinario_consulta = aliased(Usuario)
    insumo_medicamento = aliased(InsumoClinico)

    consultas_rows = (
        db.session.query(
            ConsultaMedica,
            veterinario_consulta.nombre.label("veterinario_nombre"),
            insumo_medicamento.nombre.label("medicamento_nombre"),
        )
        .join(veterinario_consulta, ConsultaMedica.veterinario_id == veterinario_consulta.id)
        .outerjoin(insumo_medicamento, ConsultaMedica.insumo_clinico_id == insumo_medicamento.id)
        .filter(ConsultaMedica.mascota_id == mascota.id)
        .order_by(ConsultaMedica.fecha_consulta.desc(), ConsultaMedica.id.desc())
        .all()
    )

    vacunas_rows = (
        db.session.query(VacunaAlergia)
        .filter(VacunaAlergia.mascota_id == mascota.id, VacunaAlergia.tipo_registro == "vacuna")
        .order_by(VacunaAlergia.fecha_registro.desc(), VacunaAlergia.id.desc())
        .all()
    )

    analisis_rows = (
        db.session.query(AnalisisClinico)
        .filter(AnalisisClinico.mascota_id == mascota.id)
        .order_by(AnalisisClinico.fecha_analisis.desc(), AnalisisClinico.id.desc())
        .all()
    )

    pdf_buffer = _construir_pdf_reporte_clinico(
        mascota=mascota,
        dueno_nombre=mascota_row.dueno_nombre,
        generated_at=generated_at,
        edad_anos=edad_anos,
        consultas_rows=consultas_rows,
        vacunas_rows=vacunas_rows,
        analisis_rows=analisis_rows,
    )
    filename = f"reporte_clinico_{mascota.nombre.lower().replace(' ', '_')}.pdf"
    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@expedientes_bp.get("/expedientes/<int:mascota_id>/analisis/<int:analisis_id>/adjunto")
def expedientes_descargar_adjunto_analisis(mascota_id: int, analisis_id: int):
    """Función para expedientes descargar adjunto analisis."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    mascota_row, denied_response = _obtener_mascota_o_responder(me, mascota_id)
    if denied_response:
        return denied_response
    mascota = mascota_row[0]

    analisis = (
        db.session.query(AnalisisClinico)
        .filter(AnalisisClinico.id == analisis_id, AnalisisClinico.mascota_id == mascota.id)
        .first()
    )
    if not analisis or not analisis.archivo_adjunto:
        flash("El archivo solicitado no existe.", "error")
        return redirect(url_for("expedientes.expedientes_detalle", mascota_id=mascota.id))

    abs_path = _resolver_archivo_analisis(analisis.archivo_adjunto)
    if not abs_path:
        flash("No fue posible localizar el archivo solicitado.", "error")
        return redirect(url_for("expedientes.expedientes_detalle", mascota_id=mascota.id))

    return send_file(
        abs_path,
        as_attachment=False,
        download_name=analisis.nombre_archivo or os.path.basename(abs_path),
        conditional=True,
    )


@expedientes_bp.route("/expedientes/<int:mascota_id>/consultas/nueva", methods=["GET", "POST"])
def consultas_nueva(mascota_id: int):
    """Función para consultas nueva."""
    return _guardar_consulta(mascota_id)


@expedientes_bp.route("/expedientes/<int:mascota_id>/consultas/<int:consulta_id>/editar", methods=["GET", "POST"])
def consultas_editar(mascota_id: int, consulta_id: int):
    """Función para consultas editar."""
    return _guardar_consulta(mascota_id, consulta_id=consulta_id)


def _guardar_consulta(mascota_id: int, consulta_id: int | None = None):
    """Función para guardar consulta."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    hu_code = "hu026" if consulta_id is not None else "hu025"
    if not _permitido(me, hu_code):
        return render_template("acceso_denegado.html", me=me)

    mascota_row, response = _obtener_mascota_o_responder(me, mascota_id)
    if response:
        return response

    mascota = mascota_row[0]
    consulta = None
    previous_insumo_id = None
    previous_vacuna_id = None
    if consulta_id is not None:
        consulta = db.session.get(ConsultaMedica, consulta_id)
        if not consulta or consulta.mascota_id != mascota.id:
            flash("La consulta médica solicitada no existe.", "error")
            return redirect(url_for("expedientes.expedientes_detalle", mascota_id=mascota.id))
        previous_insumo_id = consulta.insumo_clinico_id
        previous_vacuna_id = consulta.vacuna_insumo_id

    veterinarios = _obtener_veterinarios_activos()
    medicamentos = _obtener_insumos("medicamento", solo_activos=True)
    vacunas = _obtener_insumos("vacuna", solo_activos=True)

    if request.method == "GET":
        datos_formulario = _datos_formulario_consulta(consulta=consulta)
        datos_formulario = _hidratar_datos_consulta_con_seguimientos(datos_formulario, consulta.id if consulta else None)
        captcha_scope = _captcha_scope_consulta_edit(consulta.id) if consulta else _captcha_scope_consulta_create(mascota.id)
        return render_template(
            "expediente_consulta_form.html",
            me=me,
            active_nav="expedientes",
            mascota=mascota,
            mode="edit" if consulta else "create",
            consulta_id=consulta.id if consulta else None,
            datos_formulario=datos_formulario,
            errores_campo={},
            veterinarios=veterinarios,
            medicamentos=medicamentos,
            vacunas=vacunas,
            tipos_analisis=TIPO_ANALISIS_OPTIONS,
            dosis_unidades=DOSIS_UNIDADES_OPTIONS,
            can_schedule_followup=usuario_puede_programar_seguimiento(me),
            captcha=build_captcha(captcha_scope),
        )

    datos_formulario = _datos_formulario_consulta(request.form)
    errores_campo = {}
    captcha_scope = _captcha_scope_consulta_edit(consulta.id) if consulta else _captcha_scope_consulta_create(mascota.id)

    fecha_consulta = _parsear_fecha(datos_formulario["fecha_consulta"])
    _validar_fecha_no_futura(fecha_consulta, "fecha_consulta", errores_campo)

    veterinario_id = _parsear_entero(datos_formulario["veterinario_id"])
    _, veterinario_error = _validar_veterinario(veterinario_id)
    if veterinario_error:
        errores_campo["veterinario_id"] = veterinario_error

    if not datos_formulario["sintomas"]:
        errores_campo["sintomas"] = "Debes describir los síntomas para continuar."
    else:
        _validar_longitud_maxima(datos_formulario["sintomas"], "sintomas", MAX_CONSULTA_TEXTO_LENGTH, errores_campo, "El campo de síntomas")
    if not datos_formulario["diagnostico"]:
        errores_campo["diagnostico"] = "Debes capturar el diagnóstico para continuar."
    else:
        _validar_longitud_maxima(datos_formulario["diagnostico"], "diagnostico", MAX_CONSULTA_TEXTO_LENGTH, errores_campo, "El diagnóstico")
    if not datos_formulario["tratamiento"]:
        errores_campo["tratamiento"] = "Debes capturar el tratamiento para continuar."
    else:
        _validar_longitud_maxima(datos_formulario["tratamiento"], "tratamiento", MAX_CONSULTA_TEXTO_LENGTH, errores_campo, "El tratamiento")

    insumo_clinico_id = _parsear_entero(datos_formulario["insumo_clinico_id"]) if datos_formulario["incluye_medicamento"] else None
    insumo = None
    if datos_formulario["incluye_medicamento"] and insumo_clinico_id is not None:
        insumo = db.session.get(InsumoClinico, insumo_clinico_id)
        if not insumo or insumo.tipo_insumo != "medicamento" or not insumo.activo:
            errores_campo["insumo_clinico_id"] = "Debes seleccionar un medicamento válido."
    elif datos_formulario["incluye_medicamento"]:
        errores_campo["insumo_clinico_id"] = "Debes seleccionar un medicamento."

    fecha_administracion = _parsear_fecha(datos_formulario["fecha_administracion"])
    if datos_formulario["incluye_medicamento"] and insumo_clinico_id:
        _validar_fecha_no_futura(fecha_administracion, "fecha_administracion", errores_campo)
        dosis_numero = _parsear_entero(datos_formulario["dosis_numero"])
        if not datos_formulario["dosis_numero"]:
            errores_campo["dosis"] = "Debes indicar la dosis del medicamento."
        elif dosis_numero is None or dosis_numero < 1 or dosis_numero > MAX_DOSIS_CANTIDAD:
            errores_campo["dosis"] = f"Debes seleccionar una dosis entre 1 y {MAX_DOSIS_CANTIDAD}."
        elif datos_formulario["dosis_unidad"] not in DOSIS_UNIDADES_OPTIONS:
            errores_campo["dosis"] = "Debes seleccionar la unidad de la dosis."
        if not datos_formulario["periodo_administracion"]:
            errores_campo["periodo_administracion"] = "Debes indicar el período de administración."
        elif _contar_palabras(datos_formulario["periodo_administracion"]) > MAX_PERIODO_ADMINISTRACION_WORDS:
            errores_campo["periodo_administracion"] = (
                f"El período de administración no puede exceder {MAX_PERIODO_ADMINISTRACION_WORDS} palabras."
            )
        elif len(datos_formulario["periodo_administracion"]) > MAX_PERIODO_ADMINISTRACION_LENGTH:
            errores_campo["periodo_administracion"] = (
                f"El período de administración no puede exceder {MAX_PERIODO_ADMINISTRACION_LENGTH} caracteres."
            )
    elif any([
        datos_formulario["fecha_administracion"],
        datos_formulario["dosis_numero"],
        datos_formulario["dosis_unidad"],
        datos_formulario["periodo_administracion"],
    ]):
        errores_campo["insumo_clinico_id"] = "Debes seleccionar un medicamento para registrar su administración."

    _validar_longitud_maxima(
        datos_formulario["observaciones"],
        "observaciones",
        MAX_OBSERVACIONES_LENGTH,
        errores_campo,
        "El campo de observaciones",
    )

    captcha_answer = (request.form.get("captcha_answer") or "").strip()
    if not captcha_answer:
        errores_campo["captcha"] = "Debes resolver el captcha para continuar."
    elif not validate_captcha(captcha_scope, captcha_answer):
        errores_campo["captcha"] = "Respuesta errónea. Intenta nuevamente para completar la acción"

    vacuna_insumo_id = _parsear_entero(datos_formulario["vacuna_insumo_id"]) if datos_formulario["incluye_vacuna"] else None
    if datos_formulario["incluye_vacuna"]:
        vacuna = db.session.get(InsumoClinico, vacuna_insumo_id) if vacuna_insumo_id else None
        if not vacuna or vacuna.tipo_insumo != "vacuna" or not vacuna.activo:
            errores_campo["vacuna_insumo_id"] = "Debes seleccionar una vacuna válida."

    tipo_analisis_relacionado = datos_formulario["tipo_analisis_relacionado"] if datos_formulario["incluye_analisis"] else ""
    if datos_formulario["incluye_analisis"] and tipo_analisis_relacionado not in TIPO_ANALISIS_OPTIONS:
        errores_campo["tipo_analisis_relacionado"] = "Debes seleccionar un análisis válido."

    seguimiento_medicamento = {"requiere": False, "programado_para": None}
    seguimiento_vacuna = {"requiere": False, "programado_para": None}
    seguimiento_analisis = {"requiere": False, "programado_para": None}
    if usuario_puede_programar_seguimiento(me):
        seguimiento_medicamento = validar_programacion_seguimiento(
            requiere=bool(datos_formulario["incluye_medicamento"] and datos_formulario["medicamento_requiere_seguimiento"]),
            programado_para_raw=datos_formulario["medicamento_seguimiento_programado_para"],
            veterinario=db.session.get(Usuario, veterinario_id) if veterinario_id else None,
            errores_campo=errores_campo,
            error_field="medicamento_seguimiento_programado_para",
        )
        seguimiento_vacuna = validar_programacion_seguimiento(
            requiere=bool(datos_formulario["incluye_vacuna"] and datos_formulario["vacuna_requiere_seguimiento"]),
            programado_para_raw=datos_formulario["vacuna_seguimiento_programado_para"],
            veterinario=db.session.get(Usuario, veterinario_id) if veterinario_id else None,
            errores_campo=errores_campo,
            error_field="vacuna_seguimiento_programado_para",
        )
        seguimiento_analisis = validar_programacion_seguimiento(
            requiere=bool(datos_formulario["incluye_analisis"] and datos_formulario["analisis_requiere_seguimiento"]),
            programado_para_raw=datos_formulario["analisis_seguimiento_programado_para"],
            veterinario=db.session.get(Usuario, veterinario_id) if veterinario_id else None,
            errores_campo=errores_campo,
            error_field="analisis_seguimiento_programado_para",
        )

    if errores_campo:
        return render_template(
            "expediente_consulta_form.html",
            me=me,
            active_nav="expedientes",
            mascota=mascota,
            mode="edit" if consulta else "create",
            consulta_id=consulta.id if consulta else None,
            datos_formulario=datos_formulario,
            errores_campo=errores_campo,
            veterinarios=veterinarios,
            medicamentos=medicamentos,
            vacunas=vacunas,
            tipos_analisis=TIPO_ANALISIS_OPTIONS,
            dosis_unidades=DOSIS_UNIDADES_OPTIONS,
            can_schedule_followup=usuario_puede_programar_seguimiento(me),
            captcha=build_captcha(captcha_scope),
        )

    _ajustar_existencia_por_cambio(previous_insumo_id, insumo_clinico_id, "insumo_clinico_id", errores_campo)
    _ajustar_existencia_por_cambio(previous_vacuna_id, vacuna_insumo_id, "vacuna_insumo_id", errores_campo)
    if errores_campo:
        db.session.rollback()
        return render_template(
            "expediente_consulta_form.html",
            me=me,
            active_nav="expedientes",
            mascota=mascota,
            mode="edit" if consulta else "create",
            consulta_id=consulta.id if consulta else None,
            datos_formulario=datos_formulario,
            errores_campo=errores_campo,
            veterinarios=veterinarios,
            medicamentos=medicamentos,
            vacunas=vacunas,
            tipos_analisis=TIPO_ANALISIS_OPTIONS,
            dosis_unidades=DOSIS_UNIDADES_OPTIONS,
            can_schedule_followup=usuario_puede_programar_seguimiento(me),
            captcha=build_captcha(captcha_scope),
        )

    if consulta is None:
        consulta = ConsultaMedica(mascota_id=mascota.id)
        db.session.add(consulta)

    consulta.veterinario_id = veterinario_id
    consulta.fecha_consulta = fecha_consulta
    consulta.sintomas = datos_formulario["sintomas"]
    consulta.diagnostico = datos_formulario["diagnostico"]
    consulta.tratamiento = datos_formulario["tratamiento"]
    consulta.medicamentos_administrados = None
    consulta.insumo_clinico_id = insumo_clinico_id
    consulta.vacuna_insumo_id = vacuna_insumo_id
    consulta.tipo_analisis_relacionado = tipo_analisis_relacionado or None
    consulta.fecha_administracion = fecha_administracion if insumo_clinico_id else None
    consulta.dosis = datos_formulario["dosis"] or None
    consulta.periodo_administracion = datos_formulario["periodo_administracion"] or None
    consulta.observaciones = datos_formulario["observaciones"] or None
    consulta.precio_consulta = CONSULTA_BASE_PRICE

    db.session.flush()
    if seguimiento_medicamento["requiere"]:
        guardar_seguimiento(
            origen_tipo="consulta",
            origen_id=consulta.id,
            evento_tipo="medicamento",
            mascota_id=mascota.id,
            veterinario_id=veterinario_id,
            programado_para=seguimiento_medicamento["programado_para"],
            descripcion=f"Seguimiento de medicamento para {mascota.nombre}",
        )
    else:
        eliminar_seguimiento(origen_tipo="consulta", origen_id=consulta.id, evento_tipo="medicamento")

    if seguimiento_vacuna["requiere"]:
        guardar_seguimiento(
            origen_tipo="consulta",
            origen_id=consulta.id,
            evento_tipo="vacuna",
            mascota_id=mascota.id,
            veterinario_id=veterinario_id,
            programado_para=seguimiento_vacuna["programado_para"],
            descripcion=f"Seguimiento de vacuna para {mascota.nombre}",
        )
    else:
        eliminar_seguimiento(origen_tipo="consulta", origen_id=consulta.id, evento_tipo="vacuna")

    if seguimiento_analisis["requiere"]:
        guardar_seguimiento(
            origen_tipo="consulta",
            origen_id=consulta.id,
            evento_tipo="analisis",
            mascota_id=mascota.id,
            veterinario_id=veterinario_id,
            programado_para=seguimiento_analisis["programado_para"],
            descripcion=f"Seguimiento de análisis para {mascota.nombre}",
        )
    else:
        eliminar_seguimiento(origen_tipo="consulta", origen_id=consulta.id, evento_tipo="analisis")

    db.session.commit()
    flash("Consulta médica actualizada correctamente." if consulta_id else "Consulta médica registrada correctamente.", "success")
    return redirect(url_for("expedientes.expedientes_detalle", mascota_id=mascota.id))


@expedientes_bp.route("/expedientes/<int:mascota_id>/vacunas-alergias/nuevo", methods=["GET", "POST"])
def vacunas_nueva(mascota_id: int):
    """Función para vacunas nueva."""
    return _guardar_vacuna(mascota_id)


@expedientes_bp.route("/expedientes/<int:mascota_id>/vacunas-alergias/<int:registro_id>/editar", methods=["GET", "POST"])
def vacunas_editar(mascota_id: int, registro_id: int):
    """Función para vacunas editar."""
    return _guardar_vacuna(mascota_id, registro_id=registro_id)


def _guardar_vacuna(mascota_id: int, registro_id: int | None = None):
    """Función para guardar vacuna."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _permitido(me, "hu029"):
        return render_template("acceso_denegado.html", me=me)

    mascota_row, response = _obtener_mascota_o_responder(me, mascota_id)
    if response:
        return response

    mascota = mascota_row[0]
    registro = None
    previous_insumo_id = None
    if registro_id is not None:
        registro = db.session.get(VacunaAlergia, registro_id)
        if not registro or registro.mascota_id != mascota.id:
            flash("El registro solicitado no existe.", "error")
            return redirect(url_for("expedientes.expedientes_detalle", mascota_id=mascota.id))
        previous_insumo_id = registro.insumo_clinico_id

    veterinarios = _obtener_veterinarios_activos()
    vacunas_catalogo = _obtener_insumos("vacuna", solo_activos=True)
    captcha_scope = _captcha_scope_vacuna_edit(registro.id) if registro else _captcha_scope_vacuna_create(mascota.id)

    if request.method == "GET":
        datos_formulario = _datos_formulario_vacuna(registro=registro)
        datos_formulario = _hidratar_datos_vacuna_con_seguimiento(datos_formulario, registro.id if registro else None)
        return render_template(
            "expediente_vacuna_form.html",
            me=me,
            active_nav="expedientes",
            mascota=mascota,
            mode="edit" if registro else "create",
            registro_id=registro.id if registro else None,
            datos_formulario=datos_formulario,
            errores_campo={},
            veterinarios=veterinarios,
            vacunas_catalogo=vacunas_catalogo,
            can_schedule_followup=usuario_puede_programar_seguimiento(me),
            captcha=build_captcha(captcha_scope),
        )

    datos_formulario = _datos_formulario_vacuna(request.form)
    errores_campo = {}

    if datos_formulario["tipo_registro"] not in {"vacuna", "alergia"}:
        errores_campo["tipo_registro"] = "Debes seleccionar un tipo de registro válido."

    fecha_registro = _parsear_fecha(datos_formulario["fecha_registro"])
    if not fecha_registro:
        errores_campo["fecha_registro"] = "Debes seleccionar una fecha. Si el registro es del mismo día, selecciona nuevamente la fecha de hoy."
    elif fecha_registro > date.today():
        errores_campo["fecha_registro"] = "La fecha no puede ser posterior a hoy."

    veterinario_id = _parsear_entero(datos_formulario["veterinario_id"])
    _, veterinario_error = _validar_veterinario(veterinario_id)
    if veterinario_error:
        errores_campo["veterinario_id"] = veterinario_error

    insumo_clinico_id = _parsear_entero(datos_formulario["insumo_clinico_id"])
    nombre = None
    if datos_formulario["tipo_registro"] == "vacuna":
        insumo = db.session.get(InsumoClinico, insumo_clinico_id) if insumo_clinico_id else None
        if not insumo or insumo.tipo_insumo != "vacuna" or not insumo.activo:
            errores_campo["insumo_clinico_id"] = "Debes seleccionar una vacuna válida del inventario."
        else:
            nombre = insumo.nombre
    else:
        if not datos_formulario["nombre"]:
            errores_campo["nombre"] = "Debes capturar el nombre de la alergia para continuar."
        else:
            _validar_longitud_maxima(datos_formulario["nombre"], "nombre", MAX_ALERGIA_NOMBRE_LENGTH, errores_campo, "El nombre de la alergia")
        nombre = datos_formulario["nombre"]

    if datos_formulario["tipo_registro"] == "alergia":
        if not datos_formulario["reaccion_identificada"]:
            errores_campo["reaccion_identificada"] = "Debes describir la reacción alérgica."
        else:
            _validar_longitud_maxima(
                datos_formulario["reaccion_identificada"],
                "reaccion_identificada",
                MAX_REACCION_LENGTH,
                errores_campo,
                "La reacción identificada",
            )
    elif datos_formulario["tipo_registro"] == "vacuna" and not datos_formulario["tiene_reaccion"]:
        datos_formulario["reaccion_identificada"] = ""
    elif datos_formulario["reaccion_identificada"]:
        _validar_longitud_maxima(
            datos_formulario["reaccion_identificada"],
            "reaccion_identificada",
            MAX_REACCION_LENGTH,
            errores_campo,
            "La reacción identificada",
        )

    _validar_longitud_maxima(
        datos_formulario["notas_adicionales"],
        "notas_adicionales",
        MAX_NOTAS_ADICIONALES_LENGTH,
        errores_campo,
        "El campo de notas adicionales",
    )

    captcha_answer = (request.form.get("captcha_answer") or "").strip()
    if not captcha_answer:
        errores_campo["captcha"] = "Debes resolver el captcha para continuar."
    elif not validate_captcha(captcha_scope, captcha_answer):
        errores_campo["captcha"] = "Respuesta errónea. Intenta nuevamente para completar la acción"

    seguimiento_vacuna = {"requiere": False, "programado_para": None}
    if usuario_puede_programar_seguimiento(me):
        seguimiento_vacuna = validar_programacion_seguimiento(
            requiere=bool(datos_formulario["tipo_registro"] == "vacuna" and datos_formulario["vacuna_requiere_seguimiento"]),
            programado_para_raw=datos_formulario["vacuna_seguimiento_programado_para"],
            veterinario=db.session.get(Usuario, veterinario_id) if veterinario_id else None,
            errores_campo=errores_campo,
            error_field="vacuna_seguimiento_programado_para",
        )

    if errores_campo:
        return render_template(
            "expediente_vacuna_form.html",
            me=me,
            active_nav="expedientes",
            mascota=mascota,
            mode="edit" if registro else "create",
            registro_id=registro.id if registro else None,
            datos_formulario=datos_formulario,
            errores_campo=errores_campo,
            veterinarios=veterinarios,
            vacunas_catalogo=vacunas_catalogo,
            can_schedule_followup=usuario_puede_programar_seguimiento(me),
            captcha=build_captcha(captcha_scope),
        )

    new_insumo_id = insumo_clinico_id if datos_formulario["tipo_registro"] == "vacuna" else None
    _ajustar_existencia_por_cambio(previous_insumo_id, new_insumo_id, "insumo_clinico_id", errores_campo)
    if errores_campo:
        db.session.rollback()
        return render_template(
            "expediente_vacuna_form.html",
            me=me,
            active_nav="expedientes",
            mascota=mascota,
            mode="edit" if registro else "create",
            registro_id=registro.id if registro else None,
            datos_formulario=datos_formulario,
            errores_campo=errores_campo,
            veterinarios=veterinarios,
            vacunas_catalogo=vacunas_catalogo,
            can_schedule_followup=usuario_puede_programar_seguimiento(me),
            captcha=build_captcha(captcha_scope),
        )

    if registro is None:
        registro = VacunaAlergia(mascota_id=mascota.id)
        db.session.add(registro)

    registro.tipo_registro = datos_formulario["tipo_registro"]
    registro.fecha_registro = fecha_registro
    registro.veterinario_id = veterinario_id
    registro.insumo_clinico_id = insumo_clinico_id if datos_formulario["tipo_registro"] == "vacuna" else None
    registro.nombre = nombre
    registro.reaccion_identificada = datos_formulario["reaccion_identificada"] or None
    registro.notas_adicionales = datos_formulario["notas_adicionales"] or None

    db.session.flush()
    if seguimiento_vacuna["requiere"]:
        guardar_seguimiento(
            origen_tipo="vacuna_alergia",
            origen_id=registro.id,
            evento_tipo="vacuna",
            mascota_id=mascota.id,
            veterinario_id=veterinario_id,
            programado_para=seguimiento_vacuna["programado_para"],
            descripcion=f"Seguimiento de vacuna para {mascota.nombre}",
        )
    else:
        eliminar_seguimiento(origen_tipo="vacuna_alergia", origen_id=registro.id, evento_tipo="vacuna")

    db.session.commit()
    flash("Registro clínico actualizado correctamente." if registro_id else "Registro clínico guardado correctamente.", "success")
    return redirect(url_for("expedientes.expedientes_detalle", mascota_id=mascota.id))


@expedientes_bp.route("/expedientes/<int:mascota_id>/analisis/nuevo", methods=["GET", "POST"])
def analisis_nuevo(mascota_id: int):
    """Función para analisis nuevo."""
    return _guardar_analisis(mascota_id)


@expedientes_bp.route("/expedientes/<int:mascota_id>/analisis/<int:analisis_id>/editar", methods=["GET", "POST"])
def analisis_editar(mascota_id: int, analisis_id: int):
    """Función para analisis editar."""
    return _guardar_analisis(mascota_id, analisis_id=analisis_id)


def _guardar_analisis(mascota_id: int, analisis_id: int | None = None):
    """Función para guardar analisis."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _permitido(me, "hu031"):
        return render_template("acceso_denegado.html", me=me)

    mascota_row, response = _obtener_mascota_o_responder(me, mascota_id)
    if response:
        return response

    mascota = mascota_row[0]
    analisis = None
    if analisis_id is not None:
        analisis = db.session.get(AnalisisClinico, analisis_id)
        if not analisis or analisis.mascota_id != mascota.id:
            flash("El análisis solicitado no existe.", "error")
            return redirect(url_for("expedientes.expedientes_detalle", mascota_id=mascota.id))

    veterinarios = _obtener_veterinarios_activos()
    captcha_scope = _captcha_scope_analisis_edit(analisis.id) if analisis else _captcha_scope_analisis_create(mascota.id)

    if request.method == "GET":
        datos_formulario = _datos_formulario_analisis(analisis=analisis)
        datos_formulario = _hidratar_datos_analisis_con_seguimiento(datos_formulario, analisis.id if analisis else None)
        return render_template(
            "expediente_analisis_form.html",
            me=me,
            active_nav="expedientes",
            mascota=mascota,
            mode="edit" if analisis else "create",
            analisis_id=analisis.id if analisis else None,
            datos_formulario=datos_formulario,
            errores_campo={},
            veterinarios=veterinarios,
            tipos_analisis=TIPO_ANALISIS_OPTIONS,
            can_schedule_followup=usuario_puede_programar_seguimiento(me),
            captcha=build_captcha(captcha_scope),
        )

    datos_formulario = _datos_formulario_analisis(request.form)
    errores_campo = {}

    fecha_analisis = _parsear_fecha(datos_formulario["fecha_analisis"])
    if not fecha_analisis:
        errores_campo["fecha_analisis"] = "Debes seleccionar una fecha. Si el registro es del mismo día, selecciona nuevamente la fecha de hoy."
    elif fecha_analisis > date.today():
        errores_campo["fecha_analisis"] = "La fecha no puede ser posterior a hoy."

    veterinario_id = _parsear_entero(datos_formulario["veterinario_id"])
    _, veterinario_error = _validar_veterinario(veterinario_id)
    if veterinario_error:
        errores_campo["veterinario_id"] = veterinario_error

    if datos_formulario["tipo_analisis"] not in TIPO_ANALISIS_OPTIONS:
        errores_campo["tipo_analisis"] = "Debes seleccionar un tipo de análisis válido."
    if not datos_formulario["resultados"]:
        errores_campo["resultados"] = "Debes registrar los resultados para continuar."
    else:
        _validar_longitud_maxima(datos_formulario["resultados"], "resultados", MAX_RESULTADOS_LENGTH, errores_campo, "El campo de resultados")
    _validar_longitud_maxima(
        datos_formulario["documentos_adjuntos"],
        "documentos_adjuntos",
        MAX_NOTAS_ADJUNTO_LENGTH,
        errores_campo,
        "El campo de notas del adjunto",
    )
    precio = analisis.precio if analisis else Decimal("0.00")
    if _nombre_rol(me) == ROLE_ADMIN:
        precio = _parsear_decimal(datos_formulario["precio"])
        if precio is None:
            errores_campo["precio"] = "Debes capturar un precio válido."
        elif precio < 0:
            errores_campo["precio"] = "El precio no puede ser menor a 0."
        elif precio > MAX_PRECIO:
            errores_campo["precio"] = f"El precio no puede exceder ${MAX_PRECIO}."

    uploaded = request.files.get("archivo_adjunto")
    archivo_error = _validar_archivo_analisis(uploaded)
    if archivo_error:
        errores_campo["archivo_adjunto"] = archivo_error

    captcha_answer = (request.form.get("captcha_answer") or "").strip()
    if not captcha_answer:
        errores_campo["captcha"] = "Debes resolver el captcha para continuar."
    elif not validate_captcha(captcha_scope, captcha_answer):
        errores_campo["captcha"] = "Respuesta errónea. Intenta nuevamente para completar la acción"

    seguimiento_analisis = {"requiere": False, "programado_para": None}
    if usuario_puede_programar_seguimiento(me):
        seguimiento_analisis = validar_programacion_seguimiento(
            requiere=bool(datos_formulario["analisis_requiere_seguimiento"]),
            programado_para_raw=datos_formulario["analisis_seguimiento_programado_para"],
            veterinario=db.session.get(Usuario, veterinario_id) if veterinario_id else None,
            errores_campo=errores_campo,
            error_field="analisis_seguimiento_programado_para",
        )

    if errores_campo:
        datos_formulario["nombre_archivo"] = analisis.nombre_archivo if analisis and analisis.nombre_archivo else ""
        return render_template(
            "expediente_analisis_form.html",
            me=me,
            active_nav="expedientes",
            mascota=mascota,
            mode="edit" if analisis else "create",
            analisis_id=analisis.id if analisis else None,
            datos_formulario=datos_formulario,
            errores_campo=errores_campo,
            veterinarios=veterinarios,
            tipos_analisis=TIPO_ANALISIS_OPTIONS,
            can_schedule_followup=usuario_puede_programar_seguimiento(me),
            captcha=build_captcha(captcha_scope),
        )

    if analisis is None:
        analisis = AnalisisClinico(mascota_id=mascota.id)
        db.session.add(analisis)

    analisis.fecha_analisis = fecha_analisis
    analisis.veterinario_id = veterinario_id
    analisis.tipo_analisis = datos_formulario["tipo_analisis"]
    analisis.resultados = datos_formulario["resultados"]
    analisis.precio = precio
    analisis.documentos_adjuntos = datos_formulario["documentos_adjuntos"] or None

    if uploaded and uploaded.filename:
        rel_path, filename = _guardar_archivo_analisis(uploaded, mascota.id)
        analisis.archivo_adjunto = rel_path
        analisis.nombre_archivo = filename

    db.session.flush()
    if seguimiento_analisis["requiere"]:
        guardar_seguimiento(
            origen_tipo="analisis_clinico",
            origen_id=analisis.id,
            evento_tipo="analisis",
            mascota_id=mascota.id,
            veterinario_id=veterinario_id,
            programado_para=seguimiento_analisis["programado_para"],
            descripcion=f"Seguimiento de análisis clínico para {mascota.nombre}",
        )
    else:
        eliminar_seguimiento(origen_tipo="analisis_clinico", origen_id=analisis.id, evento_tipo="analisis")

    db.session.commit()
    flash("Análisis clínico actualizado correctamente." if analisis_id else "Análisis clínico registrado correctamente.", "success")
    return redirect(url_for("expedientes.expedientes_detalle", mascota_id=mascota.id))
