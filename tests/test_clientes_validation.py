"""Módulo de test clientes validation."""

import unittest
from unittest.mock import patch

from app.routes import clientes


class FakeQuery:
    """Clase para fake query."""
    def __init__(self, duplicate_result=None):
        """Función para init."""
        self.duplicate_result = duplicate_result

    def filter(self, *args, **kwargs):
        """Función para filter."""
        return self

    def first(self):
        """Función para first."""
        return self.duplicate_result


class FakeSession:
    """Clase para fake session."""
    def __init__(self, duplicate_result=None):
        """Función para init."""
        self.duplicate_result = duplicate_result

    def query(self, model):
        """Función para query."""
        return FakeQuery(self.duplicate_result)


class ClienteFormValidationTests(unittest.TestCase):
    """Clase para cliente form validation tests."""
    def setUp(self):
        """Función para set up."""
        self.base_payload = {
            "nombres": "Carlos",
            "apellido_paterno": "Perez",
            "apellido_materno": "Salgado",
            "calle": "Av. Central",
            "numero": "10",
            "colonia": "Centro",
            "codigo_postal": "55000",
            "estado": "Estado de Mexico",
            "entidad": "Ecatepec",
            "telefono": "5512345678",
            "correo": "carlos@correo.com",
            "contrasena": "ClaveSegura123!",
            "fuente_captacion": "recomendacion",
        }

    def _validate(self, overrides=None):
        """Función para validate."""
        payload = dict(self.base_payload)
        payload.update(overrides or {})
        fake_session = FakeSession()
        with patch.object(clientes.db, "session", fake_session):
            return clientes._validar_formulario_cliente(payload)

    def test_rejects_numbers_in_first_name(self):
        """Función para test rejects numbers in first name."""
        _, errores_campo, _ = self._validate({"nombres": "Carlos123"})
        self.assertEqual(errores_campo["nombres"], "El nombre no puede contener números.")

    def test_rejects_numbers_in_last_names(self):
        """Función para test rejects numbers in last names."""
        _, errores_campo, _ = self._validate({"apellido_paterno": "Perez9", "apellido_materno": "Salgado7"})
        self.assertEqual(
            errores_campo["apellido_paterno"],
            "El apellido paterno no puede contener números.",
        )
        self.assertEqual(
            errores_campo["apellido_materno"],
            "El apellido materno no puede contener números.",
        )

    def test_accepts_optional_last_names_when_they_contain_only_letters(self):
        """Función para test accepts optional last names when they contain only letters."""
        _, errores_campo, _ = self._validate({"apellido_paterno": "", "apellido_materno": ""})
        self.assertNotIn("apellido_paterno", errores_campo)
        self.assertNotIn("apellido_materno", errores_campo)


if __name__ == "__main__":
    unittest.main()
