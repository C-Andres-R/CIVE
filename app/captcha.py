"""Utilidades para captcha simple basado en operaciones aritméticas."""

from __future__ import annotations

import random

from flask import session

CAPTCHA_SESSION_KEY = "simple_captcha_answers"


def _answers_map() -> dict[str, str]:
    """Obtiene el mapa de respuestas almacenado en sesión."""
    data = session.get(CAPTCHA_SESSION_KEY)
    return data if isinstance(data, dict) else {}


def build_captcha(scope: str) -> dict[str, str]:
    """Genera un captcha simple y guarda su respuesta en sesión."""
    left = random.randint(1, 9)
    right = random.randint(1, 9)
    answer = str(left + right)

    answers = _answers_map()
    answers[scope] = answer
    session[CAPTCHA_SESSION_KEY] = answers
    session.modified = True

    return {
        "scope": scope,
        "question": f"{left} + {right}",
        "answer": answer,
    }


def validate_captcha(scope: str, answer: str) -> bool:
    """Valida la respuesta del captcha para el alcance indicado."""
    answers = _answers_map()
    expected = (answers.get(scope) or "").strip()
    provided = (answer or "").strip()
    is_valid = bool(expected) and provided == expected

    if scope in answers:
        answers.pop(scope, None)
        session[CAPTCHA_SESSION_KEY] = answers
        session.modified = True

    return is_valid
