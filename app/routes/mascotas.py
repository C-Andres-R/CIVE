from __future__ import annotations

import os
import secrets
from datetime import date, datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy import MetaData, Table, func, insert, inspect, select
from sqlalchemy.orm import aliased
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import Cita, Mascota, Rol, Usuario
from utils.auth_ui import get_current_user_from_api

mascotas_bp = Blueprint("mascotas", __name__)

# --- CONFIGURACION DE MASCOTAS ---
LOGIN_GET_ENDPOINT = "pages.login_page"

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


# --- UTILIDADES DE ACCESO Y VALIDACION ---
def _redirect_to_login():
    # Redirige al formulario de inicio de sesión.
    return redirect(url_for(LOGIN_GET_ENDPOINT))


def _require_login_or_redirect():
    # Verifica que exista una sesión activa antes de continuar.
    if not session.get("access_token"):
        return _redirect_to_login()
    return None


def _get_me_or_logout():
    # Obtiene al usuario autenticado y limpia la sesión si ya no es válida.
    me = get_current_user_from_api()
    if not me:
        session.pop("access_token", None)
        return None
    return me


def _role_name(me) -> str:
    # Obtiene el nombre del rol actual en formato uniforme.
    return (me.get("rol") or "").strip().lower()


def _allowed(me, hu_code: str) -> bool:
    # Indica si el rol actual puede usar la historia de usuario solicitada.
    return _role_name(me) in PERMISSIONS.get(hu_code, set())


def _redirect_client_to_portal(me):
    # Redirige al cliente a su portal cuando la ruta no le corresponde.
    if _role_name(me) == ROLE_CLIENTE:
        return redirect(url_for("clientes.clientes_portal"))
    return None


def _parse_int(value):
    # Convierte un valor a entero y regresa None si no es válido.
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_float(value):
    # Convierte un valor a decimal y regresa None si no es válido.
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: str):
    # Convierte un texto a fecha con el formato esperado.
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _birthdate_from_age(age: int):
    # Calcula una fecha de nacimiento aproximada a partir de la edad.
    today = date.today()
    try:
        return date(today.year - age, today.month, today.day)
    except ValueError:
        return date(today.year - age, today.month, 1)


def _is_active_client(user: Usuario | None) -> bool:
    # Verifica que un usuario sea un cliente activo y disponible.
    if not user:
        return False
    if user.eliminado or not user.activo:
        return False
    if not user.rol:
        return False
    return (user.rol.nombre or "").strip().lower() == ROLE_CLIENTE


def _get_clientes_activos():
    # Obtiene los clientes activos para los formularios de mascotas.
    return (
        db.session.query(Usuario)
        .join(Rol, Usuario.rol_id == Rol.id)
        .filter(func.lower(Rol.nombre) == ROLE_CLIENTE)
        .filter(Usuario.eliminado.is_(False), Usuario.activo.is_(True))
        .order_by(Usuario.nombre.asc())
        .all()
    )


def _build_mascotas_query(me):
    # Construye la consulta base del listado de mascotas según el rol.
    q = (
        db.session.query(Mascota, Usuario.nombre.label("dueno_nombre"), Usuario.activo.label("dueno_activo"))
        .join(Usuario, Mascota.dueno_id == Usuario.id)
        .filter(Usuario.eliminado.is_(False))
    )

    me_id = _parse_int(me.get("id"))
    if _role_name(me) == ROLE_CLIENTE and me_id is not None:
        q = q.filter(Mascota.dueno_id == me_id)

    return q


def _user_can_view_pet(me, mascota: Mascota) -> bool:
    # Revisa si el usuario actual puede consultar la mascota indicada.
    role = _role_name(me)
    me_id = _parse_int(me.get("id"))
    if role in {ROLE_ADMIN, ROLE_VETERINARIO}:
        return True
    if role == ROLE_CLIENTE and me_id is not None:
        return mascota.dueno_id == me_id
    return False


def _validate_pet_form(form, *, for_update: bool = False):
    # Valida y normaliza los datos capturados en el formulario de mascotas.
    errors = []

    nombre = (form.get("nombre") or "").strip()
    fecha_nacimiento_raw = (form.get("fecha_nacimiento") or "").strip()
    edad_raw = (form.get("edad") or "").strip()
    peso_raw = (form.get("peso") or "").strip()
    raza = (form.get("raza") or "").strip()
    especie = (form.get("especie") or "").strip().lower()
    sexo = (form.get("sexo") or "").strip().lower()
    datos_adicionales = (form.get("datos_adicionales") or "").strip()
    dueno_id = _parse_int(form.get("dueno_id"))

    fecha_nacimiento = _parse_date(fecha_nacimiento_raw)
    edad = _parse_int(edad_raw)

    if not fecha_nacimiento and edad is not None and edad >= 0:
        fecha_nacimiento = _birthdate_from_age(edad)

    peso = _parse_float(peso_raw) if peso_raw else None

    if not nombre:
        errors.append("El nombre de la mascota es obligatorio.")

    if not fecha_nacimiento:
        errors.append("Debes capturar fecha de nacimiento válida o edad válida.")
    elif fecha_nacimiento > date.today():
        errors.append("La fecha de nacimiento no puede ser futura.")

    if peso is None:
        errors.append("El peso es obligatorio.")
    elif peso <= 0:
        errors.append("El peso debe ser un valor positivo.")

    if not especie or especie not in ALLOWED_SPECIES:
        errors.append("La especie es obligatoria y debe ser válida.")

    if not sexo or sexo not in ALLOWED_SEX:
        errors.append("El sexo es obligatorio y debe ser válido.")

    if not dueno_id:
        errors.append("Debes asociar un dueño.")

    if not raza:
        errors.append("La raza es obligatoria.")

    dueno = db.session.get(Usuario, dueno_id) if dueno_id else None
    if dueno_id and not _is_active_client(dueno):
        errors.append("El dueño seleccionado no existe o no está activo.")

    payload = {
        "nombre": nombre,
        "fecha_nacimiento": fecha_nacimiento,
        "peso": peso,
        "raza": raza,
        "especie": especie,
        "sexo": sexo,
        "datos_adicionales": datos_adicionales or None,
        "dueno_id": dueno_id,
        "razon_inactivacion": None,
    }

    return errors, payload


# --- CONSULTAS Y APOYO PARA MULTIMEDIA ---
def _reflect_table(table_name: str) -> Table | None:
    # Carga una tabla existente de la base de datos para usarla dinámicamente.
    if not inspect(db.engine).has_table(table_name):
        return None
    metadata = MetaData()
    return Table(table_name, metadata, autoload_with=db.engine)


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


def _build_media_payload(table: Table, *, mascota_id: int, rel_file_path: str, filename: str):
    # Prepara los datos mínimos para guardar un archivo de mascota en la base de datos.
    payload: dict[str, object] = {}

    mascota_col = _find_col(table, ["mascota_id", "id_mascota"])
    if mascota_col is not None:
        payload[mascota_col.name] = mascota_id

    file_col = _find_col(
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

    name_col = _find_col(table, ["nombre_archivo", "nombre", "titulo"])
    if name_col is not None:
        payload[name_col.name] = filename

    date_col = _find_col(table, ["fecha_subida", "fecha_registro", "fecha_creacion", "created_at"])
    if date_col is not None:
        payload[date_col.name] = datetime.now()

    required_cols = _required_columns_without_default(table)
    unknown_required = [c for c in required_cols if c not in payload and c not in ("id",)]
    if unknown_required:
        raise ValueError(
            "No se pudo guardar el archivo porque faltan columnas requeridas: "
            + ", ".join(unknown_required)
        )

    return payload


def _media_rows(table: Table | None, *, mascota_id: int):
    # Obtiene los archivos multimedia registrados para una mascota.
    if table is None:
        return []

    id_col = _find_col(table, ["id"])
    mascota_col = _find_col(table, ["mascota_id", "id_mascota"])
    file_col = _find_col(
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
    name_col = _find_col(table, ["nombre_archivo", "nombre", "titulo"])
    date_col = _find_col(table, ["fecha_subida", "fecha_registro", "fecha_creacion", "created_at"])

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


# --- RUTAS DE MASCOTAS ---
@mascotas_bp.get("/mascotas")
def mascotas_index():
    # Muestra el listado general de mascotas.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    client_redirect = _redirect_client_to_portal(me)
    if client_redirect:
        return client_redirect

    if not _allowed(me, "hu014"):
        return render_template("acceso_denegado.html", me=me)

    estado = (request.args.get("estado") or "").strip().lower()
    orden = (request.args.get("orden") or "asc").strip().lower()

    q = _build_mascotas_query(me)

    if estado in {"activa", "inactiva"}:
        q = q.filter(Mascota.estado == estado)

    if orden == "desc":
        q = q.order_by(Mascota.fecha_registro.desc(), Mascota.id.desc())
    else:
        q = q.order_by(Mascota.fecha_registro.asc(), Mascota.id.asc())

    rows = q.all()

    return render_template(
        "mascotas_list.html",
        me=me,
        active_nav="mascotas",
        mascotas_rows=rows,
        filters={"estado": estado, "orden": orden},
        can_create=_allowed(me, "hu011"),
        can_edit=_allowed(me, "hu012"),
        can_inactivate=_allowed(me, "hu013"),
        can_link_owner=_allowed(me, "hu015"),
        can_behavior=_allowed(me, "hu017"),
        can_multimedia=_allowed(me, "hu016"),
    )


@mascotas_bp.route("/mascotas/nueva", methods=["GET", "POST"])
def mascotas_new():
    # Registra una nueva mascota en el sistema.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    client_redirect = _redirect_client_to_portal(me)
    if client_redirect:
        return client_redirect

    if not _allowed(me, "hu011"):
        return render_template("acceso_denegado.html", me=me)

    clientes = _get_clientes_activos()
    role = _role_name(me)
    me_id = _parse_int(me.get("id"))

    if request.method == "GET":
        form_data = {
            "nombre": "",
            "fecha_nacimiento": "",
            "edad": "",
            "peso": "",
            "raza": "",
            "especie": "",
            "sexo": "",
            "datos_adicionales": "",
            "dueno_id": str(me_id or "") if role == ROLE_CLIENTE else "",
        }
        return render_template(
            "mascota_form.html",
            me=me,
            active_nav="mascotas",
            mode="create",
            form_data=form_data,
            clientes=clientes,
            only_self_owner=(role == ROLE_CLIENTE),
            me_id=me_id,
        )

    errors, payload = _validate_pet_form(request.form)

    if role == ROLE_CLIENTE and me_id is not None:
        payload["dueno_id"] = me_id

    form_data = {
        "nombre": request.form.get("nombre") or "",
        "fecha_nacimiento": request.form.get("fecha_nacimiento") or "",
        "edad": request.form.get("edad") or "",
        "peso": request.form.get("peso") or "",
        "raza": request.form.get("raza") or "",
        "especie": request.form.get("especie") or "",
        "sexo": request.form.get("sexo") or "",
        "datos_adicionales": request.form.get("datos_adicionales") or "",
        "dueno_id": str(payload.get("dueno_id") or ""),
    }

    if errors:
        for err in errors:
            flash(err, "error")
        return render_template(
            "mascota_form.html",
            me=me,
            active_nav="mascotas",
            mode="create",
            form_data=form_data,
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
    return redirect(url_for("mascotas.mascotas_index"))


@mascotas_bp.route("/mascotas/<int:mascota_id>/editar", methods=["GET", "POST"])
def mascotas_edit(mascota_id: int):
    # Actualiza la información de una mascota existente.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    client_redirect = _redirect_client_to_portal(me)
    if client_redirect:
        return client_redirect

    if not _allowed(me, "hu012"):
        return render_template("acceso_denegado.html", me=me)

    mascota = db.session.get(Mascota, mascota_id)
    if not mascota:
        flash("La mascota no existe.", "error")
        return redirect(url_for("mascotas.mascotas_index"))

    if not _user_can_view_pet(me, mascota):
        return render_template("acceso_denegado.html", me=me)

    role = _role_name(me)
    me_id = _parse_int(me.get("id"))
    clientes = _get_clientes_activos()

    if request.method == "GET":
        form_data = {
            "nombre": mascota.nombre or "",
            "fecha_nacimiento": mascota.fecha_nacimiento.isoformat() if mascota.fecha_nacimiento else "",
            "edad": "",
            "peso": str(mascota.peso or ""),
            "raza": mascota.raza or "",
            "especie": mascota.especie or "",
            "sexo": mascota.sexo or "",
            "datos_adicionales": mascota.datos_adicionales or "",
            "dueno_id": str(mascota.dueno_id or ""),
        }

        return render_template(
            "mascota_form.html",
            me=me,
            active_nav="mascotas",
            mode="edit",
            mascota_id=mascota.id,
            form_data=form_data,
            clientes=clientes,
            only_self_owner=(role == ROLE_CLIENTE),
            me_id=me_id,
        )

    errors, payload = _validate_pet_form(request.form, for_update=True)

    if role == ROLE_CLIENTE and me_id is not None:
        payload["dueno_id"] = me_id

    form_data = {
        "nombre": request.form.get("nombre") or "",
        "fecha_nacimiento": request.form.get("fecha_nacimiento") or "",
        "edad": request.form.get("edad") or "",
        "peso": request.form.get("peso") or "",
        "raza": request.form.get("raza") or "",
        "especie": request.form.get("especie") or "",
        "sexo": request.form.get("sexo") or "",
        "datos_adicionales": request.form.get("datos_adicionales") or "",
        "dueno_id": str(payload.get("dueno_id") or ""),
    }

    if errors:
        for err in errors:
            flash(err, "error")
        return render_template(
            "mascota_form.html",
            me=me,
            active_nav="mascotas",
            mode="edit",
            mascota_id=mascota.id,
            form_data=form_data,
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
    return redirect(url_for("mascotas.mascotas_index"))


@mascotas_bp.route("/mascotas/<int:mascota_id>/inactivar", methods=["GET", "POST"])
def mascotas_inactivar(mascota_id: int):
    # Inactiva una mascota y guarda la razón indicada.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    client_redirect = _redirect_client_to_portal(me)
    if client_redirect:
        return client_redirect

    if not _allowed(me, "hu013"):
        return render_template("acceso_denegado.html", me=me)

    mascota = db.session.get(Mascota, mascota_id)
    if not mascota:
        flash("La mascota no existe.", "error")
        return redirect(url_for("mascotas.mascotas_index"))

    if not _user_can_view_pet(me, mascota):
        return render_template("acceso_denegado.html", me=me)

    if request.method == "GET":
        return render_template(
            "mascota_inactivar.html",
            me=me,
            active_nav="mascotas",
            mascota=mascota,
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
            "mascota_inactivar.html",
            me=me,
            active_nav="mascotas",
            mascota=mascota,
        )

    mascota.estado = "inactiva"
    mascota.razon_inactivacion = razon
    db.session.commit()

    flash("Mascota inactivada correctamente.", "success")
    return redirect(url_for("mascotas.mascotas_index"))


@mascotas_bp.route("/mascotas/<int:mascota_id>/vincular", methods=["GET", "POST"])
def mascotas_vincular_dueno(mascota_id: int):
    # Reasigna el dueño de una mascota.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    client_redirect = _redirect_client_to_portal(me)
    if client_redirect:
        return client_redirect

    if not _allowed(me, "hu015"):
        return render_template("acceso_denegado.html", me=me)

    mascota = db.session.get(Mascota, mascota_id)
    if not mascota:
        flash("La mascota no existe.", "error")
        return redirect(url_for("mascotas.mascotas_index"))

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

    nuevo_dueno_id = _parse_int(request.form.get("dueno_id"))
    dueno = db.session.get(Usuario, nuevo_dueno_id) if nuevo_dueno_id else None

    errors = []
    if not nuevo_dueno_id:
        errors.append("Debes seleccionar un dueño.")
    elif not _is_active_client(dueno):
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
    return redirect(url_for("mascotas.mascotas_index"))


@mascotas_bp.route("/mascotas/<int:mascota_id>/comportamiento", methods=["GET", "POST"])
def mascotas_comportamiento(mascota_id: int):
    # Guarda observaciones de comportamiento para una mascota.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    client_redirect = _redirect_client_to_portal(me)
    if client_redirect:
        return client_redirect

    if not _allowed(me, "hu017"):
        return render_template("acceso_denegado.html", me=me)

    mascota = db.session.get(Mascota, mascota_id)
    if not mascota:
        flash("La mascota no existe.", "error")
        return redirect(url_for("mascotas.mascotas_index"))

    if not _user_can_view_pet(me, mascota):
        return render_template("acceso_denegado.html", me=me)

    if mascota.estado != "activa":
        flash("Solo se puede registrar comportamiento para mascotas activas.", "error")
        return redirect(url_for("mascotas.mascotas_historial", mascota_id=mascota.id))

    if request.method == "GET":
        return render_template(
            "mascota_comportamiento.html",
            me=me,
            active_nav="mascotas",
            mascota=mascota,
            comportamiento=mascota.comportamiento or "",
        )

    comportamiento = (request.form.get("comportamiento") or "").strip()
    if not comportamiento:
        flash("El comportamiento es obligatorio.", "error")
        return render_template(
            "mascota_comportamiento.html",
            me=me,
            active_nav="mascotas",
            mascota=mascota,
            comportamiento="",
        )

    mascota.comportamiento = comportamiento
    db.session.commit()

    flash("Comportamiento guardado correctamente.", "success")
    return redirect(url_for("mascotas.mascotas_historial", mascota_id=mascota.id))


@mascotas_bp.route("/mascotas/<int:mascota_id>/multimedia", methods=["GET", "POST"])
def mascotas_multimedia(mascota_id: int):
    # Permite subir y consultar archivos multimedia de una mascota.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    client_redirect = _redirect_client_to_portal(me)
    if client_redirect:
        return client_redirect

    if not _allowed(me, "hu016"):
        return render_template("acceso_denegado.html", me=me)

    mascota = db.session.get(Mascota, mascota_id)
    if not mascota:
        flash("La mascota no existe.", "error")
        return redirect(url_for("mascotas.mascotas_index"))

    if not _user_can_view_pet(me, mascota):
        return render_template("acceso_denegado.html", me=me)

    fotos_table = _reflect_table("fotos_mascota")
    docs_table = _reflect_table("documentos_mascota")

    if request.method == "POST":
        uploaded = request.files.get("archivo")
        if not uploaded or not uploaded.filename:
            flash("Debes seleccionar un archivo.", "error")
            return redirect(url_for("mascotas.mascotas_multimedia", mascota_id=mascota.id))

        # Validamos el archivo recibido antes de guardarlo.
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

        # Guardamos el archivo en la carpeta correspondiente de la mascota.
        upload_dir = os.path.join(current_app.root_path, "static", "uploads", "mascotas", str(mascota.id))
        os.makedirs(upload_dir, exist_ok=True)

        token = secrets.token_hex(6)
        new_name = f"{token}_{filename}"
        abs_path = os.path.join(upload_dir, new_name)
        rel_path = os.path.join("uploads", "mascotas", str(mascota.id), new_name).replace("\\", "/")

        uploaded.save(abs_path)

        try:
            # Registramos el archivo en la base de datos despues de guardarlo.
            payload = _build_media_payload(
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

    fotos = _media_rows(fotos_table, mascota_id=mascota.id)
    documentos = _media_rows(docs_table, mascota_id=mascota.id)

    return render_template(
        "mascota_multimedia.html",
        me=me,
        active_nav="mascotas",
        mascota=mascota,
        fotos=fotos,
        documentos=documentos,
        fotos_table_exists=fotos_table is not None,
        docs_table_exists=docs_table is not None,
    )


@mascotas_bp.get("/mascotas/<int:mascota_id>/historial")
def mascotas_historial(mascota_id: int):
    # Muestra el historial general de una mascota.
    r = _require_login_or_redirect()
    if r:
        return r

    me = _get_me_or_logout()
    if not me:
        return _redirect_to_login()

    client_redirect = _redirect_client_to_portal(me)
    if client_redirect:
        return client_redirect

    if not _allowed(me, "hu014"):
        return render_template("acceso_denegado.html", me=me)

    dueno = aliased(Usuario)

    mascota_row = (
        db.session.query(Mascota, dueno.nombre.label("dueno_nombre"), dueno.correo.label("dueno_correo"))
        .join(dueno, Mascota.dueno_id == dueno.id)
        .filter(Mascota.id == mascota_id)
        .first()
    )

    if not mascota_row:
        flash("La mascota no existe.", "error")
        return redirect(url_for("mascotas.mascotas_index"))

    mascota = mascota_row[0]
    if not _user_can_view_pet(me, mascota):
        return render_template("acceso_denegado.html", me=me)

    cliente = aliased(Usuario)
    veterinario = aliased(Usuario)

    citas_rows = (
        db.session.query(
            Cita,
            cliente.nombre.label("cliente_nombre"),
            veterinario.nombre.label("veterinario_nombre"),
        )
        .join(cliente, Cita.cliente_id == cliente.id)
        .join(veterinario, Cita.veterinario_id == veterinario.id)
        .filter(Cita.mascota_id == mascota.id)
        .order_by(Cita.fecha_hora.asc(), Cita.id.asc())
        .all()
    )

    return render_template(
        "mascota_historial.html",
        me=me,
        active_nav="mascotas",
        mascota=mascota,
        dueno_nombre=mascota_row.dueno_nombre,
        dueno_correo=mascota_row.dueno_correo,
        citas_rows=citas_rows,
        can_behavior=_allowed(me, "hu017"),
        can_multimedia=_allowed(me, "hu016"),
    )
