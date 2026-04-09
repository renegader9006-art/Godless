from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

DEFAULT_BILLING_DB = Path(".seo_data/billing/subscriptions.db")

ACTION_URL_AUDIT = "url_audit"
ACTION_TEXT_AUDIT = "text_audit"
ACTION_AI = "ai_generation"
ACTION_EXPORT = "export_download"
ACTION_COMPETITORS = "competitor_benchmark"

PAYMENT_PROVIDER_DEMO = "demo"
PAYMENT_PROVIDER_LINKS = "payment_links"
PAYMENT_PROVIDERS = (PAYMENT_PROVIDER_DEMO, PAYMENT_PROVIDER_LINKS)
PAYMENT_LINK_ENV_BY_PLAN: dict[str, tuple[str, ...]] = {
    "starter": ("PAYMENT_LINK_STARTER", "PAYMENT_LINK_START"),
    "growth": ("PAYMENT_LINK_GROWTH",),
    "pro": ("PAYMENT_LINK_PRO",),
    "agency": ("PAYMENT_LINK_AGENCY", "PAYMENT_LINK_BUSINESS", "PAYMENT_LINK_SCALE"),
}


@dataclass(frozen=True)
class Plan:
    plan_id: str
    title: str
    monthly_price_rub: int
    price_rub_display: str
    price_usdt_display: str
    description: str
    limits: dict[str, int]
    features: list[str]


PLANS: dict[str, Plan] = {
    "starter": Plan(
        plan_id="starter",
        title="Starter",
        monthly_price_rub=2490,
        price_rub_display="2 490–3 490 ₽ / мес",
        price_usdt_display="29–39 USDT / мес",
        description=(
            "Быстрый старт для 1 проекта: запускайте аудит, собирайте понятный план правок "
            "и показывайте клиенту измеримый прогресс."
        ),
        limits={
            ACTION_URL_AUDIT: 80,
            ACTION_TEXT_AUDIT: 150,
            ACTION_AI: 80,
            ACTION_EXPORT: 250,
            ACTION_COMPETITORS: 40,
        },
        features=[
            "Базовый SEO-аудит страниц и контента",
            "Контент-календарь и простой план публикаций",
            "Поддержка 1-2 соцсетей и отложенные публикации",
            "Экспорт отчетов PDF/JSON/MD для клиента",
        ],
    ),
    "growth": Plan(
        plan_id="growth",
        title="Growth",
        monthly_price_rub=6990,
        price_rub_display="6 990–8 990 ₽ / мес",
        price_usdt_display="79–99 USDT / мес",
        description=(
            "Основной рабочий тариф для малого бизнеса: больше лимитов, автоматизация контента "
            "и регулярная отчетность без ручной рутины."
        ),
        limits={
            ACTION_URL_AUDIT: 300,
            ACTION_TEXT_AUDIT: 600,
            ACTION_AI: 450,
            ACTION_EXPORT: 1500,
            ACTION_COMPETITORS: 300,
        },
        features=[
            "Все из Starter",
            "Автопостинг и AI-перепаковка контента",
            "Еженедельные отчеты и расширенная аналитика",
            "Больше лимитов по страницам, аудитам и публикациям",
        ],
    ),
    "pro": Plan(
        plan_id="pro",
        title="Pro",
        monthly_price_rub=14900,
        price_rub_display="14 900–19 900 ₽ / мес",
        price_usdt_display="169–229 USDT / мес",
        description=(
            "Для агентств и продвинутых команд: несколько брендов, white-label, "
            "история изменений и масштабируемая аналитика."
        ),
        limits={
            ACTION_URL_AUDIT: 1200,
            ACTION_TEXT_AUDIT: 2500,
            ACTION_AI: 1800,
            ACTION_EXPORT: 5000,
            ACTION_COMPETITORS: 1200,
        },
        features=[
            "Все из Growth",
            "White-label отчеты и история изменений",
            "Прогнозирование через MiroFish",
            "Командный доступ и расширенная аналитика под несколько брендов",
        ],
    ),
    "agency": Plan(
        plan_id="agency",
        title="Agency / Business",
        monthly_price_rub=39900,
        price_rub_display="39 900–69 900 ₽ / мес",
        price_usdt_display="449–799 USDT / мес",
        description=(
            "Enterprise-режим для агентств и крупных команд: клиентские кабинеты, API, "
            "кастомные лимиты и приоритетная поддержка."
        ),
        limits={
            ACTION_URL_AUDIT: -1,
            ACTION_TEXT_AUDIT: -1,
            ACTION_AI: -1,
            ACTION_EXPORT: -1,
            ACTION_COMPETITORS: -1,
        },
        features=[
            "Клиентские кабинеты и роли доступа",
            "API, webhooks и кастомные лимиты",
            "Приоритетная поддержка и enterprise-интеграции",
            "Безлимитная операционная работа команды",
        ],
    ),
}


def current_period_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_provider(provider: str | None) -> str:
    raw = (provider or os.getenv("PAYMENT_PROVIDER", PAYMENT_PROVIDER_DEMO)).strip().lower()
    return raw if raw in PAYMENT_PROVIDERS else PAYMENT_PROVIDER_DEMO


def payment_provider_status(provider: str | None = None) -> dict[str, Any]:
    selected = _normalize_provider(provider)
    links: dict[str, str] = {}
    if selected == PAYMENT_PROVIDER_LINKS:
        for plan_id, env_names in PAYMENT_LINK_ENV_BY_PLAN.items():
            links[plan_id] = _resolve_plan_payment_link(env_names)
        missing = [plan_id for plan_id, url in links.items() if not url]
        configured = not missing
        if configured:
            message = "Платежные ссылки подключены."
        else:
            names = ", ".join("/".join(PAYMENT_LINK_ENV_BY_PLAN[item]) for item in missing)
            message = f"Не хватает env-переменных для оплаты: {names}"
    else:
        configured = True
        message = "Демо-режим оплаты: заказ можно подтвердить вручную в интерфейсе."

    manual_confirmation = os.getenv("PAYMENT_ALLOW_MANUAL_CONFIRM", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    return {
        "provider": selected,
        "configured": configured,
        "message": message,
        "links": links,
        "manual_confirmation": manual_confirmation,
    }


def _resolve_plan_payment_link(env_names: tuple[str, ...]) -> str:
    for env_name in env_names:
        value = os.getenv(env_name, "").strip()
        if value:
            return value
    return ""


def init_billing_db(path: str | Path = DEFAULT_BILLING_DB) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                username TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usage (
                username TEXT NOT NULL,
                period_key TEXT NOT NULL,
                action TEXT NOT NULL,
                used INTEGER NOT NULL,
                PRIMARY KEY (username, period_key, action)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checkout_orders (
                order_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                plan_id TEXT NOT NULL,
                amount_rub INTEGER NOT NULL,
                provider TEXT NOT NULL,
                status TEXT NOT NULL,
                checkout_url TEXT NOT NULL,
                payment_ref TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def get_plan(plan_id: str) -> Plan:
    return PLANS.get(plan_id, PLANS["starter"])


def set_subscription(
    username: str,
    plan_id: str,
    status: str = "active",
    path: str | Path = DEFAULT_BILLING_DB,
) -> None:
    if plan_id not in PLANS:
        raise ValueError(f"Unknown plan: {plan_id}")
    init_billing_db(path)
    with sqlite3.connect(Path(path)) as conn:
        conn.execute(
            """
            INSERT INTO subscriptions (username, plan_id, status, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                plan_id = excluded.plan_id,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (username, plan_id, status, _now_iso()),
        )
        conn.commit()


def get_subscription(
    username: str,
    path: str | Path = DEFAULT_BILLING_DB,
) -> dict[str, Any] | None:
    init_billing_db(path)
    with sqlite3.connect(Path(path)) as conn:
        row = conn.execute(
            "SELECT plan_id, status, updated_at FROM subscriptions WHERE username = ?",
            (username,),
        ).fetchone()
    if not row:
        return None
    plan_id = str(row[0])
    status = str(row[1])
    updated_at = str(row[2])
    plan = get_plan(plan_id)
    return {
        "username": username,
        "plan_id": plan.plan_id,
        "plan_title": plan.title,
        "status": status,
        "updated_at": updated_at,
        "limits": plan.limits,
        "features": plan.features,
        "price_rub": plan.monthly_price_rub,
        "price_rub_display": plan.price_rub_display,
        "price_usdt_display": plan.price_usdt_display,
        "description": plan.description,
    }


def has_active_subscription(username: str, path: str | Path = DEFAULT_BILLING_DB) -> bool:
    subscription = get_subscription(username, path)
    return bool(subscription and subscription.get("status") == "active")


def create_checkout_order(
    username: str,
    plan_id: str,
    provider: str | None = None,
    path: str | Path = DEFAULT_BILLING_DB,
) -> tuple[bool, dict[str, Any] | str]:
    if not username:
        return False, "Пользователь не авторизован."
    if plan_id not in PLANS:
        return False, f"Неизвестный тариф: {plan_id}."

    status = payment_provider_status(provider)
    selected_provider = str(status["provider"])
    if selected_provider == PAYMENT_PROVIDER_LINKS and not bool(status["configured"]):
        return False, str(status["message"])

    plan = get_plan(plan_id)
    checkout_url = ""
    if selected_provider == PAYMENT_PROVIDER_LINKS:
        checkout_url = str(status["links"].get(plan_id, "")).strip()
        if not checkout_url:
            return False, "Ссылка оплаты для этого тарифа не настроена."

    order = {
        "order_id": f"ord_{uuid4().hex[:16]}",
        "username": username,
        "plan_id": plan_id,
        "amount_rub": plan.monthly_price_rub,
        "provider": selected_provider,
        "status": "pending",
        "checkout_url": checkout_url,
        "payment_ref": "",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    init_billing_db(path)
    with sqlite3.connect(Path(path)) as conn:
        conn.execute(
            """
            INSERT INTO checkout_orders (
                order_id, username, plan_id, amount_rub, provider, status,
                checkout_url, payment_ref, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order["order_id"],
                order["username"],
                order["plan_id"],
                order["amount_rub"],
                order["provider"],
                order["status"],
                order["checkout_url"],
                order["payment_ref"],
                order["created_at"],
                order["updated_at"],
            ),
        )
        conn.commit()
    return True, order


def list_checkout_orders(
    username: str,
    limit: int = 20,
    path: str | Path = DEFAULT_BILLING_DB,
) -> list[dict[str, Any]]:
    if not username:
        return []
    init_billing_db(path)
    safe_limit = max(1, min(int(limit), 200))
    with sqlite3.connect(Path(path)) as conn:
        rows = conn.execute(
            """
            SELECT order_id, username, plan_id, amount_rub, provider, status, checkout_url, payment_ref, created_at, updated_at
            FROM checkout_orders
            WHERE username = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (username, safe_limit),
        ).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "order_id": str(row[0]),
                "username": str(row[1]),
                "plan_id": str(row[2]),
                "amount_rub": int(row[3]),
                "provider": str(row[4]),
                "status": str(row[5]),
                "checkout_url": str(row[6]),
                "payment_ref": str(row[7]),
                "created_at": str(row[8]),
                "updated_at": str(row[9]),
            }
        )
    return result


def confirm_checkout_order(
    username: str,
    order_id: str,
    payment_ref: str = "manual",
    path: str | Path = DEFAULT_BILLING_DB,
) -> tuple[bool, str]:
    if not username:
        return False, "Пользователь не авторизован."
    if not order_id.strip():
        return False, "Order ID пустой."

    init_billing_db(path)
    with sqlite3.connect(Path(path)) as conn:
        row = conn.execute(
            "SELECT plan_id, status FROM checkout_orders WHERE order_id = ? AND username = ?",
            (order_id.strip(), username),
        ).fetchone()
        if not row:
            return False, "Заказ не найден."

        plan_id = str(row[0])
        status = str(row[1]).lower()
        if status == "paid":
            set_subscription(username, plan_id, status="active", path=path)
            return True, "Заказ уже был оплачен. Подписка активна."
        if status == "cancelled":
            return False, "Заказ отменен и не может быть оплачен."

        conn.execute(
            """
            UPDATE checkout_orders
            SET status = 'paid', payment_ref = ?, updated_at = ?
            WHERE order_id = ? AND username = ?
            """,
            (payment_ref.strip() or "manual", _now_iso(), order_id.strip(), username),
        )
        conn.commit()

    set_subscription(username, plan_id, status="active", path=path)
    return True, "Оплата подтверждена. Подписка активирована."


def cancel_checkout_order(
    username: str,
    order_id: str,
    path: str | Path = DEFAULT_BILLING_DB,
) -> tuple[bool, str]:
    if not username:
        return False, "Пользователь не авторизован."
    if not order_id.strip():
        return False, "Order ID пустой."

    init_billing_db(path)
    with sqlite3.connect(Path(path)) as conn:
        row = conn.execute(
            "SELECT status FROM checkout_orders WHERE order_id = ? AND username = ?",
            (order_id.strip(), username),
        ).fetchone()
        if not row:
            return False, "Заказ не найден."
        if str(row[0]).lower() == "paid":
            return False, "Оплаченный заказ нельзя отменить."

        conn.execute(
            """
            UPDATE checkout_orders
            SET status = 'cancelled', updated_at = ?
            WHERE order_id = ? AND username = ?
            """,
            (_now_iso(), order_id.strip(), username),
        )
        conn.commit()
    return True, "Заказ отменен."


def get_usage(
    username: str,
    action: str,
    period_key: str | None = None,
    path: str | Path = DEFAULT_BILLING_DB,
) -> int:
    init_billing_db(path)
    period = period_key or current_period_key()
    with sqlite3.connect(Path(path)) as conn:
        row = conn.execute(
            "SELECT used FROM usage WHERE username = ? AND period_key = ? AND action = ?",
            (username, period, action),
        ).fetchone()
    return int(row[0]) if row else 0


def check_and_consume(
    username: str,
    action: str,
    amount: int = 1,
    path: str | Path = DEFAULT_BILLING_DB,
) -> tuple[bool, str]:
    if not username:
        return False, "Пользователь не авторизован."
    if amount <= 0:
        return False, "Некорректное количество списаний: amount должен быть больше 0."

    init_billing_db(path)
    db_path = Path(path)
    period = current_period_key()

    try:
        with sqlite3.connect(db_path, timeout=10, isolation_level=None) as conn:
            conn.execute("BEGIN IMMEDIATE")

            subscription_row = conn.execute(
                "SELECT plan_id, status FROM subscriptions WHERE username = ?",
                (username,),
            ).fetchone()
            if not subscription_row:
                conn.execute("ROLLBACK")
                return False, "Нет активной подписки. Оформите тариф, чтобы продолжить."

            plan_id = str(subscription_row[0])
            status = str(subscription_row[1]).strip().lower()
            if status != "active":
                conn.execute("ROLLBACK")
                return False, "Нет активной подписки. Оформите тариф, чтобы продолжить."

            plan = get_plan(plan_id)
            if action not in plan.limits:
                conn.execute("ROLLBACK")
                return False, f"Действие '{action}' не поддерживается тарифом."

            limit = int(plan.limits[action])
            usage_row = conn.execute(
                "SELECT used FROM usage WHERE username = ? AND period_key = ? AND action = ?",
                (username, period, action),
            ).fetchone()
            used = max(0, int(usage_row[0])) if usage_row else 0
            new_used = used + amount

            if limit >= 0 and new_used > limit:
                conn.execute("ROLLBACK")
                return (
                    False,
                    f"Лимит исчерпан: {used}/{limit} для действия '{action}' в текущем месяце.",
                )

            conn.execute(
                """
                INSERT INTO usage (username, period_key, action, used)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(username, period_key, action) DO UPDATE SET
                    used = excluded.used
                """,
                (username, period, action, new_used),
            )
            conn.execute("COMMIT")
    except sqlite3.DatabaseError as error:
        return False, f"Ошибка учета лимитов: {error}"

    if limit < 0:
        return True, f"Использовано: {new_used} (безлимит)."
    return True, f"Использовано: {new_used}/{limit}."


def usage_snapshot(
    username: str,
    path: str | Path = DEFAULT_BILLING_DB,
) -> list[dict[str, Any]]:
    subscription = get_subscription(username, path)
    if not subscription:
        return []
    plan = get_plan(str(subscription["plan_id"]))
    rows: list[dict[str, Any]] = []
    for action, limit in plan.limits.items():
        used = get_usage(username, action, path=path)
        percent = 0.0
        if limit > 0:
            percent = round((used / limit) * 100, 2)
        rows.append(
                {
                    "action": action,
                    "used": used,
                    "limit": "∞" if limit < 0 else limit,
                    "percent": percent,
                }
            )
    return rows

