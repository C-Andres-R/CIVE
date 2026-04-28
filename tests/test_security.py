"""Módulo de test security."""

import unittest
from datetime import datetime, timedelta, timezone

from flask import Flask, session

from app.security import (
    CSRF_SESSION_KEY,
    LAST_ACTIVITY_SESSION_KEY,
    generate_csrf_token,
    is_session_expired,
    mark_session_authenticated,
    rotate_csrf_token,
    validate_csrf_request,
)


class SecurityHelpersTests(unittest.TestCase):
    """Clase para security helpers tests."""
    def setUp(self):
        """Función para set up."""
        self.app = Flask(__name__)
        self.app.config["SECRET_KEY"] = "test-secret"

    def test_generate_csrf_token_persists_in_session(self):
        """Función para test generate csrf token persists in session."""
        with self.app.test_request_context("/"):
            token = generate_csrf_token()
            self.assertEqual(session[CSRF_SESSION_KEY], token)
            self.assertEqual(generate_csrf_token(), token)

    def test_rotate_csrf_token_replaces_previous_value(self):
        """Función para test rotate csrf token replaces previous value."""
        with self.app.test_request_context("/"):
            first = generate_csrf_token()
            second = rotate_csrf_token()
            self.assertNotEqual(first, second)
            self.assertEqual(session[CSRF_SESSION_KEY], second)

    def test_validate_csrf_request_accepts_form_token(self):
        """Función para test validate csrf request accepts form token."""
        with self.app.test_request_context("/", method="POST", data={"_csrf_token": "token-ok"}):
            session[CSRF_SESSION_KEY] = "token-ok"
            self.assertTrue(validate_csrf_request())

    def test_validate_csrf_request_accepts_header_token(self):
        """Función para test validate csrf request accepts header token."""
        with self.app.test_request_context("/", method="POST", headers={"X-CSRF-Token": "token-ok"}):
            session[CSRF_SESSION_KEY] = "token-ok"
            self.assertTrue(validate_csrf_request())

    def test_validate_csrf_request_rejects_missing_or_invalid_tokens(self):
        """Función para test validate csrf request rejects missing or invalid tokens."""
        with self.app.test_request_context("/", method="POST", data={"_csrf_token": "otro"}):
            session[CSRF_SESSION_KEY] = "token-ok"
            self.assertFalse(validate_csrf_request())

        with self.app.test_request_context("/", method="POST"):
            session[CSRF_SESSION_KEY] = "token-ok"
            self.assertFalse(validate_csrf_request())

    def test_mark_session_authenticated_sets_timeout_tracking(self):
        """Función para test mark session authenticated sets timeout tracking."""
        with self.app.test_request_context("/"):
            mark_session_authenticated()
            self.assertTrue(session.permanent)
            self.assertIn(LAST_ACTIVITY_SESSION_KEY, session)

    def test_is_session_expired_uses_last_activity_timestamp(self):
        """Función para test is session expired uses last activity timestamp."""
        with self.app.test_request_context("/"):
            session[LAST_ACTIVITY_SESSION_KEY] = (
                datetime.now(timezone.utc) - timedelta(seconds=901)
            ).isoformat()
            self.assertTrue(is_session_expired(900))

        with self.app.test_request_context("/"):
            session[LAST_ACTIVITY_SESSION_KEY] = datetime.now(timezone.utc).isoformat()
            self.assertFalse(is_session_expired(900))


if __name__ == "__main__":
    unittest.main()
