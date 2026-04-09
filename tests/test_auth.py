import unittest
from pathlib import Path
from uuid import uuid4

from seo_ai_analyzer.auth import (
    authenticate_user,
    create_persistent_login_token,
    init_auth_db,
    register_user,
    resolve_persistent_login_token,
    revoke_persistent_login_token,
)


class AuthTests(unittest.TestCase):
    def _db_path(self) -> Path:
        root = Path('tests/.tmp_auth')
        root.mkdir(parents=True, exist_ok=True)
        return root / f'{uuid4().hex}.db'

    def test_register_and_authenticate(self) -> None:
        db_path = self._db_path()
        init_auth_db(db_path)
        ok, _ = register_user('tester_01', 'Strongpass123', path=db_path)
        self.assertTrue(ok)

        ok, _ = authenticate_user('tester_01', 'Strongpass123', path=db_path)
        self.assertTrue(ok)

        ok, _ = authenticate_user('tester_01', 'wrong-pass', path=db_path)
        self.assertFalse(ok)

    def test_register_duplicate_user(self) -> None:
        db_path = self._db_path()
        register_user('tester_02', 'Strongpass123', path=db_path)
        ok, _ = register_user('tester_02', 'Strongpass123', path=db_path)
        self.assertFalse(ok)

    def test_username_and_password_validation(self) -> None:
        db_path = self._db_path()

        ok, _ = register_user('a', '123', path=db_path)
        self.assertFalse(ok)

        ok, _ = register_user('valid_user', 'Strongpass1', path=db_path)
        self.assertTrue(ok)

    def test_password_rejects_cyrillic_and_requires_uppercase(self) -> None:
        db_path = self._db_path()

        ok, msg = register_user('valid_user2', 'Пароль123', path=db_path)
        self.assertFalse(ok)
        self.assertIn('на русском', msg)

        ok, msg = register_user('valid_user3', 'lowercase123', path=db_path)
        self.assertFalse(ok)
        self.assertIn('заглавную', msg)

    def test_persistent_login_token_lifecycle(self) -> None:
        db_path = self._db_path()
        ok, _ = register_user('persist_user', 'StrongPass123', path=db_path)
        self.assertTrue(ok)

        token = create_persistent_login_token('persist_user', path=db_path)
        self.assertTrue(token)

        resolved = resolve_persistent_login_token(token, path=db_path)
        self.assertEqual(resolved, 'persist_user')

        revoke_persistent_login_token(token, path=db_path)
        resolved_after_revoke = resolve_persistent_login_token(token, path=db_path)
        self.assertIsNone(resolved_after_revoke)


if __name__ == '__main__':
    unittest.main()
