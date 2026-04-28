"""Módulo de datos."""

from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func

from app.extensions import db
from app.models import AnalisisClinico, Cita, ConsultaMedica, InsumoClinico, Rol, Usuario, VacunaAlergia
from utils.auth_ui import get_current_user_from_api

datos_bp = Blueprint("datos", __name__)

LOGIN_GET_ENDPOINT = "pages.pagina_inicio_sesion"
ROLE_ADMIN = "administrador"
CONSULTA_PRECIO_ESTIMADO = Decimal("300.00")


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


def _parsear_fecha(value: str):
    """Función para parsear fecha."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _inicio_mes_actual(hoy: date):
    """Función para inicio mes actual."""
    return hoy.replace(day=1)


def _fin_mes(year: int, month: int) -> date:
    """Función para fin mes."""
    return date(year, month, calendar.monthrange(year, month)[1])


def _inicio_fin_datetime(fecha_inicio: date, fecha_fin: date):
    """Función para inicio fin datetime."""
    return (
        datetime.combine(fecha_inicio, time.min),
        datetime.combine(fecha_fin, time.max),
    )


def _daterange(fecha_inicio: date, fecha_fin: date):
    """Función para daterange."""
    current = fecha_inicio
    while current <= fecha_fin:
        yield current
        current += timedelta(days=1)


def _validar_periodo(fecha_inicio_raw: str, fecha_fin_raw: str):
    """Función para validar periodo."""
    errores_campo = {}
    fecha_inicio = _parsear_fecha(fecha_inicio_raw)
    fecha_fin = _parsear_fecha(fecha_fin_raw)
    hoy = date.today()

    if not fecha_inicio_raw:
        errores_campo["fecha_inicio"] = "Debes seleccionar la fecha inicial."
    elif not fecha_inicio:
        errores_campo["fecha_inicio"] = "Debes seleccionar una fecha inicial válida."
    elif fecha_inicio > hoy:
        errores_campo["fecha_inicio"] = "La fecha inicial no puede ser posterior a hoy."

    if not fecha_fin_raw:
        errores_campo["fecha_fin"] = "Debes seleccionar la fecha final."
    elif not fecha_fin:
        errores_campo["fecha_fin"] = "Debes seleccionar una fecha final válida."
    elif fecha_fin > hoy:
        errores_campo["fecha_fin"] = "La fecha final no puede ser posterior a hoy."

    if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
        errores_campo["fecha_fin"] = "La fecha final no puede ser anterior a la fecha inicial."

    return errores_campo, fecha_inicio, fecha_fin


def _clasificar_servicio(consulta: ConsultaMedica) -> str:
    """Función para clasificar servicio."""
    if (consulta.tipo_analisis_relacionado or "").strip():
        return "Análisis de laboratorio"
    if consulta.vacuna_insumo_id:
        return "Vacunación"
    return "Consulta general"


def _format_currency(value) -> str:
    """Función para format currency."""
    amount = Decimal(value or 0)
    return f"${amount:.2f}"


def _resolve_citas_periodo(fecha_inicio: date, fecha_fin: date, *, include_current_month_future: bool):
    """Función para resolve citas periodo."""
    if not include_current_month_future:
        return fecha_inicio, fecha_fin
    if fecha_inicio.year == fecha_fin.year and fecha_inicio.month == fecha_fin.month:
        return fecha_inicio, _fin_mes(fecha_fin.year, fecha_fin.month)
    return fecha_inicio, fecha_fin


def _build_frequency_chart(fecha_inicio: date, fecha_fin: date, *, include_current_month_future: bool):
    """Función para build frequency chart."""
    fecha_inicio, fecha_fin = _resolve_citas_periodo(
        fecha_inicio,
        fecha_fin,
        include_current_month_future=include_current_month_future,
    )
    start_dt, end_dt = _inicio_fin_datetime(fecha_inicio, fecha_fin)
    counts = {}
    grouped_rows = (
        db.session.query(func.date(Cita.fecha_hora), func.count(Cita.id))
        .filter(Cita.fecha_hora >= start_dt, Cita.fecha_hora <= end_dt)
        .group_by(func.date(Cita.fecha_hora))
        .all()
    )
    for row_date, total in grouped_rows:
        if isinstance(row_date, str):
            try:
                row_date = datetime.strptime(row_date, "%Y-%m-%d").date()
            except ValueError:
                continue
        counts[row_date] = total
    period_days = (fecha_fin - fecha_inicio).days + 1
    labels = []
    values = []
    if period_days <= 31:
        granularity = "daily"
        for day in _daterange(fecha_inicio, fecha_fin):
            labels.append(day.strftime("%d %b"))
            values.append(int(counts.get(day, 0)))
    else:
        granularity = "weekly"
        bucket_start = fecha_inicio
        while bucket_start <= fecha_fin:
            bucket_end = min(bucket_start + timedelta(days=6), fecha_fin)
            total = 0
            current = bucket_start
            while current <= bucket_end:
                total += int(counts.get(current, 0))
                current += timedelta(days=1)
            if bucket_start.month == bucket_end.month:
                label = f"{bucket_start.strftime('%d')}-{bucket_end.strftime('%d %b')}"
            else:
                label = bucket_start.strftime("%d %b")
            labels.append(label)
            values.append(total)
            bucket_start = bucket_end + timedelta(days=1)

    max_value = max(values) if values else 0
    points = []
    total_points = len(values)
    chart_height = 220
    label_stride = 1 if total_points <= 8 else 2 if total_points <= 14 else 3 if total_points <= 20 else 4
    for index, value in enumerate(values):
        x_pct = (index / (total_points - 1) * 100) if total_points > 1 else 50
        y = chart_height - ((value / max_value) * (chart_height - 24)) if max_value else chart_height
        points.append(
            {
                "label": labels[index],
                "value": value,
                "x_pct": x_pct,
                "y": round(y, 2),
                "label_bottom": round(max(220 - y + 16, 14), 2),
                "show_value": value > 0,
                "show_label": index % label_stride == 0 or index == total_points - 1,
            }
        )
    y_ticks = []
    if max_value <= 0:
        y_ticks = [{"label": 0, "y": chart_height}]
    else:
        for tick_value in range(max_value, -1, -1):
            y = chart_height - ((tick_value / max_value) * (chart_height - 24))
            y_ticks.append({"label": tick_value, "y": round(y, 2)})
    polyline = " ".join(f"{point['x_pct']:.2f},{point['y']:.2f}" for point in points)
    return {
        "labels": labels,
        "values": values,
        "points": points,
        "polyline": polyline,
        "y_ticks": y_ticks,
        "granularity": granularity,
    }


def _build_services_chart(fecha_inicio: date, fecha_fin: date):
    """Función para build services chart."""
    consultas_generales = (
        db.session.query(func.count(ConsultaMedica.id))
        .filter(ConsultaMedica.fecha_consulta >= fecha_inicio, ConsultaMedica.fecha_consulta <= fecha_fin)
        .filter(ConsultaMedica.vacuna_insumo_id.is_(None))
        .filter(func.coalesce(ConsultaMedica.tipo_analisis_relacionado, "") == "")
        .scalar()
        or 0
    )
    vacunas = (
        db.session.query(func.count(VacunaAlergia.id))
        .filter(VacunaAlergia.tipo_registro == "vacuna")
        .filter(VacunaAlergia.fecha_registro >= fecha_inicio, VacunaAlergia.fecha_registro <= fecha_fin)
        .scalar()
        or 0
    )
    analisis = (
        db.session.query(func.count(AnalisisClinico.id))
        .filter(AnalisisClinico.fecha_analisis >= fecha_inicio, AnalisisClinico.fecha_analisis <= fecha_fin)
        .scalar()
        or 0
    )
    labels = ["Consulta general", "Vacunación", "Análisis de laboratorio"]
    values = [int(consultas_generales), int(vacunas), int(analisis)]
    max_value = max(values) if values else 0
    bars = []
    for index, label in enumerate(labels):
        value = values[index]
        bars.append(
            {
                "label": label,
                "value": value,
                "height_pct": ((value / max_value) * 100) if max_value else 0,
            }
        )
    return {"labels": labels, "values": values, "bars": bars}


def _build_quick_stats(fecha_inicio: date, fecha_fin: date, *, include_current_month_future: bool):
    """Función para build quick stats."""
    citas_inicio, citas_fin = _resolve_citas_periodo(
        fecha_inicio,
        fecha_fin,
        include_current_month_future=include_current_month_future,
    )
    start_dt, end_dt = _inicio_fin_datetime(citas_inicio, citas_fin)
    citas_total = (
        db.session.query(func.count(Cita.id))
        .filter(Cita.fecha_hora >= start_dt, Cita.fecha_hora <= end_dt)
        .scalar()
        or 0
    )
    consultas_total = (
        db.session.query(func.count(ConsultaMedica.id))
        .filter(ConsultaMedica.fecha_consulta >= fecha_inicio, ConsultaMedica.fecha_consulta <= fecha_fin)
        .scalar()
        or 0
    )
    vacunas_total = (
        db.session.query(func.count(VacunaAlergia.id))
        .filter(VacunaAlergia.tipo_registro == "vacuna")
        .filter(VacunaAlergia.fecha_registro >= fecha_inicio, VacunaAlergia.fecha_registro <= fecha_fin)
        .scalar()
        or 0
    )
    analisis_total = (
        db.session.query(func.count(AnalisisClinico.id))
        .filter(AnalisisClinico.fecha_analisis >= fecha_inicio, AnalisisClinico.fecha_analisis <= fecha_fin)
        .scalar()
        or 0
    )

    ingresos_citas = Decimal(citas_total) * CONSULTA_PRECIO_ESTIMADO
    ingresos_vacunas = (
        db.session.query(func.coalesce(func.sum(InsumoClinico.precio), 0))
        .join(VacunaAlergia, VacunaAlergia.insumo_clinico_id == InsumoClinico.id)
        .filter(VacunaAlergia.tipo_registro == "vacuna")
        .filter(VacunaAlergia.fecha_registro >= fecha_inicio, VacunaAlergia.fecha_registro <= fecha_fin)
        .scalar()
        or 0
    )
    ingresos_analisis = (
        db.session.query(func.coalesce(func.sum(AnalisisClinico.precio), 0))
        .filter(AnalisisClinico.fecha_analisis >= fecha_inicio, AnalisisClinico.fecha_analisis <= fecha_fin)
        .scalar()
        or 0
    )
    ingresos_total = ingresos_citas + Decimal(ingresos_vacunas or 0) + Decimal(ingresos_analisis or 0)

    return {
        "citas_total": int(citas_total),
        "consultas_total": int(consultas_total),
        "vacunas_total": int(vacunas_total),
        "analisis_total": int(analisis_total),
        "ingresos_total": _format_currency(ingresos_total),
    }


def _build_monitoring(fecha_referencia: date):
    """Función para build monitoring."""
    start_dt, end_dt = _inicio_fin_datetime(fecha_referencia, fecha_referencia)

    citas_hoy = (
        db.session.query(func.count(Cita.id))
        .filter(Cita.fecha_hora >= start_dt, Cita.fecha_hora <= end_dt)
        .scalar()
        or 0
    )
    consultas_hoy = (
        db.session.query(func.count(ConsultaMedica.id))
        .filter(ConsultaMedica.fecha_consulta == fecha_referencia)
        .scalar()
        or 0
    )
    vacunas_hoy = (
        db.session.query(func.count(VacunaAlergia.id))
        .filter(VacunaAlergia.tipo_registro == "vacuna", VacunaAlergia.fecha_registro == fecha_referencia)
        .scalar()
        or 0
    )
    analisis_hoy = (
        db.session.query(func.count(AnalisisClinico.id))
        .filter(AnalisisClinico.fecha_analisis == fecha_referencia)
        .scalar()
        or 0
    )
    citas_hoy_valor = Decimal(citas_hoy) * CONSULTA_PRECIO_ESTIMADO
    vacunas_hoy_valor = Decimal(
        (
            db.session.query(func.coalesce(func.sum(InsumoClinico.precio), 0))
            .join(VacunaAlergia, VacunaAlergia.insumo_clinico_id == InsumoClinico.id)
            .filter(VacunaAlergia.tipo_registro == "vacuna", VacunaAlergia.fecha_registro == fecha_referencia)
            .scalar()
        )
        or 0
    )
    ingresos_hoy = citas_hoy_valor + vacunas_hoy_valor + Decimal(
        (
            db.session.query(func.coalesce(func.sum(AnalisisClinico.precio), 0))
            .filter(AnalisisClinico.fecha_analisis == fecha_referencia)
            .scalar()
        )
        or 0
    )
    inicio_mes = fecha_referencia.replace(day=1)
    citas_mes = (
        db.session.query(func.count(Cita.id))
        .filter(Cita.fecha_hora >= datetime.combine(inicio_mes, time.min))
        .filter(Cita.fecha_hora <= datetime.combine(fecha_referencia, time.max))
        .scalar()
        or 0
    )
    ingresos_vacunas_mes = Decimal(
        (
            db.session.query(func.coalesce(func.sum(InsumoClinico.precio), 0))
            .join(VacunaAlergia, VacunaAlergia.insumo_clinico_id == InsumoClinico.id)
            .filter(VacunaAlergia.tipo_registro == "vacuna")
            .filter(VacunaAlergia.fecha_registro >= inicio_mes, VacunaAlergia.fecha_registro <= fecha_referencia)
            .scalar()
        )
        or 0
    )
    ingresos_mensuales = (Decimal(citas_mes) * CONSULTA_PRECIO_ESTIMADO) + ingresos_vacunas_mes + Decimal(
        (
            db.session.query(func.coalesce(func.sum(AnalisisClinico.precio), 0))
            .filter(AnalisisClinico.fecha_analisis >= inicio_mes, AnalisisClinico.fecha_analisis <= fecha_referencia)
            .scalar()
        )
        or 0
    )

    vet_map = {
        usuario.id: usuario.nombre
        for usuario in (
            db.session.query(Usuario)
            .join(Rol, Usuario.rol_id == Rol.id)
            .filter(func.lower(Rol.nombre) == "veterinario")
            .filter(Usuario.eliminado.is_(False), Usuario.activo.is_(True))
            .all()
        )
    }
    productivity_by_vet = defaultdict(lambda: {"consultas": 0, "vacunas": 0, "analisis": 0, "total": 0})
    for item in (
        db.session.query(ConsultaMedica)
        .filter(ConsultaMedica.fecha_consulta == fecha_referencia)
        .all()
    ):
        productivity_by_vet[item.veterinario_id]["consultas"] += 1
    for item in (
        db.session.query(VacunaAlergia)
        .filter(VacunaAlergia.tipo_registro == "vacuna", VacunaAlergia.fecha_registro == fecha_referencia)
        .all()
    ):
        productivity_by_vet[item.veterinario_id]["vacunas"] += 1
    for item in (
        db.session.query(AnalisisClinico)
        .filter(AnalisisClinico.fecha_analisis == fecha_referencia)
        .all()
    ):
        productivity_by_vet[item.veterinario_id]["analisis"] += 1

    vet_rows = []
    for vet_id, data in productivity_by_vet.items():
        total = data["consultas"] + data["vacunas"] + data["analisis"]
        data["total"] = total
        vet_rows.append(
            {
                "veterinario": vet_map.get(vet_id, f"Veterinario #{vet_id}"),
                "consultas": data["consultas"],
                "vacunas": data["vacunas"],
                "analisis": data["analisis"],
                "total": total,
            }
        )
    vet_rows.sort(key=lambda row: (-row["total"], row["veterinario"]))

    return {
        "citas_hoy": int(citas_hoy),
        "consultas_hoy": int(consultas_hoy),
        "vacunas_hoy": int(vacunas_hoy),
        "analisis_hoy": int(analisis_hoy),
        "ingresos_hoy": _format_currency(ingresos_hoy),
        "ingresos_mensuales": _format_currency(ingresos_mensuales),
        "veterinarios": vet_rows,
        "ultima_actualizacion": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def _month_range(year: int, month: int):
    """Función para month range."""
    start = date(year, month, 1)
    return start, _fin_mes(year, month)


def _build_prediction(today: date):
    """Función para build prediction."""
    current_month_start = today.replace(day=1)
    history_months = []
    for offset in range(3, 0, -1):
        year = current_month_start.year
        month = current_month_start.month - offset
        while month <= 0:
            month += 12
            year -= 1
        month_start, month_end = _month_range(year, month)
        count = (
            db.session.query(func.count(Cita.id))
            .filter(Cita.fecha_hora >= datetime.combine(month_start, time.min))
            .filter(Cita.fecha_hora <= datetime.combine(month_end, time.max))
            .scalar()
            or 0
        )
        history_months.append({"label": month_start.strftime("%b %Y"), "total": int(count)})

    if sum(item["total"] for item in history_months) == 0:
        return {"ready": False, "message": "No se cuenta con datos suficientes para proyectar citas futuras."}

    current_total = (
        db.session.query(func.count(Cita.id))
        .filter(Cita.fecha_hora >= datetime.combine(current_month_start, time.min))
        .filter(Cita.fecha_hora <= datetime.combine(today, time.max))
        .scalar()
        or 0
    )

    if len(history_months) < 3:
        return {"ready": False, "message": "Se requieren al menos 3 meses de historial para generar la proyección."}

    monthly_totals = [item["total"] for item in history_months]
    average_total = sum(monthly_totals) / 3
    trend_adjustment = 0
    if monthly_totals[0] > 0:
        trend_adjustment = (monthly_totals[2] - monthly_totals[0]) / 2
    projected_total = max(0, round(average_total + trend_adjustment))

    next_month_year = current_month_start.year + (1 if current_month_start.month == 12 else 0)
    next_month = 1 if current_month_start.month == 12 else current_month_start.month + 1
    next_label = date(next_month_year, next_month, 1).strftime("%b %Y")
    daily_average = round(projected_total / calendar.monthrange(next_month_year, next_month)[1], 1)

    labels = [item["label"] for item in history_months] + [current_month_start.strftime("%b %Y"), next_label]
    series = monthly_totals + [int(current_total), int(projected_total)]
    max_value = max(series) if series else 0
    bars = []
    for index, label in enumerate(labels):
        value = series[index]
        bars.append(
            {
                "label": label,
                "value": value,
                "height_pct": ((value / max_value) * 100) if max_value else 0,
                "is_projected": index == len(labels) - 1,
            }
        )

    return {
        "ready": True,
        "bars": bars,
        "projected_total": int(projected_total),
        "daily_average": daily_average,
        "history_window": "Últimos 3 meses cerrados + mes en curso",
        "method": "Promedio histórico ajustado por tendencia reciente",
    }


def _build_dashboard_context(fecha_inicio: date, fecha_fin: date, *, include_current_month_future: bool):
    """Función para build dashboard context."""
    frequency_chart = _build_frequency_chart(
        fecha_inicio,
        fecha_fin,
        include_current_month_future=include_current_month_future,
    )
    services_chart = _build_services_chart(fecha_inicio, fecha_fin)
    quick_stats = _build_quick_stats(
        fecha_inicio,
        fecha_fin,
        include_current_month_future=include_current_month_future,
    )
    monitoring = _build_monitoring(date.today())
    prediction = _build_prediction(date.today())

    total_points = sum(frequency_chart["values"]) + sum(services_chart["values"])
    has_period_data = total_points > 0

    return {
        "frequency_chart": frequency_chart,
        "services_chart": services_chart,
        "quick_stats": quick_stats,
        "monitoring": monitoring,
        "prediction": prediction,
        "has_period_data": has_period_data,
    }


@datos_bp.get("/datos")
def datos_dashboard():
    """Función para datos dashboard."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()
    if _nombre_rol(me) != ROLE_ADMIN:
        return render_template("acceso_denegado.html", me=me)

    today = date.today()
    default_start = _inicio_mes_actual(today)
    filters = {
        "fecha_inicio": (request.args.get("fecha_inicio") or default_start.isoformat()).strip(),
        "fecha_fin": (request.args.get("fecha_fin") or today.isoformat()).strip(),
    }
    errores_campo, fecha_inicio, fecha_fin = _validar_periodo(filters["fecha_inicio"], filters["fecha_fin"])

    dashboard = None
    if not errores_campo:
        include_current_month_future = not request.args
        dashboard = _build_dashboard_context(
            fecha_inicio,
            fecha_fin,
            include_current_month_future=include_current_month_future,
        )

    return render_template(
        "datos_dashboard.html",
        me=me,
        active_nav="datos",
        filtros=filters,
        errores_campo=errores_campo,
        dashboard=dashboard,
    )


@datos_bp.get("/datos/monitor")
def datos_monitor():
    """Función para datos monitor."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return jsonify({"ok": False, "message": "No autorizado."}), 401

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return jsonify({"ok": False, "message": "Sesión expirada."}), 401
    if _nombre_rol(me) != ROLE_ADMIN:
        return jsonify({"ok": False, "message": "Acceso denegado."}), 403

    monitoring = _build_monitoring(date.today())
    return jsonify({"ok": True, "monitoring": monitoring})
