"""Utilidades de CSRF y control de vigencia de sesión."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from flask import request, session


CSRF_SESSION_KEY = "_csrf_token"
LAST_ACTIVITY_SESSION_KEY = "_last_activity"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def generate_csrf_token() -> str:
    """Genera o recupera el token CSRF almacenado en sesión."""
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
        session.modified = True
    return token


def validate_csrf_request() -> bool:
    """Compara el token enviado por el cliente contra el token guardado en sesión."""
    expected = session.get(CSRF_SESSION_KEY)
    provided = (
        request.headers.get("X-CSRF-Token")
        or request.form.get("_csrf_token")
        or request.headers.get("X-CSRFToken")
    )
    return bool(expected and provided and secrets.compare_digest(expected, provided))


def should_validate_csrf() -> bool:
    """Indica si la petición actual requiere validación CSRF por su método HTTP."""
    return request.method.upper() in UNSAFE_METHODS


def rotate_csrf_token() -> str:
    """Invalida el token previo y emite uno nuevo para la sesión activa."""
    session.pop(CSRF_SESSION_KEY, None)
    return generate_csrf_token()


def mark_session_authenticated() -> None:
    """Marca la sesión como persistente y registra la última actividad."""
    session.permanent = True
    touch_session_activity()


def touch_session_activity() -> None:
    """Actualiza la marca temporal usada para detectar inactividad."""
    session[LAST_ACTIVITY_SESSION_KEY] = _utcnow().isoformat()
    session.modified = True


def is_session_expired(timeout_seconds: int) -> bool:
    """Determina si la sesión excedió el tiempo máximo de inactividad permitido."""
    last_seen = session.get(LAST_ACTIVITY_SESSION_KEY)
    if not last_seen:
        return False

    try:
        last_seen_at = datetime.fromisoformat(last_seen)
    except ValueError:
        return True

    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)

    return _utcnow() - last_seen_at > timedelta(seconds=timeout_seconds)


def clear_authenticated_session() -> None:
    """Vacía por completo la sesión autenticada actual."""
    session.clear()
    session.modified = True


def _utcnow() -> datetime:
    """Obtiene la fecha actual en UTC para cálculos de sesión."""
    return datetime.now(timezone.utc)
