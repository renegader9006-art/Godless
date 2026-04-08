from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_AUTH_DB = Path('.seo_data/auth/users.db')
USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9_.-]{3,32}$')
CYRILLIC_PATTERN = re.compile(r'[А-Яа-яЁё]')
EMAIL_PATTERN = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
PBKDF2_ITERATIONS = 120_000


def init_auth_db(path: str | Path = DEFAULT_AUTH_DB) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            '''
        )
        _ensure_users_columns(conn)
        conn.commit()


def register_user(
    username: str,
    password: str,
    path: str | Path = DEFAULT_AUTH_DB,
    email: str = "",
) -> tuple[bool, str]:
    normalized = _normalize_username(username)
    normalized_email = _normalize_email(email)
    valid, message = _validate_credentials(normalized, password)
    if not valid:
        return False, message
    if normalized_email and not EMAIL_PATTERN.fullmatch(normalized_email):
        return False, 'Некорректный email.'

    db_path = Path(path)
    init_auth_db(db_path)
    password_hash = _hash_password(password)
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        with sqlite3.connect(db_path) as conn:
            if normalized_email:
                existing_email = conn.execute(
                    'SELECT username FROM users WHERE lower(email) = lower(?)',
                    (normalized_email,),
                ).fetchone()
                if existing_email:
                    return False, 'Этот email уже используется.'
            conn.execute(
                'INSERT INTO users (username, password_hash, created_at, email) VALUES (?, ?, ?, ?)',
                (normalized, password_hash, created_at, normalized_email),
            )
            conn.commit()
        return True, 'Регистрация успешна.'
    except sqlite3.IntegrityError:
        return False, 'Пользователь уже существует.'


def authenticate_user(
    username: str,
    password: str,
    path: str | Path = DEFAULT_AUTH_DB,
) -> tuple[bool, str]:
    normalized = _normalize_username(username)
    if not normalized:
        return False, 'Введите логин.'
    if not password:
        return False, 'Введите пароль.'

    db_path = Path(path)
    init_auth_db(db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            '''
            SELECT username, password_hash
            FROM users
            WHERE lower(username) = lower(?)
               OR lower(email) = lower(?)
            ''',
            (normalized, normalized),
        ).fetchone()

    if not row:
        return False, 'Пользователь не найден.'

    if _verify_password(password, str(row[1])):
        return True, 'Вход выполнен.'
    return False, 'Неверный пароль.'


def resolve_login_username(
    login: str,
    path: str | Path = DEFAULT_AUTH_DB,
) -> str | None:
    normalized = _normalize_username(login)
    if not normalized:
        return None
    db_path = Path(path)
    init_auth_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            '''
            SELECT username
            FROM users
            WHERE lower(username) = lower(?)
               OR lower(email) = lower(?)
            ''',
            (normalized, normalized),
        ).fetchone()
    if not row:
        return None
    return str(row[0])


def get_user_profile(
    username: str,
    path: str | Path = DEFAULT_AUTH_DB,
) -> dict[str, str] | None:
    normalized = _normalize_username(username)
    if not normalized:
        return None
    db_path = Path(path)
    init_auth_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            'SELECT username, email, created_at FROM users WHERE username = ?',
            (normalized,),
        ).fetchone()
    if not row:
        return None
    return {
        'username': str(row[0]),
        'email': str(row[1] or ''),
        'created_at': str(row[2]),
    }


def update_user_email(
    username: str,
    new_email: str,
    path: str | Path = DEFAULT_AUTH_DB,
) -> tuple[bool, str]:
    normalized = _normalize_username(username)
    if not normalized:
        return False, 'Пользователь не найден.'
    email = _normalize_email(new_email)
    if email and not EMAIL_PATTERN.fullmatch(email):
        return False, 'Некорректный email.'

    db_path = Path(path)
    init_auth_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            'SELECT username FROM users WHERE username = ?',
            (normalized,),
        ).fetchone()
        if not row:
            return False, 'Пользователь не найден.'

        if email:
            existing = conn.execute(
                'SELECT username FROM users WHERE lower(email) = lower(?) AND username != ?',
                (email, normalized),
            ).fetchone()
            if existing:
                return False, 'Этот email уже используется.'

        conn.execute(
            'UPDATE users SET email = ? WHERE username = ?',
            (email, normalized),
        )
        conn.commit()
    return True, 'Email обновлен.'


def change_user_password(
    username: str,
    current_password: str,
    new_password: str,
    path: str | Path = DEFAULT_AUTH_DB,
) -> tuple[bool, str]:
    normalized = _normalize_username(username)
    if not normalized:
        return False, 'Пользователь не найден.'
    if not current_password:
        return False, 'Введите текущий пароль.'
    valid, message = _validate_credentials(normalized, new_password)
    if not valid:
        return False, message

    db_path = Path(path)
    init_auth_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            'SELECT password_hash FROM users WHERE username = ?',
            (normalized,),
        ).fetchone()
        if not row:
            return False, 'Пользователь не найден.'
        if not _verify_password(current_password, str(row[0])):
            return False, 'Неверный текущий пароль.'

        conn.execute(
            'UPDATE users SET password_hash = ? WHERE username = ?',
            (_hash_password(new_password), normalized),
        )
        conn.commit()
    return True, 'Пароль обновлен.'


def _normalize_username(username: str) -> str:
    return (username or '').strip()


def _normalize_email(email: str) -> str:
    return (email or '').strip().lower()


def _validate_credentials(username: str, password: str) -> tuple[bool, str]:
    if not username:
        return False, 'Введите логин.'
    if not USERNAME_PATTERN.fullmatch(username):
        return False, 'Логин: 3-32 символа, латиница/цифры/._-'
    if len(password) < 8:
        return False, 'Пароль должен быть минимум 8 символов.'
    if CYRILLIC_PATTERN.search(password):
        return False, 'Пароль нельзя писать на русском. Используйте латиницу.'
    if not re.search(r'[A-Z]', password):
        return False, 'Пароль должен содержать хотя бы одну заглавную букву (A-Z).'
    return True, ''


def _ensure_users_columns(conn: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "email" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''")


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        PBKDF2_ITERATIONS,
    )
    key_hex = key.hex()
    return f'pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${key_hex}'


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iterations_raw, salt, key_hex = encoded.split('$', 3)
        if algo != 'pbkdf2_sha256':
            return False
        iterations = int(iterations_raw)
    except ValueError:
        return False

    candidate = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        iterations,
    ).hex()
    return hmac.compare_digest(candidate, key_hex)
