from __future__ import annotations

import os
import secrets
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy import MetaData, Table, func, insert, inspect, select
from sqlalchemy.orm import aliased
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import Cita, Mascota, Rol, Usuario
from utils.auth_ui import get_current_user_from_api

mascotas_bp = Blueprint("mascotas", __name__)

LOGIN_GET_ENDPOINT = "pages.pagina_inicio_sesion"

ROLE_ADMIN = "administrador"
ROLE_CLIENTE = "cliente"
ROLE_VETERINARIO = "veterinario"

PERMISSIONS = {
    "hu011": {ROLE_ADMIN, ROLE_VETERINARIO},
    "hu012": {ROLE_ADMIN, ROLE_VETERINARIO},
    "hu013": {ROLE_ADMIN, ROLE_VETERINARIO},
    "hu014": {ROLE_ADMIN, ROLE_CLIENTE, ROLE_VETERINARIO},
    "hu015": {ROLE_ADMIN},
    "hu016": {ROLE_ADMIN, ROLE_CLIENTE, ROLE_VETERINARIO},
    "hu017": {ROLE_ADMIN, ROLE_VETERINARIO},
}

ALLOWED_SPECIES = {"perro", "gato", "otro"}
ALLOWED_SEX = {"macho", "hembra"}
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "pdf"}
MAX_FILE_SIZE = 2 * 1024 * 1024
MAX_AGE_BY_SPECIES = {
    "perro": 30,
    "gato": 30,
    "otro": 50,
}


def _redirigir_a_inicio_sesion():
    return redirect(url_for(LOGIN_GET_ENDPOINT))


def _requiere_inicio_sesion_o_redirige():
    if not session.get("access_token"):
        return _redirigir_a_inicio_sesion()
    return None


def _obtener_usuario_o_cerrar_sesion():
    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return None
    return me


def _nombre_rol(me) -> str:
    return (me.get("rol") or "").strip().lower()


def _permitido(me, hu_code: str) -> bool:
    return _nombre_rol(me) in PERMISSIONS.get(hu_code, set())


def _redirigir_cliente_a_portal(me):
    if _nombre_rol(me) == ROLE_CLIENTE:
        return redirect(url_for("clientes.clientes_portal"))
    return None


def _parsear_entero(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parsear_flotante(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parsear_fecha(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _fecha_nacimiento_desde_edad(age: int):
    today = date.today()
    try:
        return date(today.year - age, today.month, today.day)
    except ValueError:
        return date(today.year - age, today.month, 1)


def _edad_desde_fecha_nacimiento(birthdate: date | None):
    if not birthdate:
        return None
    today = date.today()
    years = today.year - birthdate.year
    if (today.month, today.day) < (birthdate.month, birthdate.day):
        years -= 1
    return max(years, 0)


def _formatear_etiqueta_edad(age: int | None):
    if age is None:
        return ""
    suffix = "año" if age == 1 else "años"
    return f"{age} {suffix}"


def _contar_palabras(value: str) -> int:
    return len(re.findall(r"\S+", value or ""))


def _validar_nombre_mascota(raw_value: str):
    value = (raw_value or "").strip()
    if not value:
        return value, "El nombre debe tener entre 2 y 60 letras y contener una sola palabra."
    if len(value) < 2 or len(value) > 60 or any(ch.isspace() for ch in value):
        return value, "El nombre debe tener entre 2 y 60 letras y contener una sola palabra."
    if not all(ch.isalpha() for ch in value):
        return value, "El nombre no puede contener números, símbolos ni emojis."
    return value, None


def _validar_peso(raw_value: str):
    value = (raw_value or "").strip()
    if not value:
        return None, "El peso es obligatorio."
    if "," in value:
        return None, "Para indicar decimales, usa punto en lugar de coma."
    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        return None, "El peso debe ser un número mayor a 0."
    if "." in value and len(value.split(".", 1)[1]) > 2:
        return None, "El peso solo puede tener hasta 2 decimales."
    try:
        weight = Decimal(value)
    except InvalidOperation:
        return None, "El peso debe ser un número mayor a 0."
    if weight <= 0:
        return None, "El peso debe ser un número mayor a 0."
    if weight > Decimal("100"):
        return None, "El peso no puede ser mayor a 100 kg."
    return float(weight), None


def _validar_edad_aproximada(raw_value: str, especie: str):
    value = (raw_value or "").strip()
    if not value:
        return None, "Debes ingresar la fecha de nacimiento o la edad aproximada."
    if not re.fullmatch(r"\d+", value):
        return None, "La edad aproximada debe ser un número entero mayor o igual a 0."
    age = int(value)
    max_age = MAX_AGE_BY_SPECIES.get(especie)
    if max_age is not None and age > max_age:
        return None, "La edad aproximada excede el máximo permitido para la especie seleccionada."
    return age, None


def _construir_datos_formulario_mascota(form=None, mascota: Mascota | None = None):
    form = form or {}
    if mascota is not None and not form:
        edad_mostrada = _formatear_etiqueta_edad(_edad_desde_fecha_nacimiento(mascota.fecha_nacimiento))
        return {
            "nombre": mascota.nombre or "",
            "fecha_nacimiento": mascota.fecha_nacimiento.isoformat() if mascota.fecha_nacimiento else "",
            "usa_edad_aproximada": False,
            "edad": "",
            "edad_mostrada": edad_mostrada,
            "peso": f"{mascota.peso:.2f}" if mascota.peso is not None else "",
            "raza": mascota.raza or "",
            "especie": mascota.especie or "",
            "sexo": mascota.sexo or "",
            "datos_adicionales": mascota.datos_adicionales or "",
            "dueno_id": str(mascota.dueno_id or ""),
        }

    fecha_nacimiento = (form.get("fecha_nacimiento") or "").strip()
    usa_edad_aproximada = (form.get("usa_edad_aproximada") or "").strip().lower() in {"1", "true", "on", "yes"}
    edad = (form.get("edad") or "").strip()
    edad_mostrada = ""

    if not usa_edad_aproximada:
        edad_mostrada = _formatear_etiqueta_edad(_edad_desde_fecha_nacimiento(_parsear_fecha(fecha_nacimiento)))

    return {
        "nombre": ((form.get("nombre") or "").strip()),
        "fecha_nacimiento": fecha_nacimiento,
        "usa_edad_aproximada": usa_edad_aproximada,
        "edad": edad,
        "edad_mostrada": edad_mostrada,
        "peso": (form.get("peso") or "").strip(),
        "raza": (form.get("raza") or "").strip(),
        "especie": ((form.get("especie") or "").strip().lower()),
        "sexo": ((form.get("sexo") or "").strip().lower()),
        "datos_adicionales": (form.get("datos_adicionales") or "").strip(),
        "dueno_id": str(_parsear_entero(form.get("dueno_id")) or ""),
    }


def _es_cliente_activo(user: Usuario | None) -> bool:
    if not user:
        return False
    if user.eliminado or not user.activo:
        return False
    if not user.rol:
        return False
    return (user.rol.nombre or "").strip().lower() == ROLE_CLIENTE


def _get_clientes_activos():
    return (
        db.session.query(Usuario)
        .join(Rol, Usuario.rol_id == Rol.id)
        .filter(func.lower(Rol.nombre) == ROLE_CLIENTE)
        .filter(Usuario.eliminado.is_(False), Usuario.activo.is_(True))
        .order_by(Usuario.nombre.asc())
        .all()
    )


def _construir_consulta_mascotas(me):
    q = (
        db.session.query(Mascota, Usuario.nombre.label("dueno_nombre"), Usuario.activo.label("dueno_activo"))
        .join(Usuario, Mascota.dueno_id == Usuario.id)
        .filter(Usuario.eliminado.is_(False))
    )

    me_id = _parsear_entero(me.get("id"))
    if _nombre_rol(me) == ROLE_CLIENTE and me_id is not None:
        q = q.filter(Mascota.dueno_id == me_id)

    return q


def _usuario_puede_ver_mascota(me, mascota: Mascota) -> bool:
    # Revisa si el usuario actual puede consultar la mascota indicada.
    role = _nombre_rol(me)
    me_id = _parsear_entero(me.get("id"))
    if role in {ROLE_ADMIN, ROLE_VETERINARIO}:
        return True
    if role == ROLE_CLIENTE and me_id is not None:
        return mascota.dueno_id == me_id
    return False


def _validar_formulario_mascota(form, *, for_update: bool = False):
    errors = []
    errores_campo = {}

    nombre, nombre_error = _validar_nombre_mascota(form.get("nombre") or "")
    fecha_nacimiento_raw = (form.get("fecha_nacimiento") or "").strip()
    usa_edad_aproximada = (form.get("usa_edad_aproximada") or "").strip().lower() in {"1", "true", "on", "yes"}
    edad_raw = (form.get("edad") or "").strip()
    peso_raw = (form.get("peso") or "").strip()
    raza = (form.get("raza") or "").strip()
    especie = (form.get("especie") or "").strip().lower()
    sexo = (form.get("sexo") or "").strip().lower()
    datos_adicionales = (form.get("datos_adicionales") or "").strip()
    dueno_id = _parsear_entero(form.get("dueno_id"))

    fecha_nacimiento = _parsear_fecha(fecha_nacimiento_raw)
    peso, peso_error = _validar_peso(peso_raw)
    edad_aproximada = None

    if nombre_error:
        errores_campo["nombre"] = nombre_error

    if usa_edad_aproximada:
        edad_aproximada, edad_error = _validar_edad_aproximada(edad_raw, especie)
        if edad_error:
            errores_campo["edad"] = edad_error
        elif edad_aproximada is not None:
            fecha_nacimiento = _fecha_nacimiento_desde_edad(edad_aproximada)
    else:
        if not fecha_nacimiento:
            errores_campo["fecha_nacimiento"] = "Debes ingresar la fecha de nacimiento o la edad aproximada."
        elif fecha_nacimiento > date.today():
            errores_campo["fecha_nacimiento"] = "La fecha de nacimiento no puede ser futura."

    if peso_error:
        errores_campo["peso"] = peso_error

    if not especie or especie not in ALLOWED_SPECIES:
        errores_campo["especie"] = "La especie es obligatoria y debe ser válida."

    if not sexo or sexo not in ALLOWED_SEX:
        errores_campo["sexo"] = "El sexo es obligatorio y debe ser válido."

    if not dueno_id:
        errores_campo["dueno_id"] = "Debes asociar un dueño."

    if not raza:
        errores_campo["raza"] = "La raza es obligatoria."

    if datos_adicionales and _contar_palabras(datos_adicionales) > 100:
        errores_campo["datos_adicionales"] = "Los datos adicionales no pueden exceder 100 palabras."

    dueno = db.session.get(Usuario, dueno_id) if dueno_id else None
    if dueno_id and not _es_cliente_activo(dueno):
        errores_campo["dueno_id"] = "El dueño seleccionado no existe o no está activo."

    errors.extend(errores_campo.values())

    payload = {
        "nombre": nombre,
        "fecha_nacimiento": fecha_nacimiento,
        "edad_aproximada": edad_aproximada,
        "peso": peso,
        "raza": raza,
        "especie": especie,
        "sexo": sexo,
        "datos_adicionales": datos_adicionales or None,
        "dueno_id": dueno_id,
        "razon_inactivacion": None,
    }

    return errors, errores_campo, payload


def _reflejar_tabla(table_name: str) -> Table | None:
    if not inspect(db.engine).has_table(table_name):
        return None
    metadata = MetaData()
    return Table(table_name, metadata, autoload_with=db.engine)


def _buscar_columna(table: Table, candidates: list[str]):
    for name in candidates:
        if name in table.c:
            return table.c[name]
    return None


def _columnas_obligatorias_sin_predeterminado(table: Table):
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


def _construir_datos_multimedia(table: Table, *, mascota_id: int, rel_file_path: str, filename: str):
    payload: dict[str, object] = {}

    mascota_col = _buscar_columna(table, ["mascota_id", "id_mascota"])
    if mascota_col is not None:
        payload[mascota_col.name] = mascota_id

    file_col = _buscar_columna(
        table,
        [
            "url_foto",
            "archivo",
            "ruta_archivo",
            "ruta",
            "url",
            "path",
            "documento",
            "url_documento",
        ],
    )
    if file_col is not None:
        payload[file_col.name] = rel_file_path

    name_col = _buscar_columna(table, ["nombre_archivo", "nombre", "titulo"])
    if name_col is not None:
        payload[name_col.name] = filename

    date_col = _buscar_columna(table, ["fecha_subida", "fecha_registro", "fecha_creacion", "created_at"])
    if date_col is not None:
        payload[date_col.name] = datetime.now()

    required_cols = _columnas_obligatorias_sin_predeterminado(table)
    unknown_required = [c for c in required_cols if c not in payload and c not in ("id",)]
    if unknown_required:
        raise ValueError(
            "No se pudo guardar el archivo porque faltan columnas requeridas: "
            + ", ".join(unknown_required)
        )

    return payload


def _filas_multimedia(table: Table | None, *, mascota_id: int):
    if table is None:
        return []

    id_col = _buscar_columna(table, ["id"])
    mascota_col = _buscar_columna(table, ["mascota_id", "id_mascota"])
    file_col = _buscar_columna(
        table,
        [
            "url_foto",
            "archivo",
            "ruta_archivo",
            "ruta",
            "url",
            "path",
            "documento",
            "url_documento",
        ],
    )
    name_col = _buscar_columna(table, ["nombre_archivo", "nombre", "titulo"])
    date_col = _buscar_columna(table, ["fecha_subida", "fecha_registro", "fecha_creacion", "created_at"])

    if mascota_col is None or file_col is None:
        return []

    cols = [mascota_col, file_col]
    if id_col is not None:
        cols.append(id_col)
    if name_col is not None:
        cols.append(name_col)
    if date_col is not None:
        cols.append(date_col)

    stmt = select(*cols).where(mascota_col == mascota_id)
    if date_col is not None:
        stmt = stmt.order_by(date_col.desc())
    elif id_col is not None:
        stmt = stmt.order_by(id_col.desc())

    rows = db.session.execute(stmt).all()

    data = []
    for row in rows:
        mapping = row._mapping
        rel_path = mapping[file_col.name]
        data.append(
            {
                "path": rel_path,
                "name": mapping[name_col.name] if name_col is not None else os.path.basename(rel_path),
                "uploaded_at": mapping[date_col.name] if date_col is not None else None,
            }
        )
    return data


def _mapa_foto_principal(mascota_ids: list[int]):
    # Función de vista previa multimedia.
    fotos_table = _reflejar_tabla("fotos_mascota")
    if fotos_table is None:
        return {}

    previews: dict[int, dict[str, str]] = {}
    for mascota_id in mascota_ids:
        fotos = _filas_multimedia(fotos_table, mascota_id=mascota_id)
        if fotos:
            previews[mascota_id] = {
                "path": fotos[0]["path"],
                "name": fotos[0]["name"],
            }
    return previews


@mascotas_bp.get("/mascotas")
def mascotas_lista():
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    client_redirect = _redirigir_cliente_a_portal(me)
    if client_redirect:
        return client_redirect

    if not _permitido(me, "hu014"):
        return render_template("acceso_denegado.html", me=me)

    estado = (request.args.get("estado") or "").strip().lower()
    orden = (request.args.get("orden") or "asc").strip().lower()

    q = _construir_consulta_mascotas(me)

    if estado in {"activa", "inactiva"}:
        q = q.filter(Mascota.estado == estado)

    if orden == "desc":
        q = q.order_by(Mascota.fecha_registro.desc(), Mascota.id.desc())
    else:
        q = q.order_by(Mascota.fecha_registro.asc(), Mascota.id.asc())

    rows = q.all()
    mascota_ids = [mascota.id for mascota, *_ in rows]
    foto_previews = _mapa_foto_principal(mascota_ids)

    return render_template(
        "mascotas_list.html",
        me=me,
        active_nav="mascotas",
        mascotas_rows=rows,
        foto_previews=foto_previews,
        filters={"estado": estado, "orden": orden},
        can_create=_permitido(me, "hu011"),
        can_edit=_permitido(me, "hu012"),
        can_inactivate=_permitido(me, "hu013"),
        can_link_owner=_permitido(me, "hu015"),
        can_behavior=_permitido(me, "hu017"),
        can_multimedia=_permitido(me, "hu016"),
    )


@mascotas_bp.route("/mascotas/nueva", methods=["GET", "POST"])
def mascotas_nueva():
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    client_redirect = _redirigir_cliente_a_portal(me)
    if client_redirect:
        return client_redirect

    if not _permitido(me, "hu011"):
        return render_template("acceso_denegado.html", me=me)

    clientes = _get_clientes_activos()
    role = _nombre_rol(me)
    me_id = _parsear_entero(me.get("id"))

    if request.method == "GET":
        datos_formulario = _construir_datos_formulario_mascota()
        if role == ROLE_CLIENTE:
            datos_formulario["dueno_id"] = str(me_id or "")
        return render_template(
            "mascota_form.html",
            me=me,
            active_nav="mascotas",
            mode="create",
            datos_formulario=datos_formulario,
            errores_campo={},
            clientes=clientes,
            only_self_owner=(role == ROLE_CLIENTE),
            me_id=me_id,
        )

    errors, errores_campo, payload = _validar_formulario_mascota(request.form)

    if role == ROLE_CLIENTE and me_id is not None:
        payload["dueno_id"] = me_id

    datos_formulario = _construir_datos_formulario_mascota(request.form)
    datos_formulario["dueno_id"] = str(payload.get("dueno_id") or "")

    if errors:
        return render_template(
            "mascota_form.html",
            me=me,
            active_nav="mascotas",
            mode="create",
            datos_formulario=datos_formulario,
            errores_campo=errores_campo,
            clientes=clientes,
            only_self_owner=(role == ROLE_CLIENTE),
            me_id=me_id,
        )

    mascota = Mascota(
        nombre=payload["nombre"],
        fecha_nacimiento=payload["fecha_nacimiento"],
        peso=payload["peso"],
        raza=payload["raza"],
        especie=payload["especie"],
        sexo=payload["sexo"],
        datos_adicionales=payload["datos_adicionales"],
        dueno_id=payload["dueno_id"],
        estado="activa",
        razon_inactivacion=None,
    )

    db.session.add(mascota)
    db.session.commit()

    flash("Mascota registrada correctamente.", "success")
    return redirect(url_for("mascotas.mascotas_lista"))


@mascotas_bp.route("/mascotas/<int:mascota_id>/editar", methods=["GET", "POST"])
def mascotas_editar(mascota_id: int):
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    client_redirect = _redirigir_cliente_a_portal(me)
    if client_redirect:
        return client_redirect

    if not _permitido(me, "hu012"):
        return render_template("acceso_denegado.html", me=me)

    mascota = db.session.get(Mascota, mascota_id)
    if not mascota:
        flash("La mascota no existe.", "error")
        return redirect(url_for("mascotas.mascotas_lista"))

    if not _usuario_puede_ver_mascota(me, mascota):
        return render_template("acceso_denegado.html", me=me)

    role = _nombre_rol(me)
    me_id = _parsear_entero(me.get("id"))
    clientes = _get_clientes_activos()

    if request.method == "GET":
        datos_formulario = _construir_datos_formulario_mascota(mascota=mascota)

        return render_template(
            "mascota_form.html",
            me=me,
            active_nav="mascotas",
            mode="edit",
            mascota_id=mascota.id,
            datos_formulario=datos_formulario,
            errores_campo={},
            clientes=clientes,
            only_self_owner=(role == ROLE_CLIENTE),
            me_id=me_id,
        )

    errors, errores_campo, payload = _validar_formulario_mascota(request.form, for_update=True)

    if role == ROLE_CLIENTE and me_id is not None:
        payload["dueno_id"] = me_id

    datos_formulario = _construir_datos_formulario_mascota(request.form)
    datos_formulario["dueno_id"] = str(payload.get("dueno_id") or "")

    if errors:
        return render_template(
            "mascota_form.html",
            me=me,
            active_nav="mascotas",
            mode="edit",
            mascota_id=mascota.id,
            datos_formulario=datos_formulario,
            errores_campo=errores_campo,
            clientes=clientes,
            only_self_owner=(role == ROLE_CLIENTE),
            me_id=me_id,
        )

    mascota.nombre = payload["nombre"]
    mascota.fecha_nacimiento = payload["fecha_nacimiento"]
    mascota.peso = payload["peso"]
    mascota.raza = payload["raza"]
    mascota.especie = payload["especie"]
    mascota.sexo = payload["sexo"]
    mascota.datos_adicionales = payload["datos_adicionales"]
    mascota.dueno_id = payload["dueno_id"]

    db.session.commit()

    flash("Mascota actualizada correctamente.", "success")
    return redirect(url_for("mascotas.mascotas_lista"))


@mascotas_bp.route("/mascotas/<int:mascota_id>/inactivar", methods=["GET", "POST"])
def mascotas_inactivar(mascota_id: int):
    # Inactiva una mascota y guarda la razón indicada.
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    client_redirect = _redirigir_cliente_a_portal(me)
    if client_redirect:
        return client_redirect

    if not _permitido(me, "hu013"):
        return render_template("acceso_denegado.html", me=me)

    mascota = db.session.get(Mascota, mascota_id)
    if not mascota:
        flash("La mascota no existe.", "error")
        return redirect(url_for("mascotas.mascotas_lista"))

    if not _usuario_puede_ver_mascota(me, mascota):
        return render_template("acceso_denegado.html", me=me)

    if request.method == "GET":
        return render_template(
            "mascota_inactivar.html",
            me=me,
            active_nav="mascotas",
            mascota=mascota,
            datos_formulario={"razon_inactivacion": "", "confirmar": False},
            errores_campo={},
        )

    razon = (request.form.get("razon_inactivacion") or "").strip()
    confirmacion = request.form.get("confirmar") == "si"

    errors = []
    general_errors = []
    errores_campo = {}
    if not razon:
        errores_campo["razon_inactivacion"] = (
            "Este campo no puede estar vacío. Por favor indica la razón de desactivación."
        )
    if not confirmacion:
        general_errors.append("Debes confirmar la inactivación.")

    errors.extend(general_errors)
    errors.extend(errores_campo.values())

    if errors:
        for err in general_errors:
            flash(err, "error")
        return render_template(
            "mascota_inactivar.html",
            me=me,
            active_nav="mascotas",
            mascota=mascota,
            datos_formulario={"razon_inactivacion": razon, "confirmar": confirmacion},
            errores_campo=errores_campo,
        )

    mascota.estado = "inactiva"
    mascota.razon_inactivacion = razon
    db.session.commit()

    flash("Mascota inactivada correctamente.", "success")
    return redirect(url_for("mascotas.mascotas_lista"))


@mascotas_bp.route("/mascotas/<int:mascota_id>/vincular", methods=["GET", "POST"])
def mascotas_vincular_duenio(mascota_id: int):
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    client_redirect = _redirigir_cliente_a_portal(me)
    if client_redirect:
        return client_redirect

    if not _permitido(me, "hu015"):
        return render_template("acceso_denegado.html", me=me)

    mascota = db.session.get(Mascota, mascota_id)
    if not mascota:
        flash("La mascota no existe.", "error")
        return redirect(url_for("mascotas.mascotas_lista"))

    clientes = _get_clientes_activos()

    if request.method == "GET":
        return render_template(
            "mascota_vincular.html",
            me=me,
            active_nav="mascotas",
            mascota=mascota,
            clientes=clientes,
            selected_dueno_id=str(mascota.dueno_id),
        )

    nuevo_dueno_id = _parsear_entero(request.form.get("dueno_id"))
    dueno = db.session.get(Usuario, nuevo_dueno_id) if nuevo_dueno_id else None

    errors = []
    if not nuevo_dueno_id:
        errors.append("Debes seleccionar un dueño.")
    elif not _es_cliente_activo(dueno):
        errors.append("El dueño seleccionado no existe o no está activo.")

    if errors:
        for err in errors:
            flash(err, "error")
        return render_template(
            "mascota_vincular.html",
            me=me,
            active_nav="mascotas",
            mascota=mascota,
            clientes=clientes,
            selected_dueno_id=str(nuevo_dueno_id or ""),
        )

    mascota.dueno_id = nuevo_dueno_id
    db.session.commit()

    flash("Dueño vinculado correctamente.", "success")
    return redirect(url_for("mascotas.mascotas_lista"))


@mascotas_bp.route("/mascotas/<int:mascota_id>/comportamiento", methods=["GET", "POST"])
def mascotas_comportamiento(mascota_id: int):
    # Guarda observaciones de comportamiento para una mascota.
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    client_redirect = _redirigir_cliente_a_portal(me)
    if client_redirect:
        return client_redirect

    if not _permitido(me, "hu017"):
        return render_template("acceso_denegado.html", me=me)

    mascota = db.session.get(Mascota, mascota_id)
    if not mascota:
        flash("La mascota no existe.", "error")
        return redirect(url_for("mascotas.mascotas_lista"))

    if not _usuario_puede_ver_mascota(me, mascota):
        return render_template("acceso_denegado.html", me=me)

    if mascota.estado != "activa":
        flash("Solo se puede registrar comportamiento para mascotas activas.", "error")
        return redirect(url_for("expedientes.expedientes_detalle", mascota_id=mascota.id))

    if request.method == "GET":
        return render_template(
            "mascota_comportamiento.html",
            me=me,
            active_nav="expedientes",
            mascota=mascota,
            datos_formulario={"comportamiento": mascota.comportamiento or ""},
            errores_campo={},
        )

    comportamiento = (request.form.get("comportamiento") or "").strip()
    if not comportamiento:
        return render_template(
            "mascota_comportamiento.html",
            me=me,
            active_nav="expedientes",
            mascota=mascota,
            datos_formulario={"comportamiento": ""},
            errores_campo={
                "comportamiento": "Debes describir el comportamiento especial observado para continuar.",
            },
        )

    mascota.comportamiento = comportamiento
    db.session.commit()

    flash("Comportamiento guardado correctamente.", "success")
    return redirect(url_for("expedientes.expedientes_detalle", mascota_id=mascota.id))


@mascotas_bp.route("/mascotas/<int:mascota_id>/multimedia", methods=["GET", "POST"])
def mascotas_multimedia(mascota_id: int):
    r = _requiere_inicio_sesion_o_redirige()
    if r:
        return r

    me = _obtener_usuario_o_cerrar_sesion()
    if not me:
        return _redirigir_a_inicio_sesion()

    client_redirect = _redirigir_cliente_a_portal(me)
    if client_redirect:
        return client_redirect

    if not _permitido(me, "hu016"):
        return render_template("acceso_denegado.html", me=me)

    mascota = db.session.get(Mascota, mascota_id)
    if not mascota:
        flash("La mascota no existe.", "error")
        return redirect(url_for("mascotas.mascotas_lista"))

    if not _usuario_puede_ver_mascota(me, mascota):
        return render_template("acceso_denegado.html", me=me)

    fotos_table = _reflejar_tabla("fotos_mascota")
    docs_table = _reflejar_tabla("documentos_mascota")

    if request.method == "POST":
        uploaded = request.files.get("archivo")
        if not uploaded or not uploaded.filename:
            flash("Debes seleccionar un archivo.", "error")
            return redirect(url_for("mascotas.mascotas_multimedia", mascota_id=mascota.id))
        filename = secure_filename(uploaded.filename)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext not in ALLOWED_EXTENSIONS:
            flash("Formato inválido. Solo se permiten JPG, PNG o PDF.", "error")
            return redirect(url_for("mascotas.mascotas_multimedia", mascota_id=mascota.id))

        uploaded.stream.seek(0, os.SEEK_END)
        size = uploaded.stream.tell()
        uploaded.stream.seek(0)

        if size > MAX_FILE_SIZE:
            flash("El archivo excede el tamaño máximo permitido de 2MB.", "error")
            return redirect(url_for("mascotas.mascotas_multimedia", mascota_id=mascota.id))

        is_pdf = ext == "pdf"
        target_table = docs_table if is_pdf else fotos_table
        if target_table is None:
            missing_name = "documentos_mascota" if is_pdf else "fotos_mascota"
            flash(f"No existe la tabla {missing_name} en la base de datos.", "error")
            return redirect(url_for("mascotas.mascotas_multimedia", mascota_id=mascota.id))
        upload_dir = os.path.join(current_app.root_path, "static", "uploads", "mascotas", str(mascota.id))
        os.makedirs(upload_dir, exist_ok=True)

        token = secrets.token_hex(6)
        new_name = f"{token}_{filename}"
        abs_path = os.path.join(upload_dir, new_name)
        rel_path = os.path.join("uploads", "mascotas", str(mascota.id), new_name).replace("\\", "/")

        uploaded.save(abs_path)

        try:
            payload = _construir_datos_multimedia(
                target_table,
                mascota_id=mascota.id,
                rel_file_path=rel_path,
                filename=filename,
            )
            db.session.execute(insert(target_table).values(**payload))
            db.session.commit()
            flash("Archivo subido y registrado correctamente.", "success")
        except ValueError as ex:
            db.session.rollback()
            if os.path.exists(abs_path):
                os.remove(abs_path)
            flash(str(ex), "error")
        except Exception:
            db.session.rollback()
            if os.path.exists(abs_path):
                os.remove(abs_path)
            flash("No fue posible guardar el archivo en la base de datos.", "error")

        return redirect(url_for("mascotas.mascotas_multimedia", mascota_id=mascota.id))

    fotos = _filas_multimedia(fotos_table, mascota_id=mascota.id)
    documentos = _filas_multimedia(docs_table, mascota_id=mascota.id)

    return render_template(
        "mascota_multimedia.html",
        me=me,
        active_nav="expedientes",
        mascota=mascota,
        fotos=fotos,
        documentos=documentos,
        fotos_table_exists=fotos_table is not None,
        docs_table_exists=docs_table is not None,
    )


@mascotas_bp.get("/mascotas/<int:mascota_id>/historial")
def mascotas_historial(mascota_id: int):
    # Función de historial completo.
    return redirect(url_for("expedientes.expedientes_reporte", mascota_id=mascota_id))
