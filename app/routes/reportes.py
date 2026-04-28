"""Rutas para reportes administrativos, métricas y exportaciones."""

from __future__ import annotations

import csv
import os
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO, StringIO

from flask import Blueprint, current_app, redirect, render_template, request, send_file, session, url_for
from openpyxl import Workbook
from PIL import Image as PilImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func
from sqlalchemy.orm import aliased

from app.extensions import db
from app.models import AnalisisClinico, Cita, ConsultaMedica, InsumoClinico, Mascota, Rol, Usuario, VacunaAlergia
from utils.auth_ui import get_current_user_from_api

reportes_bp = Blueprint("reportes", __name__)

LOGIN_GET_ENDPOINT = "pages.pagina_inicio_sesion"

ROLE_ADMIN = "administrador"
ROLE_CLIENTE = "cliente"
ROLE_VETERINARIO = "veterinario"
EXPORT_FORMATS = {"pdf", "csv", "xlsx"}
CLIENT_SOURCE_LABELS = {
    "recomendacion": "Recomendación",
    "redes_sociales": "Redes sociales",
    "sin_dato": "Sin dato",
}
MONTH_LABELS = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}


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


def _titulo_fuente(source: str | None):
    """Función para titulo fuente."""
    key = (source or "").strip().lower() or "sin_dato"
    return CLIENT_SOURCE_LABELS.get(key, "Sin dato")


def _format_currency(value) -> str:
    """Función para format currency."""
    amount = Decimal(value or 0)
    return f"${amount:.2f}"


def _validar_periodo(fecha_inicio_raw: str, fecha_fin_raw: str):
    """Función para validar periodo."""
    errores_campo = {}
    fecha_inicio = _parsear_fecha(fecha_inicio_raw)
    fecha_fin = _parsear_fecha(fecha_fin_raw)

    if not fecha_inicio_raw:
        errores_campo["fecha_inicio"] = "Debes seleccionar la fecha inicial."
    elif not fecha_inicio:
        errores_campo["fecha_inicio"] = "Debes seleccionar una fecha inicial válida."
    elif fecha_inicio > date.today():
        errores_campo["fecha_inicio"] = "La fecha inicial no puede ser posterior a hoy."

    if not fecha_fin_raw:
        errores_campo["fecha_fin"] = "Debes seleccionar la fecha final."
    elif not fecha_fin:
        errores_campo["fecha_fin"] = "Debes seleccionar una fecha final válida."
    elif fecha_fin > date.today():
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


def _month_bounds(year: int, month: int):
    """Función para month bounds."""
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def _nombre_mes(month: int) -> str:
    """Función para nombre mes."""
    return MONTH_LABELS.get(month, str(month))


def _build_pdf_logo_asset():
    """Función para build pdf logo asset."""
    # Función de logotipo para reportes PDF.
    logo_path = os.path.join(current_app.root_path, "static", "images", "logo-cive.png")
    if not os.path.exists(logo_path):
        return None, None

    try:
        image = PilImage.open(logo_path).convert("RGBA")
        image.putalpha(int(255 * 0.6))

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer, image.size
    except Exception:
        return None, None


def _build_pdf_header(title: str, subtitle: str, title_style, subtitle_style):
    """Función para build pdf header."""
    # Función de encabezado con logotipo para reportes PDF.
    left_table = Table(
        [[Paragraph(title, title_style)], [Paragraph(subtitle, subtitle_style)]],
        colWidths=[110 * mm],
    )
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


def _export_response(*, title: str, subtitle: str, headers: list[str], rows: list[list], export_format: str, filename_base: str):
    """Función para export response."""
    if export_format == "csv":
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(headers)
        writer.writerows(rows)
        return send_file(
            BytesIO(buffer.getvalue().encode("utf-8-sig")),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"{filename_base}.csv",
        )

    if export_format == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Reporte"
        sheet.append(headers)
        for row in rows:
            sheet.append(list(row))
        for column in sheet.columns:
            max_len = max(len(str(cell.value or "")) for cell in column)
            sheet.column_dimensions[column[0].column_letter].width = min(max_len + 2, 40)
        buffer = BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"{filename_base}.xlsx",
        )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReporteTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=20,
        textColor=colors.HexColor("#21272a"),
        alignment=TA_LEFT,
    )
    subtitle_style = ParagraphStyle(
        "ReporteSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        textColor=colors.HexColor("#697077"),
    )
    cell_style = ParagraphStyle(
        "ReporteCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
    )
    header_style = ParagraphStyle(
        "ReporteHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.white,
    )

    def _paragraph(value, style):
        """Función para paragraph."""
        text = str(value or "-").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        return Paragraph(text, style)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )
    story = [
        _build_pdf_header(title, subtitle, title_style, subtitle_style),
        Spacer(1, 8),
    ]

    table_data = [[_paragraph(header, header_style) for header in headers]]
    table_data.extend([[_paragraph(value, cell_style) for value in row] for row in rows] or [[_paragraph("Sin registros disponibles.", cell_style)] + [""] * (len(headers) - 1)])

    total_width = doc.width
    widths = [total_width / max(len(headers), 1)] * len(headers)
    table = Table(table_data, colWidths=widths, repeatRows=1)
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f62fe")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dde1e6")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if not rows:
        style_commands.extend([
            ("SPAN", (0, 1), (-1, 1)),
            ("ALIGN", (0, 1), (-1, 1), "LEFT"),
        ])
    table.setStyle(TableStyle(style_commands))
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{filename_base}.pdf",
    )


def _render_export_urls(endpoint: str, filters: dict):
    """Genera los enlaces de exportación PDF, CSV y Excel para un reporte."""
    return {
        "pdf": url_for(endpoint, **filters, export_format="pdf"),
        "csv": url_for(endpoint, **filters, export_format="csv"),
        "xlsx": url_for(endpoint, **filters, export_format="xlsx"),
    }


def _require_roles(me, allowed_roles: set[str]):
    """Valida si el usuario autenticado pertenece a los roles autorizados."""
    return _nombre_rol(me) in allowed_roles


def _obtener_veterinarios():
    """Obtiene veterinarios activos para filtros y reportes operativos."""
    return (
        db.session.query(Usuario)
        .join(Rol, Usuario.rol_id == Rol.id)
        .filter(func.lower(Rol.nombre) == ROLE_VETERINARIO)
        .filter(Usuario.eliminado.is_(False), Usuario.activo.is_(True))
        .order_by(Usuario.nombre.asc())
        .all()
    )


def _build_report_tabs(me):
    """Construye las pestañas de reportes visibles según el rol autenticado."""
    role = _nombre_rol(me)
    tabs = [
        {"id": "citas", "label": "Citas", "endpoint": "reportes.reportes_citas_administrativo", "visible": role == ROLE_ADMIN},
        {"id": "ingresos", "label": "Ingresos", "endpoint": "reportes.reportes_ingresos", "visible": role == ROLE_ADMIN},
        {"id": "productividad", "label": "Productividad", "endpoint": "reportes.reportes_productividad", "visible": role in {ROLE_ADMIN, ROLE_VETERINARIO}},
        {"id": "clientes_nuevos", "label": "Clientes nuevos", "endpoint": "reportes.reportes_clientes_nuevos", "visible": role == ROLE_ADMIN},
        {"id": "medicamentos", "label": "Medicamentos", "endpoint": "reportes.reportes_medicamentos", "visible": role == ROLE_ADMIN},
        {"id": "clientes_frecuentes", "label": "Clientes frecuentes", "endpoint": "reportes.reportes_clientes_frecuentes", "visible": role == ROLE_ADMIN},
    ]
    return [tab for tab in tabs if tab["visible"]]


@reportes_bp.get("/reportes")
def reportes_home():
    """Redirige al primer reporte disponible para el rol actual."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if _nombre_rol(me) == ROLE_CLIENTE:
        return render_template("acceso_denegado.html", me=me)
    tabs = _build_report_tabs(me)
    if not tabs:
        return render_template("acceso_denegado.html", me=me)
    return redirect(url_for(tabs[0]["endpoint"]))


@reportes_bp.get("/reportes/citas")
def reportes_citas_administrativo():
    """Genera el reporte administrativo de citas por estado y por veterinario."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r
    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()
    if not _require_roles(me, {ROLE_ADMIN}):
        return render_template("acceso_denegado.html", me=me)

    filters = {
        "fecha_inicio": (request.args.get("fecha_inicio") or "").strip(),
        "fecha_fin": (request.args.get("fecha_fin") or "").strip(),
    }
    export_format = (request.args.get("export_format") or "").strip().lower()
    errores_campo = {}
    summary = {"completadas": 0, "canceladas": 0, "pendientes": 0, "total": 0}
    rows = []
    export_urls = {}

    if filters["fecha_inicio"] or filters["fecha_fin"] or export_format:
        errores_campo, fecha_inicio, fecha_fin = _validar_periodo(filters["fecha_inicio"], filters["fecha_fin"])
        if not errores_campo:
            start_dt, end_dt = _inicio_fin_datetime(fecha_inicio, fecha_fin)
            vet_alias = aliased(Usuario)
            citas = (
                db.session.query(Cita, vet_alias.nombre.label("veterinario_nombre"))
                .join(vet_alias, Cita.veterinario_id == vet_alias.id)
                .filter(Cita.fecha_hora >= start_dt, Cita.fecha_hora <= end_dt)
                .order_by(vet_alias.nombre.asc(), Cita.fecha_hora.asc())
                .all()
            )

            if not citas:
                errores_campo["fecha_fin"] = "No existen citas para el periodo seleccionado."
            else:
                now = datetime.now()
                by_vet = defaultdict(lambda: {"completadas": 0, "canceladas": 0, "pendientes": 0, "total": 0})
                for cita, vet_name in citas:
                    bucket = by_vet[vet_name]
                    bucket["total"] += 1
                    summary["total"] += 1
                    if cita.cancelada or cita.estado == "cancelada":
                        bucket["canceladas"] += 1
                        summary["canceladas"] += 1
                    elif cita.estado == "confirmada" and cita.fecha_hora < now:
                        bucket["completadas"] += 1
                        summary["completadas"] += 1
                    else:
                        bucket["pendientes"] += 1
                        summary["pendientes"] += 1
                rows = [
                    {
                        "veterinario": vet_name,
                        "completadas": data["completadas"],
                        "canceladas": data["canceladas"],
                        "pendientes": data["pendientes"],
                        "total": data["total"],
                    }
                    for vet_name, data in by_vet.items()
                ]
                export_urls = _render_export_urls("reportes.reportes_citas_administrativo", filters)

    if export_format in EXPORT_FORMATS and rows and not errores_campo:
        headers = ["Veterinario", "Citas completadas", "Canceladas", "Pendientes", "Total"]
        export_rows = [[row["veterinario"], row["completadas"], row["canceladas"], row["pendientes"], row["total"]] for row in rows]
        subtitle = f"Periodo: {filters['fecha_inicio']} a {filters['fecha_fin']}"
        return _export_response(
            title="Reporte administrativo de citas",
            subtitle=subtitle,
            headers=headers,
            rows=export_rows,
            export_format=export_format,
            filename_base="reporte_administrativo_citas",
        )

    return render_template(
        "reporte_citas.html",
        me=me,
        active_nav="reportes",
        tabs=_build_report_tabs(me),
        active_report="citas",
        filtros=filters,
        errores_campo=errores_campo,
        summary=summary,
        rows=rows,
        export_urls=export_urls,
    )


@reportes_bp.get("/reportes/ingresos")
def reportes_ingresos():
    """Función para reportes ingresos."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r
    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()
    if not _require_roles(me, {ROLE_ADMIN}):
        return render_template("acceso_denegado.html", me=me)

    filters = {
        "fecha_inicio": (request.args.get("fecha_inicio") or "").strip(),
        "fecha_fin": (request.args.get("fecha_fin") or "").strip(),
    }
    export_format = (request.args.get("export_format") or "").strip().lower()
    errores_campo = {}
    rows = []
    summary = {"consultas": Decimal("0.00"), "medicamentos": Decimal("0.00"), "vacunas": Decimal("0.00"), "analisis": Decimal("0.00"), "total": Decimal("0.00")}
    export_urls = {}

    if filters["fecha_inicio"] or filters["fecha_fin"] or export_format:
        errores_campo, fecha_inicio, fecha_fin = _validar_periodo(filters["fecha_inicio"], filters["fecha_fin"])
        if not errores_campo:
            consultas = (
                db.session.query(ConsultaMedica)
                .filter(ConsultaMedica.fecha_consulta >= fecha_inicio, ConsultaMedica.fecha_consulta <= fecha_fin)
                .all()
            )
            medicamentos = (
                db.session.query(ConsultaMedica, InsumoClinico)
                .join(InsumoClinico, ConsultaMedica.insumo_clinico_id == InsumoClinico.id)
                .filter(ConsultaMedica.fecha_consulta >= fecha_inicio, ConsultaMedica.fecha_consulta <= fecha_fin)
                .all()
            )
            vacunas = (
                db.session.query(VacunaAlergia, InsumoClinico)
                .join(InsumoClinico, VacunaAlergia.insumo_clinico_id == InsumoClinico.id)
                .filter(VacunaAlergia.tipo_registro == "vacuna")
                .filter(VacunaAlergia.fecha_registro >= fecha_inicio, VacunaAlergia.fecha_registro <= fecha_fin)
                .all()
            )
            analisis = (
                db.session.query(AnalisisClinico)
                .filter(AnalisisClinico.fecha_analisis >= fecha_inicio, AnalisisClinico.fecha_analisis <= fecha_fin)
                .all()
            )

            if not any([consultas, medicamentos, vacunas, analisis]):
                errores_campo["fecha_fin"] = "No existen ingresos para el periodo seleccionado."
            else:
                conceptos = defaultdict(lambda: {"cantidad": 0, "total": Decimal("0.00"), "precios": set()})

                for consulta in consultas:
                    precio = Decimal(consulta.precio_consulta or 0)
                    conceptos[("Consulta", "Consulta general")]["cantidad"] += 1
                    conceptos[("Consulta", "Consulta general")]["total"] += precio
                    conceptos[("Consulta", "Consulta general")]["precios"].add(precio)
                    summary["consultas"] += precio

                for _, insumo in medicamentos:
                    precio = Decimal(insumo.precio or 0)
                    conceptos[("Medicamento", insumo.nombre)]["cantidad"] += 1
                    conceptos[("Medicamento", insumo.nombre)]["total"] += precio
                    conceptos[("Medicamento", insumo.nombre)]["precios"].add(precio)
                    summary["medicamentos"] += precio

                for _, insumo in vacunas:
                    precio = Decimal(insumo.precio or 0)
                    conceptos[("Vacuna", insumo.nombre)]["cantidad"] += 1
                    conceptos[("Vacuna", insumo.nombre)]["total"] += precio
                    conceptos[("Vacuna", insumo.nombre)]["precios"].add(precio)
                    summary["vacunas"] += precio

                for item in analisis:
                    precio = Decimal(item.precio or 0)
                    conceptos[("Análisis", item.tipo_analisis)]["cantidad"] += 1
                    conceptos[("Análisis", item.tipo_analisis)]["total"] += precio
                    conceptos[("Análisis", item.tipo_analisis)]["precios"].add(precio)
                    summary["analisis"] += precio

                summary["total"] = summary["consultas"] + summary["medicamentos"] + summary["vacunas"] + summary["analisis"]
                rows = []
                for (categoria, concepto), data in conceptos.items():
                    unit_price = "Variable" if len(data["precios"]) > 1 else _format_currency(next(iter(data["precios"])) if data["precios"] else 0)
                    rows.append(
                        {
                            "categoria": categoria,
                            "concepto": concepto,
                            "cantidad": data["cantidad"],
                            "precio_unitario": unit_price,
                            "total": data["total"],
                        }
                    )
                rows.sort(key=lambda row: (row["categoria"], row["concepto"]))
                export_urls = _render_export_urls("reportes.reportes_ingresos", filters)

    if export_format in EXPORT_FORMATS and rows and not errores_campo:
        headers = ["Categoría", "Concepto", "Cantidad", "Precio unitario", "Monto total"]
        export_rows = [[row["categoria"], row["concepto"], row["cantidad"], row["precio_unitario"], _format_currency(row["total"])] for row in rows]
        subtitle = f"Periodo: {filters['fecha_inicio']} a {filters['fecha_fin']}"
        return _export_response(
            title="Reporte financiero de ingresos",
            subtitle=subtitle,
            headers=headers,
            rows=export_rows,
            export_format=export_format,
            filename_base="reporte_financiero_ingresos",
        )

    return render_template(
        "reporte_ingresos.html",
        me=me,
        active_nav="reportes",
        tabs=_build_report_tabs(me),
        active_report="ingresos",
        filtros=filters,
        errores_campo=errores_campo,
        rows=rows,
        summary=summary,
        export_urls=export_urls,
        format_currency=_format_currency,
    )


@reportes_bp.get("/reportes/productividad")
def reportes_productividad():
    """Función para reportes productividad."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r
    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()
    if not _require_roles(me, {ROLE_ADMIN, ROLE_VETERINARIO}):
        return render_template("acceso_denegado.html", me=me)

    role = _nombre_rol(me)
    my_id = _parsear_entero(me.get("id"))
    veterinarios = _obtener_veterinarios()
    filters = {
        "fecha_inicio": (request.args.get("fecha_inicio") or "").strip(),
        "fecha_fin": (request.args.get("fecha_fin") or "").strip(),
        "veterinario_id": (request.args.get("veterinario_id") or "").strip(),
    }
    export_format = (request.args.get("export_format") or "").strip().lower()
    if role == ROLE_VETERINARIO:
        filters["veterinario_id"] = str(my_id or "")

    errores_campo = {}
    rows = []
    summary = {"consultas": 0, "medicamentos": 0, "vacunas": 0, "analisis": 0, "total": 0}
    export_urls = {}

    if filters["fecha_inicio"] or filters["fecha_fin"] or export_format:
        errores_campo, fecha_inicio, fecha_fin = _validar_periodo(filters["fecha_inicio"], filters["fecha_fin"])
        selected_vet_id = _parsear_entero(filters["veterinario_id"])
        vet_map = {vet.id: vet.nombre for vet in veterinarios}
        if role == ROLE_VETERINARIO:
            selected_vet_id = my_id
        elif filters["veterinario_id"] and selected_vet_id not in vet_map:
            errores_campo["veterinario_id"] = "Debes seleccionar un veterinario válido."

        if not errores_campo:
            consultas_query = (
                db.session.query(ConsultaMedica)
                .filter(ConsultaMedica.fecha_consulta >= fecha_inicio, ConsultaMedica.fecha_consulta <= fecha_fin)
            )
            vacunas_query = (
                db.session.query(VacunaAlergia)
                .filter(VacunaAlergia.tipo_registro == "vacuna")
                .filter(VacunaAlergia.fecha_registro >= fecha_inicio, VacunaAlergia.fecha_registro <= fecha_fin)
            )
            analisis_query = (
                db.session.query(AnalisisClinico)
                .filter(AnalisisClinico.fecha_analisis >= fecha_inicio, AnalisisClinico.fecha_analisis <= fecha_fin)
            )
            if selected_vet_id:
                consultas_query = consultas_query.filter(ConsultaMedica.veterinario_id == selected_vet_id)
                vacunas_query = vacunas_query.filter(VacunaAlergia.veterinario_id == selected_vet_id)
                analisis_query = analisis_query.filter(AnalisisClinico.veterinario_id == selected_vet_id)

            consultas = consultas_query.all()
            vacunas = vacunas_query.all()
            analisis = analisis_query.all()
            if not any([consultas, vacunas, analisis]):
                errores_campo["fecha_fin"] = "No hay actividad registrada para el periodo seleccionado."
            else:
                by_vet = defaultdict(lambda: {"consultas": 0, "medicamentos": 0, "vacunas": 0, "analisis": 0, "total": 0})
                for item in consultas:
                    bucket = by_vet[item.veterinario_id]
                    bucket["consultas"] += 1
                    bucket["medicamentos"] += 1 if item.insumo_clinico_id else 0
                for item in vacunas:
                    by_vet[item.veterinario_id]["vacunas"] += 1
                for item in analisis:
                    by_vet[item.veterinario_id]["analisis"] += 1

                rows = []
                for vet_id, data in by_vet.items():
                    total = data["consultas"] + data["medicamentos"] + data["vacunas"] + data["analisis"]
                    data["total"] = total
                    rows.append(
                        {
                            "veterinario": vet_map.get(vet_id, f"Veterinario #{vet_id}"),
                            "consultas": data["consultas"],
                            "medicamentos": data["medicamentos"],
                            "vacunas": data["vacunas"],
                            "analisis": data["analisis"],
                            "total": total,
                        }
                    )
                rows.sort(key=lambda row: row["veterinario"])
                if selected_vet_id and rows:
                    row = rows[0]
                    summary = {
                        "consultas": row["consultas"],
                        "medicamentos": row["medicamentos"],
                        "vacunas": row["vacunas"],
                        "analisis": row["analisis"],
                        "total": row["total"],
                    }
                else:
                    for row in rows:
                        summary["consultas"] += row["consultas"]
                        summary["medicamentos"] += row["medicamentos"]
                        summary["vacunas"] += row["vacunas"]
                        summary["analisis"] += row["analisis"]
                        summary["total"] += row["total"]
                export_urls = _render_export_urls("reportes.reportes_productividad", filters)

    if export_format in EXPORT_FORMATS and rows and not errores_campo:
        headers = ["Veterinario", "Consultas", "Medicamentos", "Vacunas", "Análisis", "Total de actividades"]
        export_rows = [[row["veterinario"], row["consultas"], row["medicamentos"], row["vacunas"], row["analisis"], row["total"]] for row in rows]
        subtitle = f"Periodo: {filters['fecha_inicio']} a {filters['fecha_fin']}"
        return _export_response(
            title="Reporte de productividad",
            subtitle=subtitle,
            headers=headers,
            rows=export_rows,
            export_format=export_format,
            filename_base="reporte_productividad",
        )

    return render_template(
        "reporte_productividad.html",
        me=me,
        active_nav="reportes",
        tabs=_build_report_tabs(me),
        active_report="productividad",
        filtros=filters,
        errores_campo=errores_campo,
        veterinarios=veterinarios,
        rows=rows,
        summary=summary,
        export_urls=export_urls,
        role=role,
    )


@reportes_bp.get("/reportes/clientes-nuevos")
def reportes_clientes_nuevos():
    """Función para reportes clientes nuevos."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r
    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()
    if not _require_roles(me, {ROLE_ADMIN}):
        return render_template("acceso_denegado.html", me=me)

    today = date.today()
    filters = {
        "month": (request.args.get("month") or str(today.month)).strip(),
        "year": (request.args.get("year") or str(today.year)).strip(),
        "fecha_inicio": (request.args.get("fecha_inicio") or "").strip(),
        "fecha_fin": (request.args.get("fecha_fin") or "").strip(),
        "use_date_range": (request.args.get("use_date_range") or "").strip().lower() in {"1", "true", "on", "yes"},
    }
    export_format = (request.args.get("export_format") or "").strip().lower()
    errores_campo = {}
    rows = []
    summary = {"total": 0}
    export_urls = {}
    subtitle = ""

    role_alias = aliased(Rol)
    q = (
        db.session.query(Usuario)
        .join(role_alias, Usuario.rol_id == role_alias.id)
        .filter(func.lower(role_alias.nombre) == ROLE_CLIENTE)
        .filter(Usuario.eliminado.is_(False))
    )

    if filters["use_date_range"]:
        errores_campo, fecha_inicio, fecha_fin = _validar_periodo(filters["fecha_inicio"], filters["fecha_fin"])
        if not errores_campo:
            start_dt, end_dt = _inicio_fin_datetime(fecha_inicio, fecha_fin)
            clientes = (
                q.filter(Usuario.fecha_registro >= start_dt)
                .filter(Usuario.fecha_registro <= end_dt)
                .order_by(Usuario.fecha_registro.asc(), Usuario.nombre.asc())
                .all()
            )
            if not clientes:
                errores_campo["fecha_fin"] = "No hay clientes nuevos para el periodo seleccionado."
            else:
                by_source = defaultdict(int)
                for client in clientes:
                    source_key = (client.fuente_captacion or "").strip().lower() or "sin_dato"
                    by_source[source_key] += 1
                    rows.append(
                        {
                            "cliente": client.nombre,
                            "correo": client.correo,
                            "fecha_registro": client.fecha_registro.strftime("%Y-%m-%d"),
                            "fuente": _titulo_fuente(client.fuente_captacion),
                        }
                    )
                summary["total"] = len(clientes)
                summary["por_fuente"] = [{"fuente": _titulo_fuente(source), "cantidad": cantidad} for source, cantidad in sorted(by_source.items())]
                export_urls = _render_export_urls("reportes.reportes_clientes_nuevos", filters)
                subtitle = f"Periodo: {filters['fecha_inicio']} a {filters['fecha_fin']}"
    else:
        month = _parsear_entero(filters["month"])
        year = _parsear_entero(filters["year"])
        if month is None or month < 1 or month > 12:
            errores_campo["month"] = "Debes seleccionar un mes válido."
        if year is None or year < 2000 or year > today.year:
            errores_campo["year"] = "Debes seleccionar un año válido."

        if not errores_campo:
            period_start, period_end = _month_bounds(year, month)
            clientes = (
                q.filter(Usuario.fecha_registro >= datetime.combine(period_start, time.min))
                .filter(Usuario.fecha_registro <= datetime.combine(period_end, time.max))
                .order_by(Usuario.fecha_registro.asc(), Usuario.nombre.asc())
                .all()
            )
            if not clientes:
                errores_campo["year"] = "No hay clientes nuevos para el mes seleccionado."
            else:
                by_source = defaultdict(int)
                for client in clientes:
                    source_key = (client.fuente_captacion or "").strip().lower() or "sin_dato"
                    by_source[source_key] += 1
                    rows.append(
                        {
                            "cliente": client.nombre,
                            "correo": client.correo,
                            "fecha_registro": client.fecha_registro.strftime("%Y-%m-%d"),
                            "fuente": _titulo_fuente(client.fuente_captacion),
                        }
                    )
                summary["total"] = len(clientes)
                summary["por_fuente"] = [{"fuente": _titulo_fuente(source), "cantidad": cantidad} for source, cantidad in sorted(by_source.items())]
                export_urls = _render_export_urls("reportes.reportes_clientes_nuevos", filters)
                subtitle = f"Mes: {_nombre_mes(month)} {year}"

    if export_format in EXPORT_FORMATS and rows and not errores_campo:
        headers = ["Cliente", "Correo", "Fecha de registro", "Fuente de captación"]
        export_rows = [[row["cliente"], row["correo"], row["fecha_registro"], row["fuente"]] for row in rows]
        return _export_response(
            title="Reporte mensual de clientes nuevos",
            subtitle=subtitle,
            headers=headers,
            rows=export_rows,
            export_format=export_format,
            filename_base="reporte_clientes_nuevos",
        )

    return render_template(
        "reporte_clientes_nuevos.html",
        me=me,
        active_nav="reportes",
        tabs=_build_report_tabs(me),
        active_report="clientes_nuevos",
        filtros=filters,
        month_labels=MONTH_LABELS,
        errores_campo=errores_campo,
        rows=rows,
        summary=summary,
        export_urls=export_urls,
    )


@reportes_bp.get("/reportes/medicamentos")
def reportes_medicamentos():
    """Función para reportes medicamentos."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r
    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()
    if not _require_roles(me, {ROLE_ADMIN}):
        return render_template("acceso_denegado.html", me=me)

    filters = {
        "fecha_inicio": (request.args.get("fecha_inicio") or "").strip(),
        "fecha_fin": (request.args.get("fecha_fin") or "").strip(),
    }
    export_format = (request.args.get("export_format") or "").strip().lower()
    errores_campo = {}
    rows = []
    summary = {"aplicaciones": 0, "medicamentos": 0}
    export_urls = {}

    if filters["fecha_inicio"] or filters["fecha_fin"] or export_format:
        errores_campo, fecha_inicio, fecha_fin = _validar_periodo(filters["fecha_inicio"], filters["fecha_fin"])
        if not errores_campo:
            medicamentos = (
                db.session.query(ConsultaMedica, InsumoClinico)
                .join(InsumoClinico, ConsultaMedica.insumo_clinico_id == InsumoClinico.id)
                .filter(ConsultaMedica.fecha_administracion >= fecha_inicio, ConsultaMedica.fecha_administracion <= fecha_fin)
                .order_by(InsumoClinico.nombre.asc())
                .all()
            )
            vacunas = (
                db.session.query(VacunaAlergia, InsumoClinico)
                .join(InsumoClinico, VacunaAlergia.insumo_clinico_id == InsumoClinico.id)
                .filter(VacunaAlergia.tipo_registro == "vacuna")
                .filter(VacunaAlergia.fecha_registro >= fecha_inicio, VacunaAlergia.fecha_registro <= fecha_fin)
                .order_by(InsumoClinico.nombre.asc())
                .all()
            )
            analisis = (
                db.session.query(AnalisisClinico)
                .filter(AnalisisClinico.fecha_analisis >= fecha_inicio, AnalisisClinico.fecha_analisis <= fecha_fin)
                .order_by(AnalisisClinico.tipo_analisis.asc())
                .all()
            )
            if not any([medicamentos, vacunas, analisis]):
                errores_campo["fecha_fin"] = "No hay registros de medicamentos, vacunas o estudios para el periodo seleccionado."
            else:
                for _, insumo in medicamentos:
                    rows.append(
                        {
                            "tipo": "Medicamento",
                            "medicamento": insumo.nombre,
                            "fecha": _.fecha_administracion.strftime("%Y-%m-%d") if _.fecha_administracion else "-",
                            "cantidad": 1,
                            "precio_unitario": Decimal(insumo.precio or 0),
                            "total": Decimal(insumo.precio or 0),
                        }
                    )
                for _, insumo in vacunas:
                    rows.append(
                        {
                            "tipo": "Vacuna",
                            "medicamento": insumo.nombre,
                            "fecha": _.fecha_registro.strftime("%Y-%m-%d") if _.fecha_registro else "-",
                            "cantidad": 1,
                            "precio_unitario": Decimal(insumo.precio or 0),
                            "total": Decimal(insumo.precio or 0),
                        }
                    )
                for item in analisis:
                    rows.append(
                        {
                            "tipo": "Estudio",
                            "medicamento": item.tipo_analisis,
                            "fecha": item.fecha_analisis.strftime("%Y-%m-%d") if item.fecha_analisis else "-",
                            "cantidad": 1,
                            "precio_unitario": Decimal(item.precio or 0),
                            "total": Decimal(item.precio or 0),
                        }
                    )
                rows.sort(key=lambda row: (row["fecha"], row["tipo"], row["medicamento"]), reverse=True)
                summary["aplicaciones"] = sum(row["cantidad"] for row in rows)
                summary["medicamentos"] = len(rows)
                export_urls = _render_export_urls("reportes.reportes_medicamentos", filters)

    if export_format in EXPORT_FORMATS and rows and not errores_campo:
        headers = ["Fecha", "Tipo", "Concepto", "Aplicaciones", "Precio unitario", "Valor estimado"]
        export_rows = [[row["fecha"], row["tipo"], row["medicamento"], row["cantidad"], _format_currency(row["precio_unitario"]), _format_currency(row["total"])] for row in rows]
        subtitle = f"Periodo: {filters['fecha_inicio']} a {filters['fecha_fin']}"
        return _export_response(
            title="Reporte de medicamentos, vacunas y estudios más utilizados",
            subtitle=subtitle,
            headers=headers,
            rows=export_rows,
            export_format=export_format,
            filename_base="reporte_insumos_estudios_utilizados",
        )

    return render_template(
        "reporte_medicamentos.html",
        me=me,
        active_nav="reportes",
        tabs=_build_report_tabs(me),
        active_report="medicamentos",
        filtros=filters,
        errores_campo=errores_campo,
        rows=rows,
        summary=summary,
        export_urls=export_urls,
        format_currency=_format_currency,
    )


@reportes_bp.get("/reportes/clientes-frecuentes")
def reportes_clientes_frecuentes():
    """Función para reportes clientes frecuentes."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r
    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()
    if not _require_roles(me, {ROLE_ADMIN}):
        return render_template("acceso_denegado.html", me=me)

    filters = {
        "fecha_inicio": (request.args.get("fecha_inicio") or "").strip(),
        "fecha_fin": (request.args.get("fecha_fin") or "").strip(),
    }
    export_format = (request.args.get("export_format") or "").strip().lower()
    errores_campo = {}
    rows = []
    summary = {"clientes": 0, "consultas": 0}
    export_urls = {}

    if filters["fecha_inicio"] or filters["fecha_fin"] or export_format:
        errores_campo, fecha_inicio, fecha_fin = _validar_periodo(filters["fecha_inicio"], filters["fecha_fin"])
        if not errores_campo:
            dueno = aliased(Usuario)
            consultas = (
                db.session.query(ConsultaMedica, Mascota, dueno)
                .join(Mascota, ConsultaMedica.mascota_id == Mascota.id)
                .join(dueno, Mascota.dueno_id == dueno.id)
                .filter(ConsultaMedica.fecha_consulta >= fecha_inicio, ConsultaMedica.fecha_consulta <= fecha_fin)
                .order_by(dueno.nombre.asc())
                .all()
            )
            if not consultas:
                errores_campo["fecha_fin"] = "No hay consultas atendidas para el periodo seleccionado."
            else:
                by_client = defaultdict(lambda: {"correo": "", "visitas": 0, "mascotas": set()})
                for _, mascota, cliente in consultas:
                    bucket = by_client[cliente.nombre]
                    bucket["correo"] = cliente.correo or "-"
                    bucket["visitas"] += 1
                    bucket["mascotas"].add(mascota.nombre)
                rows = [
                    {
                        "cliente": client_name,
                        "correo": data["correo"],
                        "visitas": data["visitas"],
                        "mascotas": len(data["mascotas"]),
                        "periodo": f"{filters['fecha_inicio']} a {filters['fecha_fin']}",
                    }
                    for client_name, data in by_client.items()
                ]
                rows.sort(key=lambda row: (-row["visitas"], row["cliente"]))
                summary["clientes"] = len(rows)
                summary["consultas"] = sum(row["visitas"] for row in rows)
                export_urls = _render_export_urls("reportes.reportes_clientes_frecuentes", filters)

    if export_format in EXPORT_FORMATS and rows and not errores_campo:
        headers = ["Cliente", "Correo", "Visitas", "Mascotas atendidas", "Periodo analizado"]
        export_rows = [[row["cliente"], row["correo"], row["visitas"], row["mascotas"], row["periodo"]] for row in rows]
        subtitle = f"Periodo: {filters['fecha_inicio']} a {filters['fecha_fin']}"
        return _export_response(
            title="Reporte de clientes con mayor frecuencia de visitas",
            subtitle=subtitle,
            headers=headers,
            rows=export_rows,
            export_format=export_format,
            filename_base="reporte_clientes_frecuentes",
        )

    return render_template(
        "reporte_clientes_frecuentes.html",
        me=me,
        active_nav="reportes",
        tabs=_build_report_tabs(me),
        active_report="clientes_frecuentes",
        filtros=filters,
        errores_campo=errores_campo,
        rows=rows,
        summary=summary,
        export_urls=export_urls,
    )
