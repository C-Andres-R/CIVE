"""Módulo de clientes."""

from __future__ import annotations

import re
from decimal import Decimal
from datetime import datetime, date

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.auth.password_policy import validate_password
from app.extensions import db
from app.models import Cita, EncuestaSatisfaccion, Facturacion, FotoMascota, Mascota, RecordatorioCita, Rol, Usuario
from utils.auth_ui import get_current_user_from_api

clientes_bp = Blueprint("clientes", __name__)

LOGIN_GET_ENDPOINT = "pages.pagina_inicio_sesion"

ROLE_ADMIN = "administrador"
ROLE_CLIENTE = "cliente"
ROLE_VETERINARIO = "veterinario"

PERMISSIONS = {
    "hu018": {ROLE_ADMIN},
    "hu019": {ROLE_ADMIN},
    "hu020": {ROLE_ADMIN},
    "hu021": {ROLE_ADMIN},
    "hu022": {ROLE_ADMIN, ROLE_CLIENTE, ROLE_VETERINARIO},
    "hu023": {ROLE_ADMIN, ROLE_CLIENTE},
    "hu024": {ROLE_CLIENTE},
}

PHONE_PATTERN = re.compile(r"^[0-9+\-()\s]{10,20}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CP_PATTERN = re.compile(r"^\d{5}$")
PERSON_NAME_PATTERN = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s]+$")
FINANCIAL_STATES = {"pagado", "pendiente", "parcial"}
CLIENT_SOURCE_OPTIONS = {"recomendacion", "redes_sociales"}


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


def _es_correo_valido(correo: str) -> bool:
    """Función para es correo valido."""
    return bool(EMAIL_PATTERN.match(correo or ""))


def _es_telefono_valido(phone: str) -> bool:
    """Función para es telefono valido."""
    if not PHONE_PATTERN.match(phone or ""):
        return False
    digits = re.sub(r"\D", "", phone or "")
    return 10 <= len(digits) <= 15


def _es_nombre_persona_valido(value: str) -> bool:
    """Función para es nombre persona valido."""
    if not value:
        return False
    return bool(PERSON_NAME_PATTERN.match(value))


def _nombre_completo(nombres: str, apellido_paterno: str, apellido_materno: str) -> str:
    """Función para nombre completo."""
    # Normaliza el nombre completo a partir de sus componentes.
    parts = [nombres.strip(), apellido_paterno.strip(), apellido_materno.strip()]
    return " ".join(part for part in parts if part)


def _direccion_completa(calle: str, numero: str, colonia: str, codigo_postal: str, estado: str, entidad: str) -> str:
    """Función para direccion completa."""
    street = " ".join(part for part in [calle.strip(), numero.strip()] if part).strip()
    tail = []
    if colonia.strip():
        tail.append(colonia.strip())
    if codigo_postal.strip():
        tail.append(f"CP {codigo_postal.strip()}")
    if estado.strip():
        tail.append(estado.strip())
    if entidad.strip():
        tail.append(entidad.strip())
    if street and tail:
        return f"{street}, {', '.join(tail)}"
    if street:
        return street
    if tail:
        return ", ".join(tail)
    return ""


def _obtener_rol_cliente():
    """Función para obtener rol cliente."""
    return (
        db.session.query(Rol)
        .filter(func.lower(Rol.nombre) == ROLE_CLIENTE)
        .first()
    )


def _obtener_cliente(cliente_id: int) -> Usuario | None:
    """Función para obtener cliente."""
    return (
        db.session.query(Usuario)
        .join(Rol, Usuario.rol_id == Rol.id)
        .filter(Usuario.id == cliente_id)
        .filter(func.lower(Rol.nombre) == ROLE_CLIENTE)
        .first()
    )


def _cliente_existe_para_acceso(cliente_id: int) -> Usuario | None:
    """Función para cliente existe para acceso."""
    client = _obtener_cliente(cliente_id)
    if not client or client.eliminado:
        return None
    return client


def _puede_acceder_recurso_cliente(me, cliente_id: int, hu_code: str) -> bool:
    """Función para puede acceder recurso cliente."""
    # Revisa si el usuario actual puede consultar recursos de un cliente.
    if not _permitido(me, hu_code):
        return False
    role = _nombre_rol(me)
    if role == ROLE_CLIENTE:
        return _parsear_entero(me.get("id")) == cliente_id
    return True


def _datos_formulario_cliente(form=None, client: Usuario | None = None):
    """Función para datos formulario cliente."""
    form = form or {}
    client_nombres = (client.nombres if client else "") or ""
    client_apellido_paterno = (client.apellido_paterno if client else "") or ""
    client_apellido_materno = (client.apellido_materno if client else "") or ""
    if client and not client_nombres and client.nombre:
        parts = [p for p in (client.nombre or "").split() if p]
        if parts:
            client_nombres = parts[0]
        if len(parts) >= 2:
            client_apellido_paterno = parts[1]
        if len(parts) >= 3:
            client_apellido_materno = " ".join(parts[2:])

    return {
        "nombres": (form.get("nombres") if form else None) or client_nombres,
        "apellido_paterno": (form.get("apellido_paterno") if form else None) or client_apellido_paterno,
        "apellido_materno": (form.get("apellido_materno") if form else None) or client_apellido_materno,
        "calle": (form.get("calle") if form else None) or (client.calle if client else "") or "",
        "numero": (form.get("numero") if form else None) or (client.numero if client else "") or "",
        "colonia": (form.get("colonia") if form else None) or (client.colonia if client else "") or "",
        "codigo_postal": (form.get("codigo_postal") if form else None) or (client.codigo_postal if client else "") or "",
        "estado": (form.get("estado") if form else None) or (client.estado if client else "") or "",
        "entidad": (form.get("entidad") if form else None) or (client.entidad if client else "") or "",
        "telefono": (form.get("telefono") if form else None) or (client.telefono if client else "") or "",
        "correo": (form.get("correo") if form else None) or (client.correo if client else "") or "",
        "fuente_captacion": (form.get("fuente_captacion") if form else None) or (client.fuente_captacion if client else "") or "",
    }


def _validar_formulario_cliente(
    form,
    *,
    cliente_id: int | None = None,
    require_password: bool = True,
    require_source: bool = True,
    current_source: str | None = None,
):
    """Función para validar formulario cliente."""
    errors = []
    errores_campo = {}

    nombres = (form.get("nombres") or "").strip()
    apellido_paterno = (form.get("apellido_paterno") or "").strip()
    apellido_materno = (form.get("apellido_materno") or "").strip()
    calle = (form.get("calle") or "").strip()
    numero = (form.get("numero") or "").strip()
    colonia = (form.get("colonia") or "").strip()
    codigo_postal = (form.get("codigo_postal") or "").strip()
    estado = (form.get("estado") or "").strip()
    entidad = (form.get("entidad") or "").strip()
    telefono = (form.get("telefono") or "").strip()
    correo = (form.get("correo") or "").strip().lower()
    contrasena = form.get("contrasena") or ""
    fuente_captacion = (form.get("fuente_captacion") or "").strip().lower()

    if not nombres:
        errores_campo["nombres"] = "El nombre es obligatorio."
    elif not _es_nombre_persona_valido(nombres):
        errores_campo["nombres"] = "El nombre no puede contener números."
    if apellido_paterno and not _es_nombre_persona_valido(apellido_paterno):
        errores_campo["apellido_paterno"] = "El apellido paterno no puede contener números."
    if apellido_materno and not _es_nombre_persona_valido(apellido_materno):
        errores_campo["apellido_materno"] = "El apellido materno no puede contener números."
    if codigo_postal and not CP_PATTERN.match(codigo_postal):
        errores_campo["codigo_postal"] = "El C.P. debe tener exactamente 5 dígitos."
    if not telefono:
        errores_campo["telefono"] = "El teléfono es obligatorio."
    elif not _es_telefono_valido(telefono):
        errores_campo["telefono"] = "El teléfono debe tener un formato válido."
    if not correo:
        errores_campo["correo"] = "El correo es obligatorio."
    elif not _es_correo_valido(correo):
        errores_campo["correo"] = "El correo no tiene un formato válido."
    if require_source:
        if not fuente_captacion:
            errores_campo["fuente_captacion"] = "Debes seleccionar una fuente de captación."
        elif fuente_captacion not in CLIENT_SOURCE_OPTIONS:
            errores_campo["fuente_captacion"] = "Debes seleccionar una fuente de captación válida."
    else:
        fuente_captacion = fuente_captacion or ((current_source or "").strip().lower())
        if fuente_captacion and fuente_captacion not in CLIENT_SOURCE_OPTIONS:
            fuente_captacion = ((current_source or "").strip().lower())

    if require_password and not contrasena:
        errores_campo["contrasena"] = "La contraseña es obligatoria."
    if contrasena:
        password_errors = validate_password(contrasena, correo=correo, nombre=_nombre_completo(nombres, apellido_paterno, apellido_materno))
        if password_errors:
            errores_campo["contrasena"] = " ".join(password_errors)

    if correo:
        duplicate_query = db.session.query(Usuario.id).filter(func.lower(Usuario.correo) == correo.lower())
        if cliente_id is not None:
            duplicate_query = duplicate_query.filter(Usuario.id != cliente_id)
        if duplicate_query.first():
            errores_campo["correo"] = "Ya existe un cliente con ese correo."

    errors.extend(errores_campo.values())

    nombre = _nombre_completo(nombres, apellido_paterno, apellido_materno)
    domicilio = _direccion_completa(calle, numero, colonia, codigo_postal, estado, entidad)

    payload = {
        "nombres": nombres,
        "apellido_paterno": apellido_paterno or None,
        "apellido_materno": apellido_materno or None,
        "nombre": nombre,
        "calle": calle or None,
        "numero": numero or None,
        "colonia": colonia or None,
        "codigo_postal": codigo_postal or None,
        "estado": estado or None,
        "entidad": entidad or None,
        "domicilio": domicilio,
        "telefono": telefono,
        "correo": correo,
        "contrasena": contrasena,
        "fuente_captacion": fuente_captacion,
    }

    return errors, errores_campo, payload


def _consulta_clientes():
    """Función para consulta clientes."""
    pet_counts = (
        db.session.query(
            Mascota.dueno_id.label("cliente_id"),
            func.count(Mascota.id).label("mascotas_count"),
        )
        .group_by(Mascota.dueno_id)
        .subquery()
    )

    return (
        db.session.query(
            Usuario,
            func.coalesce(pet_counts.c.mascotas_count, 0).label("mascotas_count"),
        )
        .join(Rol, Usuario.rol_id == Rol.id)
        .outerjoin(pet_counts, pet_counts.c.cliente_id == Usuario.id)
        .filter(func.lower(Rol.nombre) == ROLE_CLIENTE)
        .filter(Usuario.eliminado.is_(False))
        .order_by(Usuario.nombre.asc(), Usuario.id.asc())
    )


def _mascotas_cliente(cliente_id: int):
    """Función para mascotas cliente."""
    return (
        db.session.query(Mascota)
        .filter(Mascota.dueno_id == cliente_id)
        .order_by(Mascota.nombre.asc(), Mascota.id.asc())
        .all()
    )


def _foto_previews_cliente(mascota_ids: list[int]):
    """Función para foto previews cliente."""
    # Función de vista previa multimedia.
    if not mascota_ids:
        return {}

    rows = (
        db.session.query(FotoMascota)
        .filter(FotoMascota.mascota_id.in_(mascota_ids))
        .order_by(FotoMascota.mascota_id.asc(), FotoMascota.fecha_subida.desc(), FotoMascota.id.desc())
        .all()
    )

    previews = {}
    for row in rows:
        if row.mascota_id in previews:
            continue
        previews[row.mascota_id] = {
            "path": row.url_foto,
            "name": row.nombre_archivo or "Foto de mascota",
        }
    return previews


def _citas_cliente(cliente_id: int):
    """Función para citas cliente."""
    # Función de recordatorio automático.
    return (
        db.session.query(
            Cita,
            Mascota.nombre.label("mascota_nombre"),
            RecordatorioCita.estado.label("recordatorio_estado"),
            RecordatorioCita.confirmado.label("recordatorio_confirmado"),
            RecordatorioCita.anticipacion_horas.label("recordatorio_anticipacion_horas"),
            RecordatorioCita.programado_para.label("recordatorio_programado_para"),
        )
        .join(Mascota, Mascota.id == Cita.mascota_id)
        .outerjoin(RecordatorioCita, RecordatorioCita.cita_id == Cita.id)
        .filter(Cita.cliente_id == cliente_id)
        .order_by(Cita.fecha_hora.desc(), Cita.id.desc())
        .all()
    )


def _filas_financieras_cliente(cliente_id: int):
    """Función para filas financieras cliente."""
    return (
        db.session.query(Facturacion)
        .filter(Facturacion.cliente_id == cliente_id)
        .order_by(Facturacion.fecha_pago.desc(), Facturacion.id.desc())
        .all()
    )


def _resumen_encuestas_cliente(cliente_id: int):
    """Función para resumen encuestas cliente."""
    rows = (
        db.session.query(EncuestaSatisfaccion)
        .filter(EncuestaSatisfaccion.cliente_id == cliente_id)
        .all()
    )
    return {
        "pendientes": sum(1 for row in rows if not row.respondido),
        "respondidas": sum(1 for row in rows if row.respondido),
    }


def _parsear_fecha_datetime(value: str):
    """Función para parsear fecha datetime."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        return None


def _metodos_financieros():
    """Función para metodos financieros."""
    rows = (
        db.session.query(Facturacion.metodo_pago)
        .filter(Facturacion.metodo_pago.isnot(None))
        .distinct()
        .order_by(Facturacion.metodo_pago.asc())
        .all()
    )
    return [row[0] for row in rows if (row[0] or "").strip()]


def _filas_financieras_filtradas(cliente_id: int, *, fecha_inicio=None, fecha_fin=None, estado="", metodo_pago=""):
    """Función para filas financieras filtradas."""
    # Filtra los movimientos financieros del cliente según los criterios capturados.
    q = db.session.query(Facturacion).filter(Facturacion.cliente_id == cliente_id)
    if fecha_inicio:
        q = q.filter(Facturacion.fecha_pago >= fecha_inicio)
    if fecha_fin:
        q = q.filter(Facturacion.fecha_pago <= fecha_fin)
    if estado in FINANCIAL_STATES:
        q = q.filter(Facturacion.estado == estado)
    if metodo_pago:
        q = q.filter(func.lower(Facturacion.metodo_pago) == metodo_pago.lower())
    return q.order_by(Facturacion.fecha_pago.desc(), Facturacion.id.desc()).all()


def _resumen_financiero(rows: list[Facturacion]):
    """Función para resumen financiero."""
    # Resume los totales financieros de un cliente.
    total_pagado = sum((row.monto_pagado or Decimal("0")) for row in rows)
    total_descuento = sum((row.descuento or Decimal("0")) for row in rows)
    total_adeudo = sum((row.adeudo or Decimal("0")) for row in rows)
    total_facturado = sum((row.monto_total or Decimal("0")) for row in rows)
    pendientes = sum(1 for row in rows if row.estado in {"pendiente", "parcial"})
    return {
        "total_facturado": total_facturado,
        "total_pagado": total_pagado,
        "total_descuento": total_descuento,
        "total_adeudo": total_adeudo,
        "pendientes": pendientes,
    }


@clientes_bp.get("/clientes")
def clientes_lista():
    """Función para clientes lista."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    role = _nombre_rol(me)
    if role == ROLE_CLIENTE:
        return redirect(url_for("clientes.clientes_portal"))

    if role not in {ROLE_ADMIN, ROLE_VETERINARIO}:
        return render_template("acceso_denegado.html", me=me)

    rows = _consulta_clientes().all()
    return render_template(
        "clientes_list.html",
        me=me,
        active_nav="clientes",
        clientes_rows=rows,
        can_create=_permitido(me, "hu018"),
        can_edit=_permitido(me, "hu019"),
        can_inactivate=_permitido(me, "hu020"),
        can_notify=_permitido(me, "hu021"),
        can_view_pets=_permitido(me, "hu022"),
        can_view_finance=_permitido(me, "hu023"),
        can_generate_finance_report=(role == ROLE_ADMIN),
    )


@clientes_bp.route("/clientes/finanzas/generar", methods=["GET", "POST"])
def clientes_finanzas_generar():
    """Función para clientes finanzas generar."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if _nombre_rol(me) != ROLE_ADMIN:
        return render_template("acceso_denegado.html", me=me)

    clients = _consulta_clientes().all()
    payment_methods = _metodos_financieros()
    errores_campo = {}
    selected_client = None
    rows = []
    summary = _resumen_financiero(rows)
    filters = {
        "cliente_id": "",
        "fecha_inicio": "",
        "fecha_fin": "",
        "estado": "",
        "metodo_pago": "",
    }

    if request.method == "POST":
        cliente_id = _parsear_entero(request.form.get("cliente_id"))
        fecha_inicio_raw = request.form.get("fecha_inicio") or ""
        fecha_fin_raw = request.form.get("fecha_fin") or ""
        estado = (request.form.get("estado") or "").strip().lower()
        metodo_pago = (request.form.get("metodo_pago") or "").strip()

        filters = {
            "cliente_id": str(cliente_id or ""),
            "fecha_inicio": fecha_inicio_raw,
            "fecha_fin": fecha_fin_raw,
            "estado": estado,
            "metodo_pago": metodo_pago,
        }

        fecha_inicio = _parsear_fecha_datetime(fecha_inicio_raw)
        fecha_fin = _parsear_fecha_datetime(fecha_fin_raw)

        if not cliente_id:
            errores_campo["cliente_id"] = "Debes seleccionar el cliente."
        else:
            selected_client = _cliente_existe_para_acceso(cliente_id)
            if not selected_client:
                errores_campo["cliente_id"] = "El cliente seleccionado no existe."

        if fecha_inicio_raw and not fecha_inicio:
            errores_campo["fecha_inicio"] = "Debes seleccionar una fecha de inicio válida."
        elif fecha_inicio and fecha_inicio.date() > date.today():
            errores_campo["fecha_inicio"] = "La fecha de inicio no puede ser posterior a hoy."
        if fecha_fin_raw and not fecha_fin:
            errores_campo["fecha_fin"] = "Debes seleccionar una fecha de fin válida."
        if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
            errores_campo["fecha_fin"] = "La fecha de fin no puede ser anterior a la fecha de inicio."
        if estado and estado not in FINANCIAL_STATES:
            errores_campo["estado"] = "Debes seleccionar un estado válido."
        if metodo_pago and metodo_pago not in payment_methods:
            errores_campo["metodo_pago"] = "Debes seleccionar un método de pago válido."

        if not errores_campo and selected_client:
            if fecha_inicio:
                fecha_inicio = fecha_inicio.replace(hour=0, minute=0, second=0, microsecond=0)
            if fecha_fin:
                fecha_fin = fecha_fin.replace(hour=23, minute=59, second=59, microsecond=999999)
            rows = _filas_financieras_filtradas(
                selected_client.id,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                estado=estado,
                metodo_pago=metodo_pago,
            )
            summary = _resumen_financiero(rows)

    return render_template(
        "clientes_finanzas_generar.html",
        me=me,
        active_nav="clientes",
        clients=clients,
        payment_methods=payment_methods,
        errores_campo=errores_campo,
        filters=filters,
        selected_client=selected_client,
        financial_rows=rows,
        summary=summary,
    )


@clientes_bp.route("/clientes/nuevo", methods=["GET", "POST"])
def clientes_nuevo():
    """Función para clientes nuevo."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _permitido(me, "hu018"):
        return render_template("acceso_denegado.html", me=me)

    if request.method == "GET":
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="create",
            datos_formulario=_datos_formulario_cliente(),
            errores_campo={},
        )

    errors, errores_campo, payload = _validar_formulario_cliente(request.form, require_password=True)
    datos_formulario = _datos_formulario_cliente(request.form)

    if errors:
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="create",
            datos_formulario=datos_formulario,
            errores_campo=errores_campo,
        )

    role = _obtener_rol_cliente()
    if not role:
        flash("No existe el rol cliente en la base de datos.", "error")
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="create",
            datos_formulario=datos_formulario,
            errores_campo={},
        )

    client = Usuario(
        nombres=payload["nombres"],
        apellido_paterno=payload["apellido_paterno"],
        apellido_materno=payload["apellido_materno"],
        nombre=payload["nombre"],
        correo=payload["correo"],
        contrasena=generate_password_hash(payload["contrasena"]),
        calle=payload["calle"],
        numero=payload["numero"],
        colonia=payload["colonia"],
        codigo_postal=payload["codigo_postal"],
        estado=payload["estado"],
        entidad=payload["entidad"],
        domicilio=payload["domicilio"],
        telefono=payload["telefono"],
        fuente_captacion=payload["fuente_captacion"],
        razon_inactivacion=None,
        activo=True,
        eliminado=False,
        rol_id=role.id,
    )
    db.session.add(client)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("No fue posible registrar el cliente por un conflicto de datos.", "error")
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="create",
            datos_formulario=datos_formulario,
            errores_campo={},
        )

    flash("Cliente registrado correctamente.", "success")
    return redirect(url_for("clientes.clientes_lista"))


@clientes_bp.route("/clientes/<int:cliente_id>/editar", methods=["GET", "POST"])
def clientes_editar(cliente_id: int):
    """Función para clientes editar."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _permitido(me, "hu019"):
        return render_template("acceso_denegado.html", me=me)

    client = _cliente_existe_para_acceso(cliente_id)
    if not client:
        return render_template("cliente_no_encontrado.html", me=me, active_nav="clientes", cliente_id=cliente_id)

    if request.method == "GET":
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="edit",
            client=client,
            cliente_id=client.id,
            datos_formulario=_datos_formulario_cliente(client=client),
            errores_campo={},
        )

    errors, errores_campo, payload = _validar_formulario_cliente(request.form, cliente_id=client.id, require_password=False)
    datos_formulario = _datos_formulario_cliente(request.form, client)

    if errors:
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="edit",
            client=client,
            cliente_id=client.id,
            datos_formulario=datos_formulario,
            errores_campo=errores_campo,
        )

    client.nombres = payload["nombres"]
    client.apellido_paterno = payload["apellido_paterno"]
    client.apellido_materno = payload["apellido_materno"]
    client.nombre = payload["nombre"]
    client.calle = payload["calle"]
    client.numero = payload["numero"]
    client.colonia = payload["colonia"]
    client.codigo_postal = payload["codigo_postal"]
    client.estado = payload["estado"]
    client.entidad = payload["entidad"]
    client.domicilio = payload["domicilio"]
    client.telefono = payload["telefono"]
    client.correo = payload["correo"]
    client.fuente_captacion = payload["fuente_captacion"]
    if payload["contrasena"]:
        client.contrasena = generate_password_hash(payload["contrasena"])

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("No fue posible actualizar el cliente por un conflicto de datos.", "error")
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="edit",
            client=client,
            cliente_id=client.id,
            datos_formulario=datos_formulario,
            errores_campo={},
        )

    flash("Cliente actualizado correctamente.", "success")
    return redirect(url_for("clientes.clientes_lista"))


@clientes_bp.route("/clientes/<int:cliente_id>/inactivar", methods=["GET", "POST"])
def clientes_inactivar(cliente_id: int):
    """Función para clientes inactivar."""
    # Inactiva un cliente y guarda la razón indicada.
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _permitido(me, "hu020"):
        return render_template("acceso_denegado.html", me=me)

    client = _cliente_existe_para_acceso(cliente_id)
    if not client:
        return render_template("cliente_no_encontrado.html", me=me, active_nav="clientes", cliente_id=cliente_id)

    if request.method == "GET":
        return render_template(
            "cliente_inactivar.html",
            me=me,
            active_nav="clientes",
            client=client,
        )

    razon = (request.form.get("razon_inactivacion") or "").strip()
    confirmacion = request.form.get("confirmar") == "si"

    errors = []
    if not razon:
        errors.append("La razón de inactivación es obligatoria.")
    if not confirmacion:
        errors.append("Debes confirmar la inactivación.")

    if errors:
        for err in errors:
            flash(err, "error")
        return render_template(
            "cliente_inactivar.html",
            me=me,
            active_nav="clientes",
            client=client,
        )

    client.activo = False
    client.eliminado = False
    client.razon_inactivacion = razon
    db.session.commit()

    flash("Cliente inactivado correctamente.", "success")
    return redirect(url_for("clientes.clientes_lista"))


@clientes_bp.route("/clientes/<int:cliente_id>/notificar", methods=["GET", "POST"])
def clientes_notificar(cliente_id: int):
    """Función para clientes notificar."""
    # Envía una notificación por correo a un cliente.
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _permitido(me, "hu021"):
        return render_template("acceso_denegado.html", me=me)

    client = _cliente_existe_para_acceso(cliente_id)
    if not client:
        return render_template("cliente_no_encontrado.html", me=me, active_nav="clientes", cliente_id=cliente_id)

    default_subject = f"Notificación de CIVE para {client.nombre}"
    default_message = (
        f"Hola {client.nombre},\n\n"
        "Te contactamos desde CIVE para compartirte una notificación sobre tu cuenta.\n\n"
        "Quedamos atentos.\n"
        "Clínica CIVE"
    )

    if request.method == "GET":
        return render_template(
            "cliente_notificar.html",
            me=me,
            active_nav="clientes",
            client=client,
            datos_formulario={"asunto": default_subject, "mensaje": default_message},
        )

    subject = (request.form.get("asunto") or "").strip()
    body = (request.form.get("mensaje") or "").strip()

    if not subject or not body:
        flash("El asunto y el mensaje son obligatorios.", "error")
        return render_template(
            "cliente_notificar.html",
            me=me,
            active_nav="clientes",
            client=client,
            datos_formulario={"asunto": subject, "mensaje": body},
        )

    if not (client.correo or "").strip():
        flash("El cliente no tiene correo registrado.", "error")
        return render_template(
            "cliente_notificar.html",
            me=me,
            active_nav="clientes",
            client=client,
            datos_formulario={"asunto": subject, "mensaje": body},
        )

    from app.routes.chat import _enviar_email_smtp

    # Enviamos el correo y mostramos el error si el servicio no responde.
    sent_ok, sent_error = _enviar_email_smtp(client.correo.strip(), subject, body)
    if not sent_ok:
        flash(sent_error or "No fue posible enviar el correo.", "error")
        return render_template(
            "cliente_notificar.html",
            me=me,
            active_nav="clientes",
            client=client,
            datos_formulario={"asunto": subject, "mensaje": body},
        )

    flash("Notificación enviada correctamente.", "success")
    return redirect(url_for("clientes.clientes_lista"))


@clientes_bp.get("/clientes/<int:cliente_id>/mascotas")
def clientes_mascotas(cliente_id: int):
    """Función para clientes mascotas."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _puede_acceder_recurso_cliente(me, cliente_id, "hu022"):
        return render_template("acceso_denegado.html", me=me)

    client = _cliente_existe_para_acceso(cliente_id)
    if not client:
        return render_template("cliente_no_encontrado.html", me=me, active_nav="clientes", cliente_id=cliente_id)

    pets = _mascotas_cliente(client.id)
    foto_previews = _foto_previews_cliente([pet.id for pet in pets])
    return render_template(
        "cliente_mascotas.html",
        me=me,
        active_nav="clientes",
        client=client,
        pets=pets,
        foto_previews=foto_previews,
    )


@clientes_bp.get("/clientes/<int:cliente_id>/finanzas")
def clientes_finanzas(cliente_id: int):
    """Función para clientes finanzas."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _puede_acceder_recurso_cliente(me, cliente_id, "hu023"):
        return render_template("acceso_denegado.html", me=me)

    client = _cliente_existe_para_acceso(cliente_id)
    if not client:
        return render_template("cliente_no_encontrado.html", me=me, active_nav="clientes", cliente_id=cliente_id)

    rows = _filas_financieras_cliente(client.id)
    return render_template(
        "cliente_finanzas.html",
        me=me,
        active_nav="clientes",
        client=client,
        financial_rows=rows,
        summary=_resumen_financiero(rows),
    )


@clientes_bp.get("/portal-cliente")
def clientes_portal():
    """Función para clientes portal."""
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _permitido(me, "hu024"):
        return render_template("acceso_denegado.html", me=me)

    cliente_id = _parsear_entero(me.get("id"))
    client = _cliente_existe_para_acceso(cliente_id) if cliente_id is not None else None
    if not client:
        return render_template("cliente_no_encontrado.html", me=me, active_nav="clientes", cliente_id=cliente_id)

    pets = _mascotas_cliente(client.id)
    appointments = _citas_cliente(client.id)
    financial_rows = _filas_financieras_cliente(client.id)
    pending_rows = [row for row in financial_rows if row.estado in {"pendiente", "parcial"}]

    return render_template(
        "cliente_portal.html",
        me=me,
        active_nav="clientes",
        client=client,
        pets=pets,
        appointments=appointments,
        financial_rows=financial_rows,
        pending_rows=pending_rows,
        summary=_resumen_financiero(financial_rows),
        surveys_summary=_resumen_encuestas_cliente(client.id),
        now=datetime.now(),
    )


@clientes_bp.route("/portal-cliente/editar", methods=["GET", "POST"])
def clientes_portal_editar():
    """Función para clientes portal editar."""
    # Función de autoservicio del cliente.
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    if not _permitido(me, "hu024"):
        return render_template("acceso_denegado.html", me=me)

    cliente_id = _parsear_entero(me.get("id"))
    client = _cliente_existe_para_acceso(cliente_id) if cliente_id is not None else None
    if not client:
        return render_template("cliente_no_encontrado.html", me=me, active_nav="clientes", cliente_id=cliente_id)

    if request.method == "GET":
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="edit",
            client=client,
            cliente_id=client.id,
            datos_formulario=_datos_formulario_cliente(client=client),
            errores_campo={},
            self_service=True,
        )

    errors, errores_campo, payload = _validar_formulario_cliente(
        request.form,
        cliente_id=client.id,
        require_password=False,
        require_source=False,
        current_source=client.fuente_captacion,
    )
    datos_formulario = _datos_formulario_cliente(request.form, client)

    if errors:
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="edit",
            client=client,
            cliente_id=client.id,
            datos_formulario=datos_formulario,
            errores_campo=errores_campo,
            self_service=True,
        )

    client.nombres = payload["nombres"]
    client.apellido_paterno = payload["apellido_paterno"]
    client.apellido_materno = payload["apellido_materno"]
    client.nombre = payload["nombre"]
    client.calle = payload["calle"]
    client.numero = payload["numero"]
    client.colonia = payload["colonia"]
    client.codigo_postal = payload["codigo_postal"]
    client.estado = payload["estado"]
    client.entidad = payload["entidad"]
    client.domicilio = payload["domicilio"]
    client.telefono = payload["telefono"]
    client.correo = payload["correo"]
    if payload["contrasena"]:
        client.contrasena = generate_password_hash(payload["contrasena"])

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("No fue posible actualizar tus datos por un conflicto de información.", "error")
        return render_template(
            "cliente_form.html",
            me=me,
            active_nav="clientes",
            mode="edit",
            client=client,
            cliente_id=client.id,
            datos_formulario=datos_formulario,
            errores_campo={},
            self_service=True,
        )

    flash("Tus datos se actualizaron correctamente.", "success")
    return redirect(url_for("clientes.clientes_portal"))
