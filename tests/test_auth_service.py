"""Módulo de test auth service."""

import unittest

import bcrypt
from werkzeug.security import generate_password_hash

from app.auth.service import verify_password


class VerifyPasswordTests(unittest.TestCase):
    """Clase para verify password tests."""
    def test_accepts_werkzeug_hashes(self):
        """Función para test accepts werkzeug hashes."""
        stored_hash = generate_password_hash("ClaveSegura123!")
        self.assertTrue(verify_password("ClaveSegura123!", stored_hash))
        self.assertFalse(verify_password("OtraClave123!", stored_hash))

    def test_accepts_bcrypt_hashes(self):
        """Función para test accepts bcrypt hashes."""
        stored_hash = bcrypt.hashpw(b"ClaveSegura123!", bcrypt.gensalt()).decode("utf-8")
        self.assertTrue(verify_password("ClaveSegura123!", stored_hash))
        self.assertFalse(verify_password("OtraClave123!", stored_hash))

    def test_rejects_plaintext_password_storage(self):
        """Función para test rejects plaintext password storage."""
        self.assertFalse(verify_password("ClaveSegura123!", "ClaveSegura123!"))


if __name__ == "__main__":
    unittest.main()
