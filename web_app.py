from __future__ import annotations

import html
import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta

import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup

from seo_ai_analyzer.action_pack import build_action_pack, build_dev_tickets_markdown
from seo_ai_analyzer.ai_layer import (
    generate_ai_recommendations,
    generate_ai_recommendations_ollama,
    generate_improved_text_variants,
    generate_improved_text_variants_ollama,
)
from seo_ai_analyzer.analyzer import analyze_html, analyze_text_article
from seo_ai_analyzer.auth import (
    authenticate_user,
    change_user_password,
    create_persistent_login_token,
    get_user_profile,
    init_auth_db,
    register_user,
    resolve_persistent_login_token,
    resolve_login_username,
    revoke_persistent_login_token,
    update_user_email,
)
from seo_ai_analyzer.billing import (
    ACTION_AI,
    ACTION_COMPETITORS,
    ACTION_EXPORT,
    ACTION_TEXT_AUDIT,
    ACTION_URL_AUDIT,
    PAYMENT_PROVIDER_DEMO,
    PAYMENT_PROVIDER_LINKS,
    PLANS,
    cancel_checkout_order,
    check_and_consume,
    confirm_checkout_order,
    create_checkout_order,
    get_subscription,
    has_active_subscription,
    init_billing_db,
    list_checkout_orders,
    payment_provider_status,
    set_subscription,
    usage_snapshot,
)
from seo_ai_analyzer.competitive import benchmark_against_competitors, discover_competitors
from seo_ai_analyzer.fetcher import load_html_from_url
from seo_ai_analyzer.history import build_alerts, build_changelog, load_previous_snapshot, save_snapshot
from seo_ai_analyzer.integrations import (
    fetch_ga4_api_data,
    fetch_gsc_api_data,
    fetch_pagespeed_data,
    parse_ga4_csv,
    parse_gsc_csv,
)
from seo_ai_analyzer.models import AnalysisResult
from seo_ai_analyzer.query_audit import audit_queries
from seo_ai_analyzer.reporting import build_one_page_report, markdown_to_pdf_bytes

PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
PRIORITY_LABELS = {"HIGH": "Критично", "MEDIUM": "Важно", "LOW": "Желательно"}
AI_PROVIDERS = ("Без AI", "OpenAI", "Ollama (локально, бесплатно)")
BLOCKED_WITHOUT_SUBSCRIPTION = {"Новый аудит", "Результат", "Action Lab", "История", "AI Studio"}
PAGE_LABELS = {
    "Дашборд": "Дашборд",
    "Новый аудит": "Новый аудит",
    "Результат": "Результат",
    "Action Lab": "Action Lab",
    "История": "История",
    "AI Studio": "AI-помощник",
    "Тарифы": "Тарифы",
    "Профиль": "Профиль",
    "Настройки": "Настройки",
}
APP_PAGES = list(PAGE_LABELS.keys())
DASHBOARD_PAGE = APP_PAGES[0]
PROFILE_PAGE = APP_PAGES[7]
MENU_PAGES = [page for page in APP_PAGES if page != PROFILE_PAGE]

ACTION_LABELS = {
    ACTION_URL_AUDIT: "\u0410\u0443\u0434\u0438\u0442 URL",
    ACTION_TEXT_AUDIT: "\u0410\u0443\u0434\u0438\u0442 \u0442\u0435\u043a\u0441\u0442\u0430",
    ACTION_AI: "AI-\u0433\u0435\u043d\u0435\u0440\u0430\u0446\u0438\u044f",
    ACTION_EXPORT: "\u042d\u043a\u0441\u043f\u043e\u0440\u0442",
    ACTION_COMPETITORS: "\u0410\u043d\u0430\u043b\u0438\u0437 \u043a\u043e\u043d\u043a\u0443\u0440\u0435\u043d\u0442\u043e\u0432",
}


def parse_keywords(raw: str) -> list[str]:
    return [keyword.strip() for keyword in raw.split(",") if keyword.strip()]


def parse_multiline(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def sorted_issues(result: AnalysisResult) -> list:
    return sorted(result.issues, key=lambda issue: PRIORITY_ORDER.get(issue.priority, 9))


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_limit_value(limit: object) -> str:
    value = _to_int(limit, -1)
    return "∞" if value < 0 else str(value)


def _format_datetime_value(value: object) -> str:
    if value is None:
        return "—"
    raw = str(value).strip()
    if not raw:
        return "—"

    normalized = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%d.%m.%Y - %H:%M:%S")
    except ValueError:
        pass

    cleaned = raw.replace("T", " ")
    if "+" in cleaned:
        cleaned = cleaned.split("+", 1)[0]
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1]
    if "." in cleaned:
        cleaned = cleaned.split(".", 1)[0]
    cleaned = cleaned.strip()

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(cleaned, fmt)
            if fmt == "%Y-%m-%d":
                return dt.strftime("%d.%m.%Y")
            return dt.strftime("%d.%m.%Y - %H:%M:%S")
        except ValueError:
            continue

    return raw


def render_usage_table(usage: list[dict]) -> None:
    if not usage:
        st.caption("Данные по лимитам пока отсутствуют.")
        return

    rows: list[dict[str, object]] = []
    for row in usage:
        action = ACTION_LABELS.get(str(row.get("action", "")), str(row.get("action", "—")))
        used = _to_int(row.get("used"), 0)
        limit_text = _format_limit_value(row.get("limit"))
        percent = max(0.0, _to_float(row.get("percent"), 0.0))
        rows.append(
            {
                "Действие": action,
                "Использовано": used,
                "Лимит": limit_text,
                "Загрузка %": f"{percent:.1f}%",
            }
        )

    st.dataframe(rows, use_container_width=True, hide_index=True)


def _show_profile_notice() -> None:
    notice = st.session_state.pop("profile_notice", None)
    if not notice:
        return
    kind = str(notice.get("kind", "info"))
    text = str(notice.get("text", ""))
    if not text:
        return
    if kind == "success":
        st.success(text)
    elif kind == "warning":
        st.warning(text)
    elif kind == "error":
        st.error(text)
    else:
        st.info(text)


def init_session_state() -> None:
    today = datetime.utcnow().date()
    default_start = (today - timedelta(days=28)).isoformat()
    default_end = today.isoformat()
    defaults = {
        "analysis_result": None,
        "analysis_text": "",
        "analysis_source": "",
        "analysis_report_md": "",
        "analysis_keywords": [],
        "analysis_queries": [],
        "one_page_report_md": "",
        "query_audit": [],
        "action_pack": {},
        "changelog": [],
        "alerts": [],
        "competitor_benchmark": {},
        "ai_recommendations": "",
        "ai_variants": "",
        "is_authenticated": False,
        "auth_user": "",
        "remember_me_login": True,
        "nav_page": "Дашборд",
        "page_menu": "Дашборд",
        "url_input_value": "",
        "text_input_value": "",
        "text_title_value": "",
        "config_keywords_raw": "",
        "config_queries_raw": "",
        "config_competitors_raw": "",
        "config_auto_competitor_query": "",
        "config_competitor_limit": 5,
        "config_project_name": "default_project",
        "config_workspace_name": "main",
        "config_brand_name": "SEOFLOW",
        "config_webhook_url": "",
        "config_ai_provider": "Без AI",
        "config_openai_model": "gpt-4.1-mini",
        "config_ollama_model": "qwen2.5:7b",
        "config_ollama_base_url": "http://127.0.0.1:11434",
        "config_openai_api_key": "",
        "config_pagespeed_api_key": "",
        "config_pagespeed_strategy": "mobile",
        "config_google_service_account_json": "",
        "config_gsc_site_url": "",
        "config_ga4_property_id": "",
        "config_google_start_date": default_start,
        "config_google_end_date": default_end,
        "integration_pagespeed_data": {},
        "integration_gsc_data": {},
        "integration_ga4_data": {},
        "integration_gsc_api_data": {},
        "integration_ga4_api_data": {},
        "profile_notice": None,
        "prepared_export_md": False,
        "prepared_export_json": False,
        "prepared_export_pdf": False,
        "prepared_export_action_json": False,
        "prepared_export_tickets_md": False,
        "prepared_export_changelog_md": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def inject_ui_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700&display=swap');
        :root{
            --bg:#eef0ff;
            --surface:rgba(255,255,255,.72);
            --text:#1d2147;
            --muted:#676f9f;
            --line:rgba(121,114,218,.2);
            --line-strong:rgba(121,114,218,.35);
            --accent:#2d2f68;
            --accent-soft:#f3f1ff;
            --primary:#7a6cff;
        }
        html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"]{
            font-family:"Sora","Segoe UI",sans-serif;
            color:var(--text);
            background:
                radial-gradient(720px 420px at -4% 0%, rgba(126,103,255,.46) 0%, rgba(126,103,255,0) 58%),
                radial-gradient(700px 420px at 104% 12%, rgba(99,130,255,.42) 0%, rgba(99,130,255,0) 56%),
                radial-gradient(900px 500px at 50% 105%, rgba(147,132,255,.34) 0%, rgba(147,132,255,0) 56%),
                var(--bg);
        }
        [data-testid="stAppViewContainer"]{
            position:relative;
            overflow:hidden;
        }
        [data-testid="stAppViewContainer"]::before,
        [data-testid="stAppViewContainer"]::after{
            content:"";
            position:fixed;
            z-index:0;
            pointer-events:none;
            filter:blur(2px);
        }
        [data-testid="stAppViewContainer"]::before{
            width:520px;
            height:520px;
            top:-200px;
            right:-140px;
            border-radius:44% 56% 60% 40% / 50% 40% 60% 50%;
            background:linear-gradient(145deg,rgba(116,103,255,.34),rgba(98,146,255,.18));
        }
        [data-testid="stAppViewContainer"]::after{
            width:560px;
            height:560px;
            bottom:-260px;
            left:-170px;
            border-radius:58% 42% 52% 48% / 42% 58% 45% 55%;
            background:linear-gradient(145deg,rgba(137,110,255,.26),rgba(178,161,255,.16));
        }
        .block-container{
            max-width:1140px;
            padding-top:2.2rem;
            padding-bottom:5.5rem;
            position:relative;
            z-index:1;
        }
        .app-bottom-gap{
            height:72px;
            width:100%;
        }
        [data-testid="stSidebar"] > div:first-child{
            background:rgba(255,255,255,.64);
            border-right:1px solid var(--line);
            backdrop-filter: blur(8px);
        }
        .sidebar-profile-hero{
            border:1px solid rgba(122,108,255,.35);
            border-radius:16px;
            background:linear-gradient(140deg, rgba(29,33,71,.92), rgba(74,92,195,.86));
            padding:12px;
            margin-bottom:10px;
            box-shadow:0 14px 28px rgba(41,50,118,.28);
        }
        .sidebar-profile-top{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:10px;
        }
        .sidebar-profile-ident{
            display:flex;
            align-items:center;
            gap:10px;
            min-width:0;
        }
        .sidebar-profile-avatar{
            width:34px;
            height:34px;
            border-radius:999px;
            display:flex;
            align-items:center;
            justify-content:center;
            font-size:.88rem;
            font-weight:700;
            color:#ffffff;
            background:linear-gradient(135deg,#7e67ff 0%,#4fb0ff 100%);
            box-shadow:0 8px 18px rgba(103,128,255,.46);
            flex:0 0 auto;
        }
        .sidebar-profile-name{
            color:#f5f7ff;
            font-size:.88rem;
            font-weight:700;
            white-space:nowrap;
            overflow:hidden;
            text-overflow:ellipsis;
            max-width:130px;
        }
        .sidebar-profile-plan{
            display:inline-flex;
            align-items:center;
            gap:5px;
            padding:3px 8px;
            border-radius:999px;
            border:1px solid rgba(203,226,255,.42);
            background:rgba(255,255,255,.12);
            color:#e5edff;
            font-size:.68rem;
            font-weight:700;
            white-space:nowrap;
        }
        .sidebar-profile-sub{
            margin-top:8px;
            color:rgba(235,241,255,.86);
            font-size:.73rem;
            line-height:1.35;
        }
        [data-testid="stSidebar"] .stButton:nth-of-type(1) > button{
            border-radius:16px !important;
            text-align:left !important;
            white-space:pre-line !important;
            line-height:1.35 !important;
            min-height:84px !important;
            padding:12px 14px !important;
            border:1px solid rgba(122,108,255,.58) !important;
            background:linear-gradient(135deg,#7a6cff 0%,#5f84ff 60%,#49a7ff 100%) !important;
            color:#ffffff !important;
            font-weight:700 !important;
            letter-spacing:.01em !important;
            box-shadow:0 10px 24px rgba(79,110,236,.34) !important;
            transition:transform .16s ease, box-shadow .2s ease, filter .2s ease !important;
        }
        [data-testid="stSidebar"] .stButton:nth-of-type(1) > button:hover{
            transform:translateY(-2px) !important;
            box-shadow:0 16px 30px rgba(79,110,236,.42) !important;
            filter:saturate(1.08);
        }
        [data-testid="stSidebar"] .stButton:nth-of-type(1) > button:active{
            transform:translateY(0) !important;
        }

        .section-card{
            border:1px solid var(--line);
            border-radius:24px;
            background:var(--surface);
            backdrop-filter:blur(14px);
            padding:18px 20px;
            margin-bottom:16px;
            box-shadow:0 16px 32px rgba(77,73,130,.11);
        }
        .section-card h3{margin:0 0 8px 0;font-size:1.08rem;letter-spacing:.01em;}
        .section-card p{margin:0;color:var(--muted);line-height:1.5;}

        .plan-card{
            border:1px solid var(--line);
            border-radius:18px;
            background:rgba(255,255,255,.92);
            padding:14px;
            box-shadow:0 8px 24px rgba(58,54,110,.08);
            display:flex;
            flex-direction:column;
            min-height:740px;
            height:100%;
        }
        .plan-card-highlight{
            border-color:rgba(122,108,255,.52);
            box-shadow:0 12px 30px rgba(122,108,255,.18);
            background:linear-gradient(180deg,rgba(255,255,255,.98) 0%,rgba(244,242,255,.96) 100%);
        }
        .plan-head{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px;}
        .plan-title{font-size:1rem;font-weight:700;color:#0f172a;}
        .plan-badge{
            font-size:.7rem;
            font-weight:600;
            padding:4px 8px;
            border-radius:999px;
            border:1px solid #dbeafe;
            color:#1d4ed8;
            background:#eff6ff;
            white-space:nowrap;
        }
        .plan-price{font-size:1.6rem;font-weight:700;line-height:1.1;margin:4px 0 2px 0;}
        .plan-period{font-size:.8rem;color:var(--muted);margin-bottom:8px;}
        .plan-tagline{font-size:.84rem;color:#334155;line-height:1.45;margin-bottom:10px;}
        .plan-copy{min-height:150px;}
        .plan-features{min-height:190px;}
        .plan-limits{margin-top:auto;}
        .plan-feature{font-size:.84rem;color:#0f172a;line-height:1.5;margin:4px 0;}
        .plan-muted{font-size:.78rem;color:var(--muted);line-height:1.45;margin-top:8px;}
        .status-title{font-size:.9rem;font-weight:600;margin:0 0 4px 0;color:#0f172a;}
        .status-text{font-size:.82rem;margin:0;color:#475569;line-height:1.45;}
        .order-table{
            border:1px solid var(--line);
            border-radius:14px;
            background:rgba(255,255,255,.9);
            padding:10px 12px;
            margin-bottom:8px;
        }
        .usage-table-shell{
            border:1px solid var(--line);
            border-radius:16px;
            background:rgba(255,255,255,.88);
            overflow:hidden;
            box-shadow:0 10px 24px rgba(77,73,130,.09);
            margin-bottom:12px;
        }
        .usage-table{
            width:100%;
            border-collapse:collapse;
        }
        .usage-table thead th{
            text-align:left;
            font-size:.8rem;
            letter-spacing:.02em;
            color:#5b628f;
            background:rgba(122,108,255,.08);
            border-bottom:1px solid var(--line);
            padding:11px 12px;
            font-weight:600;
        }
        .usage-table tbody td{
            border-bottom:1px solid rgba(121,114,218,.12);
            padding:11px 12px;
            font-size:.9rem;
            color:#1d2147;
            vertical-align:middle;
        }
        .usage-table tbody tr:last-child td{
            border-bottom:none;
        }
        .usage-table tbody tr{
            transition:background .16s ease;
        }
        .usage-table tbody tr:hover{
            background:rgba(122,108,255,.06);
        }
        .usage-action{
            display:flex;
            align-items:center;
            gap:8px;
            font-weight:600;
        }
        .usage-dot{
            width:8px;
            height:8px;
            border-radius:999px;
            background:linear-gradient(135deg,#7a6cff,#5f84ff);
            box-shadow:0 0 0 3px rgba(122,108,255,.16);
            flex:0 0 auto;
        }
        .usage-used{
            font-weight:700;
        }
        .usage-pill{
            display:inline-flex;
            align-items:center;
            justify-content:center;
            min-width:34px;
            padding:2px 10px;
            border-radius:999px;
            background:rgba(122,108,255,.12);
            color:#3e39a8;
            border:1px solid rgba(122,108,255,.28);
            font-size:.82rem;
            font-weight:700;
        }
        .usage-limit{
            font-weight:600;
        }
        .usage-progress{
            width:100%;
            height:8px;
            border-radius:999px;
            background:rgba(122,108,255,.13);
            overflow:hidden;
            margin-bottom:4px;
        }
        .usage-progress-fill{
            height:100%;
            border-radius:999px;
            background:linear-gradient(135deg,#7a6cff,#5f84ff);
            box-shadow:0 0 12px rgba(95,132,255,.35);
            transition:width .35s ease;
        }
        .usage-percent{
            font-size:.78rem;
            color:#5b628f;
            font-weight:600;
        }
        .issue-card{
            border:1px solid var(--line);
            border-radius:14px;
            background:rgba(255,255,255,.88);
            padding:12px 14px;
            margin:10px 0;
            box-shadow:0 8px 20px rgba(77,73,130,.08);
        }
        .issue-head{
            display:flex;
            align-items:center;
            gap:8px;
            flex-wrap:wrap;
            margin-bottom:6px;
        }
        .issue-priority{
            font-size:.78rem;
            font-weight:700;
            padding:2px 8px;
            border-radius:999px;
            border:1px solid transparent;
        }
        .issue-priority-high{
            color:#991b1b;
            background:#fee2e2;
            border-color:#fecaca;
        }
        .issue-priority-medium{
            color:#92400e;
            background:#fef3c7;
            border-color:#fde68a;
        }
        .issue-priority-low{
            color:#166534;
            background:#dcfce7;
            border-color:#bbf7d0;
        }
        .issue-title{
            font-weight:700;
            color:#1d2147;
        }
        .issue-meta{
            font-size:.82rem;
            color:var(--muted);
            margin:2px 0 7px 0;
        }
        .issue-rec{
            font-size:.95rem;
            color:#1d2147;
            line-height:1.5;
        }
        .al-card{
            border:1px solid var(--line);
            border-radius:14px;
            background:rgba(255,255,255,.9);
            padding:12px 14px;
            margin:10px 0;
            box-shadow:0 8px 20px rgba(77,73,130,.08);
        }
        .al-title{
            margin:0 0 6px 0;
            font-size:1rem;
            font-weight:700;
            color:#1d2147;
        }
        .al-sub{
            margin:0 0 8px 0;
            font-size:.84rem;
            color:var(--muted);
        }
        .al-text{
            margin:4px 0;
            font-size:.92rem;
            color:#1d2147;
            line-height:1.45;
        }
        .al-chip{
            display:inline-block;
            font-size:.74rem;
            font-weight:700;
            padding:3px 8px;
            border-radius:999px;
            border:1px solid transparent;
            margin-bottom:6px;
        }
        .al-chip-high{
            color:#991b1b;
            background:#fee2e2;
            border-color:#fecaca;
        }
        .al-chip-medium{
            color:#92400e;
            background:#fef3c7;
            border-color:#fde68a;
        }
        .al-chip-low{
            color:#166534;
            background:#dcfce7;
            border-color:#bbf7d0;
        }
        .al-kv{
            margin:4px 0;
            font-size:.9rem;
            color:#1d2147;
        }
        .al-list{
            margin:6px 0 0 18px;
            color:#1d2147;
            font-size:.92rem;
            line-height:1.45;
        }
        .al-empty{
            border:1px dashed var(--line);
            border-radius:12px;
            background:rgba(255,255,255,.65);
            padding:12px 14px;
            color:var(--muted);
            margin:8px 0;
        }

        .auth-card{
            border:1px solid var(--line);
            border-radius:24px;
            background:var(--surface);
            backdrop-filter:blur(14px);
            padding:20px;
            margin-bottom:16px;
            box-shadow:0 16px 34px rgba(77,73,130,.11);
        }
        .auth-title{margin:0 0 6px 0;font-size:1.1rem;font-weight:700;}
        .auth-subtitle{margin:0;color:var(--muted);font-size:.9rem;}

        .stButton > button{
            border-radius:12px !important;
            border:1px solid var(--line) !important;
            background:rgba(255,255,255,.76) !important;
            color:var(--text) !important;
            font-weight:600 !important;
            box-shadow:none !important;
            transition:border-color .12s ease,transform .12s ease;
        }
        .stButton > button:hover{border-color:var(--line-strong) !important;transform:translateY(-1px);}
        .stButton > button[kind="primary"]{
            background:linear-gradient(135deg,#7e67ff 0%,#5f84ff 100%) !important;
            color:#fff !important;
            border-color:#7364f5 !important;
        }

        [data-baseweb="input"] > div,
        [data-baseweb="textarea"] > div,
        [data-baseweb="select"] > div{
            border:1px solid var(--line) !important;
            border-radius:12px !important;
            background:rgba(255,255,255,.82) !important;
            backdrop-filter:blur(10px);
        }
        [data-baseweb="tab-list"]{
            border:1px solid var(--line);
            border-radius:12px;
            background:rgba(255,255,255,.65);
            padding:4px;
            gap:4px;
            margin:10px 0 14px 0;
        }
        [data-baseweb="tab"]{
            padding:8px 12px !important;
            color:#4d557e !important;
        }
        [aria-selected="true"][data-baseweb="tab"]{
            border:1px solid var(--line-strong) !important;
            border-radius:10px !important;
            background:rgba(255,255,255,.92) !important;
            color:#1d2147 !important;
        }
        [data-baseweb="tab-panel"]{
            padding-top:8px;
        }
        [data-testid="stMetric"]{
            border:1px solid var(--line);
            border-radius:12px;
            background:#fff;
            padding:6px 10px;
        }
        .sale-loader{
            border:1px solid var(--line);
            border-radius:12px;
            background:#fff;
            padding:12px;
            margin-bottom:10px;
            box-shadow:0 4px 20px rgba(15,23,42,.04);
        }
        .sale-loader-title{font-size:.86rem;color:var(--muted);margin-bottom:8px;}
        .sale-loader-line{height:8px;border-radius:999px;background:#edf2ff;margin-bottom:8px;}
        .sale-loader-line:nth-child(2){width:92%;}
        .sale-loader-line:nth-child(3){width:74%;}
        @keyframes app-enter{
            from{opacity:.0;transform:translateY(7px);}
            to{opacity:1;transform:translateY(0);}
        }
        [data-testid="stMain"]{
            animation:app-enter .34s cubic-bezier(.22,1,.36,1);
        }
        .fx-prep{
            opacity:0 !important;
            transform:translateY(14px) scale(.995) !important;
            transition:
                opacity .48s cubic-bezier(.22,1,.36,1),
                transform .48s cubic-bezier(.22,1,.36,1) !important;
            transition-delay:var(--fx-delay,0ms) !important;
            will-change:opacity,transform;
        }
        .fx-in{
            opacity:1 !important;
            transform:none !important;
        }
        .section-card,
        .plan-card,
        .issue-card,
        .al-card,
        .usage-table-shell,
        .order-table,
        [data-testid="stMetric"],
        [data-testid="stAlert"],
        [data-baseweb="input"],
        [data-baseweb="textarea"],
        [data-baseweb="tab-list"]{
            transition:box-shadow .24s ease, transform .24s ease, border-color .24s ease;
        }
        .section-card:hover,
        .plan-card:hover,
        .issue-card:hover,
        .al-card:hover,
        .usage-table-shell:hover{
            transform:translateY(-2px);
            box-shadow:0 14px 28px rgba(77,73,130,.16);
        }
        .stButton > button{
            transition:border-color .18s ease, transform .18s ease, box-shadow .2s ease !important;
        }
        .stButton > button:hover{
            box-shadow:0 10px 24px rgba(94,90,173,.16) !important;
        }

        @media (max-width: 920px){
            .block-container{padding-top:1.5rem;}
            .app-bottom-gap{height:56px;}
        }
        #MainMenu,footer{visibility:hidden;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_motion_script() -> None:
    components.html(
        """
        <script>
        (() => {
          const host = window.parent || window;
          const doc = host.document || document;
          if (!doc || host.__seoMotionBooted) return;
          host.__seoMotionBooted = true;
          const prefersReduced = !!(host.matchMedia && host.matchMedia("(prefers-reduced-motion: reduce)").matches);

          const selector = [
            ".section-card",
            ".plan-card",
            ".issue-card",
            ".al-card",
            ".usage-table-shell",
            ".order-table",
            "[data-testid='stMetric']",
            "[data-testid='stAlert']",
            "[data-baseweb='tab-list']",
            "[data-baseweb='input']",
            "[data-baseweb='textarea']",
            ".stButton button"
          ].join(",");

          const observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
              if (entry.isIntersecting) {
                entry.target.classList.add("fx-in");
                observer.unobserve(entry.target);
              }
            });
          }, { root: null, threshold: 0.08, rootMargin: "0px 0px -6% 0px" });

          function parseMetric(text) {
            const raw = (text || "").trim();
            const m = raw.match(/^(-?\\d+(?:[.,]\\d+)?)(\\s*\\/\\s*\\d+)?(.*)$/);
            if (!m) return null;
            const target = Number.parseFloat(m[1].replace(",", "."));
            if (Number.isNaN(target)) return null;
            const decimals = m[1].includes(".") || m[1].includes(",")
              ? (m[1].split(/[.,]/)[1] || "").length
              : 0;
            return {
              target,
              numberRaw: m[1],
              suffix: `${m[2] || ""}${m[3] || ""}`,
              decimals,
              useComma: m[1].includes(","),
            };
          }

          function formatMetricNumber(value, decimals, useComma) {
            const rounded = decimals > 0 ? value.toFixed(decimals) : String(Math.round(value));
            return useComma ? rounded.replace(".", ",") : rounded;
          }

          function animateMetricValues() {
            const nodes = doc.querySelectorAll("[data-testid='stMetricValue']");
            nodes.forEach((el) => {
              const txt = (el.textContent || "").trim();
              if (!txt || txt === "—") return;
              if (el.dataset.metricRaw === txt) return;
              const parsed = parseMetric(txt);
              if (!parsed) return;

              el.dataset.metricRaw = txt;
              const start = prefersReduced ? parsed.target : 0;
              const end = parsed.target;
              const duration = 760;
              const startAt = host.performance?.now ? host.performance.now() : Date.now();

              function step(now) {
                const current = host.performance?.now ? now : Date.now();
                const progress = Math.min((current - startAt) / duration, 1);
                const eased = 1 - Math.pow(1 - progress, 3);
                const value = start + (end - start) * eased;
                const numberText = formatMetricNumber(value, parsed.decimals, parsed.useComma);
                el.textContent = `${numberText}${parsed.suffix}`;
                if (progress < 1 && !prefersReduced) {
                  host.requestAnimationFrame(step);
                } else {
                  el.textContent = `${parsed.numberRaw}${parsed.suffix}`;
                }
              }

              host.requestAnimationFrame(step);
            });
          }

          function bindTargets() {
            const nodes = doc.querySelectorAll(selector);
            nodes.forEach((el, idx) => {
              if (el.dataset.fxReady === "1") return;
              el.dataset.fxReady = "1";
              el.classList.add("fx-prep");
              el.style.setProperty("--fx-delay", `${Math.min((idx % 20) * 26, 360)}ms`);
              observer.observe(el);
            });
          }

          function syncEffects() {
            bindTargets();
            animateMetricValues();
          }

          syncEffects();
          setTimeout(syncEffects, 120);
          setTimeout(syncEffects, 420);

          const mo = new MutationObserver(() => syncEffects());
          mo.observe(doc.body, { childList: true, subtree: true });
          host.__seoMotionMO = mo;
        })();
        </script>
        """,
        height=0,
    )


def inject_post_auth_form_styles() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"] .stForm{
            border:1px solid var(--line) !important;
            border-radius:14px !important;
            background:rgba(255,255,255,.82) !important;
            backdrop-filter:blur(10px);
            box-shadow:0 8px 20px rgba(77,73,130,.08);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_loader(label: str = "Выполняем анализ...") -> None:
    st.markdown(
        f"""
        <div class="sale-loader">
          <div class="sale-loader-title">{label}</div>
          <div class="sale-loader-line"></div>
          <div class="sale-loader-line"></div>
          <div class="sale-loader-line"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _settings() -> dict[str, object]:
    return {
        "keywords": parse_keywords(st.session_state["config_keywords_raw"]),
        "queries": parse_multiline(st.session_state["config_queries_raw"]),
        "competitors": parse_multiline(st.session_state["config_competitors_raw"]),
        "auto_query": st.session_state["config_auto_competitor_query"],
        "competitor_limit": int(st.session_state["config_competitor_limit"]),
        "project": st.session_state["config_project_name"],
        "workspace": st.session_state["config_workspace_name"],
        "brand": st.session_state["config_brand_name"],
        "webhook_url": st.session_state["config_webhook_url"],
        "ai_provider": st.session_state["config_ai_provider"],
        "openai_model": st.session_state["config_openai_model"],
        "ollama_model": st.session_state["config_ollama_model"],
        "ollama_base_url": st.session_state["config_ollama_base_url"],
        "openai_key": st.session_state["config_openai_api_key"] or os.getenv("OPENAI_API_KEY", ""),
        "pagespeed_api_key": st.session_state["config_pagespeed_api_key"],
        "pagespeed_strategy": st.session_state["config_pagespeed_strategy"],
        "google_service_account_json": st.session_state["config_google_service_account_json"],
        "gsc_site_url": st.session_state["config_gsc_site_url"],
        "ga4_property_id": st.session_state["config_ga4_property_id"],
        "google_start_date": st.session_state["config_google_start_date"],
        "google_end_date": st.session_state["config_google_end_date"],
    }


def _build_changelog_markdown(items: list[str]) -> str:
    if not items:
        return "# Changelog\n\nНет изменений.\n"
    return "# Changelog\n\n" + "\n".join(f"- {item}" for item in items) + "\n"


def _check_ollama_available(base_url: str) -> tuple[bool, str]:
    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=3)
        response.raise_for_status()
        return True, ""
    except requests.exceptions.RequestException:
        return False, f"Не удалось подключиться к Ollama по адресу {base_url}."


def _send_webhook(webhook_url: str, payload: dict) -> tuple[bool, str]:
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        return True, "Webhook отправлен."
    except requests.exceptions.RequestException as error:
        return False, f"Ошибка отправки webhook: {error}"


def _query_param_value(name: str) -> str:
    raw = st.query_params.get(name, "")
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    return str(raw or "").strip()


def _set_query_param(name: str, value: str) -> None:
    st.query_params[name] = value


def _delete_query_param(name: str) -> None:
    if name in st.query_params:
        del st.query_params[name]


def _restore_auth_from_persistent_token() -> None:
    if _is_authenticated():
        return
    token = _query_param_value("auth")
    if not token:
        return
    username = resolve_persistent_login_token(token)
    if username:
        st.session_state["is_authenticated"] = True
        st.session_state["auth_user"] = username
    else:
        _delete_query_param("auth")


def _refresh_uploaded_integrations_state() -> None:
    gsc_file = st.session_state.get("config_gsc_csv")
    ga4_file = st.session_state.get("config_ga4_csv")

    if gsc_file is not None:
        try:
            st.session_state["integration_gsc_data"] = parse_gsc_csv(gsc_file.getvalue())
        except Exception as error:  # noqa: BLE001
            st.session_state["integration_gsc_data"] = {"ok": False, "error": f"GSC import error: {error}"}
    else:
        st.session_state["integration_gsc_data"] = {}

    if ga4_file is not None:
        try:
            st.session_state["integration_ga4_data"] = parse_ga4_csv(ga4_file.getvalue())
        except Exception as error:  # noqa: BLE001
            st.session_state["integration_ga4_data"] = {"ok": False, "error": f"GA4 import error: {error}"}
    else:
        st.session_state["integration_ga4_data"] = {}


def _refresh_pagespeed_state(url: str, settings: dict[str, object]) -> None:
    if not url.startswith(("http://", "https://")):
        st.session_state["integration_pagespeed_data"] = {}
        return

    api_key = str(settings.get("pagespeed_api_key", "")).strip()
    if not api_key:
        st.session_state["integration_pagespeed_data"] = {}
        return

    strategy = str(settings.get("pagespeed_strategy", "mobile")).strip() or "mobile"
    st.session_state["integration_pagespeed_data"] = fetch_pagespeed_data(url, api_key, strategy=strategy)


def _refresh_google_api_integrations_state(settings: dict[str, object]) -> None:
    sa_json = str(settings.get("google_service_account_json", "")).strip()
    start_date = str(settings.get("google_start_date", "")).strip()
    end_date = str(settings.get("google_end_date", "")).strip()
    gsc_site_url = str(settings.get("gsc_site_url", "")).strip()
    ga4_property_id = str(settings.get("ga4_property_id", "")).strip()

    if not sa_json:
        st.session_state["integration_gsc_api_data"] = {}
        st.session_state["integration_ga4_api_data"] = {}
        return

    if gsc_site_url:
        st.session_state["integration_gsc_api_data"] = fetch_gsc_api_data(
            service_account_json=sa_json,
            site_url=gsc_site_url,
            start_date=start_date,
            end_date=end_date,
            row_limit=100,
        )
    else:
        st.session_state["integration_gsc_api_data"] = {}

    if ga4_property_id:
        st.session_state["integration_ga4_api_data"] = fetch_ga4_api_data(
            service_account_json=sa_json,
            property_id=ga4_property_id,
            start_date=start_date,
            end_date=end_date,
            row_limit=100,
        )
    else:
        st.session_state["integration_ga4_api_data"] = {}


def _attach_integrations_to_action_pack() -> None:
    action_pack = st.session_state.get("action_pack")
    if not isinstance(action_pack, dict):
        return
    action_pack["integrations"] = {
        "pagespeed": st.session_state.get("integration_pagespeed_data", {}),
        "gsc_csv": st.session_state.get("integration_gsc_data", {}),
        "ga4_csv": st.session_state.get("integration_ga4_data", {}),
        "gsc_api": st.session_state.get("integration_gsc_api_data", {}),
        "ga4_api": st.session_state.get("integration_ga4_api_data", {}),
    }
    st.session_state["action_pack"] = action_pack


def _current_user() -> str:
    return str(st.session_state.get("auth_user", "")).strip()


def _is_authenticated() -> bool:
    # If username exists in session, treat it as authenticated state.
    user = _current_user()
    auth_flag = bool(st.session_state.get("is_authenticated", False))
    if user and not auth_flag:
        st.session_state["is_authenticated"] = True
        return True
    if not user and auth_flag:
        st.session_state["is_authenticated"] = False
        return False
    return auth_flag


def _active_subscription() -> bool:
    user = _current_user()
    return bool(user and has_active_subscription(user))


def _consume_action(action: str, amount: int = 1, show_success: bool = True) -> bool:
    user = _current_user()
    if not user:
        st.error("Пользователь не авторизован.")
        return False
    ok, message = check_and_consume(user, action, amount=amount)
    if ok:
        if show_success:
            st.caption(message)
        return True
    st.warning(message)
    return False


def _reset_export_flags() -> None:
    for key in (
        "prepared_export_md",
        "prepared_export_json",
        "prepared_export_pdf",
        "prepared_export_action_json",
        "prepared_export_tickets_md",
        "prepared_export_changelog_md",
    ):
        st.session_state[key] = False


def _save_analysis_result(
    result: AnalysisResult,
    source_text: str,
    source_label: str,
    settings: dict[str, object],
) -> None:
    title = str(result.metrics.get("title_text", ""))
    h1_text = str(result.metrics.get("h1_text", ""))
    h2_texts_raw = result.metrics.get("h2_texts", [])
    h2_texts = h2_texts_raw if isinstance(h2_texts_raw, list) else []
    queries = list(settings["queries"])

    query_audit = audit_queries(
        queries=queries,
        page_text=source_text,
        title=title,
        h1_text=h1_text,
        h2_texts=[str(item) for item in h2_texts],
    )
    action_pack = build_action_pack(
        result=result,
        source_url=source_label,
        page_text=source_text,
        queries=queries,
        query_audit=query_audit,
    )

    st.session_state["analysis_result"] = result
    st.session_state["analysis_text"] = source_text
    st.session_state["analysis_source"] = source_label
    st.session_state["analysis_keywords"] = list(settings["keywords"])
    st.session_state["analysis_queries"] = queries
    st.session_state["query_audit"] = query_audit
    st.session_state["action_pack"] = action_pack
    st.session_state["analysis_report_md"] = build_markdown_report(result)
    st.session_state["one_page_report_md"] = build_one_page_report(result, brand_name=str(settings["brand"]))
    st.session_state["ai_recommendations"] = ""
    st.session_state["ai_variants"] = ""
    _attach_integrations_to_action_pack()
    _reset_export_flags()


def _refresh_history_state(result: AnalysisResult, settings: dict[str, object]) -> None:
    payload = {
        "source": result.source,
        "score": result.score,
        "metrics": result.metrics,
        "issues": [asdict(item) for item in result.issues],
        "query_audit": st.session_state.get("query_audit", []),
    }
    previous = load_previous_snapshot(str(settings["project"]), str(settings["workspace"]), result.source)
    st.session_state["changelog"] = build_changelog(previous, payload)
    st.session_state["alerts"] = build_alerts(previous, payload)
    save_snapshot(str(settings["project"]), str(settings["workspace"]), result.source, payload)


def _run_competitor_benchmark(result: AnalysisResult, source_url: str, settings: dict[str, object]) -> None:
    competitors = [u for u in list(settings["competitors"]) if u != source_url]
    auto_query = str(settings["auto_query"]).strip()
    if source_url.startswith("http") and auto_query:
        for item in discover_competitors(auto_query, source_url, limit=int(settings["competitor_limit"])):
            if item not in competitors and item != source_url:
                competitors.append(item)

    if not competitors or not source_url.startswith("http"):
        st.session_state["competitor_benchmark"] = {}
        return

    if not _consume_action(ACTION_COMPETITORS, show_success=False):
        st.session_state["competitor_benchmark"] = {}
        return

    st.session_state["competitor_benchmark"] = benchmark_against_competitors(
        target_result=result,
        target_url=source_url,
        competitor_urls=competitors[: int(settings["competitor_limit"])],
        keywords=list(settings["keywords"]),
    )


def build_markdown_report(result: AnalysisResult) -> str:
    lines = [
        "# SEO-отчет",
        "",
        f"- Источник: {result.source}",
        f"- Эвристический индекс SEO-качества: {result.score}/100",
        "- Важно: индекс является модельной оценкой для приоритизации задач, а не абсолютной истиной.",
        "",
        "## Проблемы",
    ]
    issues = sorted_issues(result)
    if not issues:
        lines.append("- Критичных проблем не найдено.")
    else:
        for issue in issues:
            priority_label = PRIORITY_LABELS.get(issue.priority, issue.priority)
            lines.append(f"- **{priority_label} / {issue.category}**: {issue.title}. {issue.recommendation}")
    lines.append("")
    lines.append("## Доказательность")
    lines.append(f"- Indexability status: {result.metrics.get('indexability_status', 'n/a')}")
    lines.append(f"- Intent coverage: {result.metrics.get('intent_coverage_pct', 'n/a')}%")
    lines.append(f"- CTA status: {result.metrics.get('cta_status', 'n/a')}")
    lines.append(
        "- Рекомендация: сверяйте выводы с внешними источниками (GSC/GA4/PageSpeed), "
        "если принимается бизнес-решение."
    )
    lines.append("")
    lines.append("## Метрики")
    for key, value in result.metrics.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def _go(page_name: str) -> None:
    if page_name in APP_PAGES:
        st.session_state["nav_page"] = page_name
    st.rerun()


def _on_menu_change() -> None:
    selected = st.session_state.get("page_menu")
    if selected in APP_PAGES:
        st.session_state["nav_page"] = selected


def _page_label(page: str) -> str:
    return PAGE_LABELS.get(page, page)


def render_app_header() -> None:
    return


def inject_auth_gate_styles() -> None:
    st.markdown(
        """
        <style>
        :root{
            --auth-bg:#060a12;
            --auth-panel:#0b1220;
            --auth-panel-2:#0f1728;
            --auth-line:rgba(80,108,168,.36);
            --auth-line-strong:rgba(86,145,255,.8);
            --auth-text:#eaf1ff;
            --auth-muted:#96a6c9;
            --auth-primary-a:#3e68ff;
            --auth-primary-b:#21b8ee;
        }
        html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"]{
            background:linear-gradient(180deg,#050913 0%, #060d1a 100%) !important;
            color:var(--auth-text) !important;
        }
        [data-testid="stAppViewContainer"]::before,
        [data-testid="stAppViewContainer"]::after{
            display:none !important;
            content:none !important;
        }
        .block-container{
            max-width:560px !important;
            margin:0 auto !important;
            padding-top:8vh !important;
            padding-bottom:5vh !important;
        }
        .auth-head{
            border:1px solid var(--auth-line);
            border-radius:18px;
            background:linear-gradient(180deg,var(--auth-panel) 0%, var(--auth-panel-2) 100%);
            padding:22px 22px 18px;
            margin-bottom:14px;
            box-shadow:0 16px 40px rgba(2,8,18,.46);
        }
        .auth-heading{
            margin:0;
            font-size:2rem;
            line-height:1.08;
            font-weight:700;
            letter-spacing:.01em;
            color:var(--auth-text);
        }
        .auth-caption{
            margin:14px 0 0;
            color:var(--auth-muted);
            font-size:.98rem;
            line-height:1.5;
        }
        .auth-divider{
            height:1px;
            margin:16px 0 0;
            background:linear-gradient(90deg, rgba(86,145,255,.42), rgba(86,145,255,0));
        }
        .stTabs [data-baseweb="tab-list"]{
            border:1px solid var(--auth-line) !important;
            background:rgba(8,14,26,.82) !important;
            border-radius:12px !important;
            padding:4px !important;
            margin:0 0 10px !important;
        }
        .stTabs [data-baseweb="tab"]{
            color:var(--auth-muted) !important;
            border-radius:9px !important;
            font-weight:500 !important;
        }
        .stTabs [aria-selected="true"][data-baseweb="tab"]{
            color:var(--auth-text) !important;
            border:1px solid var(--auth-line-strong) !important;
            background:rgba(66,111,255,.16) !important;
        }
        .stTabs [data-baseweb="tab-panel"]{
            padding-top:8px !important;
        }
        .stForm{
            border:1px solid var(--auth-line) !important;
            border-radius:14px !important;
            background:linear-gradient(180deg, rgba(10,17,30,.92), rgba(10,17,30,.84)) !important;
            padding:14px 14px 10px !important;
        }
        .stTextInput label,
        .stCheckbox label{
            color:var(--auth-muted) !important;
        }
        .stTextInput [data-baseweb="input"]{
            border:1px solid var(--auth-line) !important;
            border-radius:10px !important;
            background:#0f1728 !important;
            overflow:hidden !important;
            box-shadow:none !important;
            outline:none !important;
        }
        .stTextInput [data-baseweb="input"] > div{
            border:none !important;
            background:transparent !important;
        }
        .stTextInput [data-baseweb="input"]:focus-within{
            border-color:var(--auth-line-strong) !important;
            box-shadow:none !important;
            outline:none !important;
        }
        .stTextInput [data-baseweb="input"] input{
            color:var(--auth-text) !important;
            background:transparent !important;
            box-shadow:none !important;
        }
        .stTextInput [data-baseweb="input"] input::placeholder{
            color:#8395bb !important;
        }
        .stTextInput [data-baseweb="input"] button{
            border:none !important;
            background:transparent !important;
            color:#9fb2d8 !important;
            box-shadow:none !important;
            outline:none !important;
        }
        .stTextInput [data-baseweb="input"] button svg{
            fill:#9fb2d8 !important;
        }
        [data-testid="InputInstructions"]{
            display:none !important;
        }
        .stCheckbox{
            margin-top:2px !important;
            margin-bottom:2px !important;
        }
        .stButton > button, .stForm button{
            border-radius:10px !important;
            border:1px solid var(--auth-line) !important;
            background:#0f1728 !important;
            color:var(--auth-text) !important;
            box-shadow:none !important;
        }
        .stButton > button:hover, .stForm button:hover{
            border-color:var(--auth-line-strong) !important;
        }
        .stButton > button[kind="primary"], .stForm button[kind="primary"]{
            border:none !important;
            background:linear-gradient(90deg,var(--auth-primary-a),var(--auth-primary-b)) !important;
            color:#fff !important;
            font-weight:600 !important;
        }
        .auth-links{
            display:flex;
            justify-content:space-between;
            align-items:center;
            margin:10px 2px 2px;
            color:var(--auth-muted);
            font-size:.9rem;
        }
        .auth-links .link{
            color:#b4c4e8;
            text-decoration:none;
        }
        .auth-footer-note{
            margin:10px 2px 0;
            font-size:.82rem;
            color:var(--auth-muted);
            text-align:center;
        }
        .stAlert{
            border:1px solid rgba(80,120,210,.45) !important;
            background:rgba(11,17,28,.95) !important;
        }
        @media (max-width: 760px){
            .block-container{
                max-width:96vw !important;
                padding-top:2.2rem !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_auth_gate() -> bool:
    if _is_authenticated():
        return True

    inject_auth_gate_styles()
    st.markdown(
        """
        <div class="auth-head">
          <h2 class="auth-heading">\u0410\u0432\u0442\u043e\u0440\u0438\u0437\u0430\u0446\u0438\u044f</h2>
          <p class="auth-caption">\u0412\u043e\u0439\u0434\u0438\u0442\u0435 \u0438\u043b\u0438 \u0441\u043e\u0437\u0434\u0430\u0439\u0442\u0435 \u0430\u043a\u043a\u0430\u0443\u043d\u0442, \u0447\u0442\u043e\u0431\u044b \u043e\u0442\u043a\u0440\u044b\u0442\u044c \u0434\u043e\u0441\u0442\u0443\u043f \u043a SEO-\u0430\u0443\u0434\u0438\u0442\u0443 \u0438 \u0442\u0430\u0440\u0438\u0444\u0430\u043c.</p>
          <div class="auth-divider"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_login, tab_register = st.tabs(["\u0412\u0445\u043e\u0434", "\u0420\u0435\u0433\u0438\u0441\u0442\u0440\u0430\u0446\u0438\u044f"])
    with tab_login:
        with st.form("login_form"):
            username = st.text_input("\u041b\u043e\u0433\u0438\u043d \u0438\u043b\u0438 e-mail", placeholder="\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043b\u043e\u0433\u0438\u043d \u0438\u043b\u0438 e-mail")
            password = st.text_input("\u041f\u0430\u0440\u043e\u043b\u044c", type="password", placeholder="\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043f\u0430\u0440\u043e\u043b\u044c")
            remember_me = st.checkbox("\u0417\u0430\u043f\u043e\u043c\u043d\u0438\u0442\u044c \u043c\u0435\u043d\u044f", key="remember_me_login", value=True)
            submit = st.form_submit_button("\u0412\u043e\u0439\u0442\u0438", type="primary", use_container_width=True)
        st.markdown('<div class="auth-links"><span></span><a class="link" href="#">\u0417\u0430\u0431\u044b\u043b\u0438 \u043f\u0430\u0440\u043e\u043b\u044c?</a></div>', unsafe_allow_html=True)
        if submit:
            ok, message = authenticate_user(username=username, password=password)
            if ok:
                resolved_username = resolve_login_username(username) or username.strip()
                st.session_state["is_authenticated"] = True
                st.session_state["auth_user"] = resolved_username
                if remember_me:
                    token = create_persistent_login_token(resolved_username)
                    if token:
                        _set_query_param("auth", token)
                else:
                    old_token = _query_param_value("auth")
                    if old_token:
                        revoke_persistent_login_token(old_token)
                    _delete_query_param("auth")
                st.rerun()
            else:
                st.error(message)

    with tab_register:
        with st.form("register_form"):
            username = st.text_input("\u041b\u043e\u0433\u0438\u043d (3-32 \u0441\u0438\u043c\u0432\u043e\u043b\u0430)", placeholder="\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043b\u043e\u0433\u0438\u043d")
            password = st.text_input(
                "\u041f\u0430\u0440\u043e\u043b\u044c (\u043c\u0438\u043d\u0438\u043c\u0443\u043c 8 \u0441\u0438\u043c\u0432\u043e\u043b\u043e\u0432, \u043b\u0430\u0442\u0438\u043d\u0438\u0446\u0430, 1 \u0437\u0430\u0433\u043b\u0430\u0432\u043d\u0430\u044f)",
                type="password",
                placeholder="\u0421\u043e\u0437\u0434\u0430\u0439\u0442\u0435 \u043f\u0430\u0440\u043e\u043b\u044c",
            )
            repeat_password = st.text_input("\u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u043f\u0430\u0440\u043e\u043b\u044c", type="password", placeholder="\u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u043f\u0430\u0440\u043e\u043b\u044c")
            submit = st.form_submit_button("\u0421\u043e\u0437\u0434\u0430\u0442\u044c \u0430\u043a\u043a\u0430\u0443\u043d\u0442", use_container_width=True)
        if submit:
            if password != repeat_password:
                st.error("\u041f\u0430\u0440\u043e\u043b\u0438 \u043d\u0435 \u0441\u043e\u0432\u043f\u0430\u0434\u0430\u044e\u0442.")
            else:
                ok, message = register_user(username=username, password=password)
                if ok:
                    resolved_username = resolve_login_username(username) or username.strip()
                    st.session_state["is_authenticated"] = True
                    st.session_state["auth_user"] = resolved_username
                    token = create_persistent_login_token(resolved_username)
                    if token:
                        _set_query_param("auth", token)
                    st.rerun()
                else:
                    st.error(message)

    st.markdown('<p class="auth-footer-note">\u0420\u0435\u0433\u0438\u0441\u0442\u0440\u0430\u0446\u0438\u044f \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438 \u0432\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442 \u0432\u0445\u043e\u0434 \u0432 \u0430\u043a\u043a\u0430\u0443\u043d\u0442.</p>', unsafe_allow_html=True)
    return False

def render_sidebar() -> None:
    with st.sidebar:
        user = _current_user() or "user"
        subscription = get_subscription(user)
        plan_title = str(subscription.get("plan_title", "Free")) if subscription else "Free"
        avatar_letter = (str(user).strip()[:1] or "U").upper()
        profile_button_label = f"{avatar_letter}  {user}\nPlan · {plan_title}\nПрофиль и подписка"
        if st.button(profile_button_label, use_container_width=True, key="sidebar_profile_btn"):
            _go(PROFILE_PAGE)

        st.radio("Меню", MENU_PAGES, key="page_menu", format_func=_page_label, on_change=_on_menu_change)
        st.divider()
        if st.button("Выйти", use_container_width=True, key="sidebar_logout_btn"):
            old_token = _query_param_value("auth")
            if old_token:
                revoke_persistent_login_token(old_token)
            _delete_query_param("auth")
            st.session_state["is_authenticated"] = False
            st.session_state["auth_user"] = ""
            st.session_state["nav_page"] = DASHBOARD_PAGE
            st.session_state["page_menu"] = DASHBOARD_PAGE
            st.rerun()


def render_dashboard() -> None:
    result: AnalysisResult | None = st.session_state.get("analysis_result")
    st.markdown(
        """
        <div class="section-card">
          <h3>Дашборд</h3>
          <p>Рабочая панель SEO-аудита.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not _active_subscription():
        st.warning("Подписка не активна.")
        if st.button("Открыть тарифы", key="go_tariffs_from_dashboard", use_container_width=True):
            _go("Тарифы")

    c1, c2, c3 = st.columns(3)
    c1.metric("Последний анализ", (st.session_state.get("analysis_source", "—") or "—")[:38])
    c2.metric("Проблем найдено", len(result.issues) if result else 0)
    c3.metric("SEO-оценка", f"{result.score}/100" if result else "—")

    a1, a2, a3 = st.columns(3)
    if a1.button("Новый аудит", use_container_width=True, type="primary"):
        _go("Новый аудит")
    if a2.button("Результат", use_container_width=True):
        _go("Результат")
    if a3.button("Action Lab", use_container_width=True):
        _go("Action Lab")


def render_profile_page() -> None:
    user = _current_user()
    if not user:
        st.error("Пользователь не авторизован.")
        return

    profile = get_user_profile(user) or {"username": user, "email": "", "created_at": ""}
    subscription = get_subscription(user)
    usage = usage_snapshot(user)
    orders = list_checkout_orders(user, limit=20)
    provider = payment_provider_status()

    st.markdown(
        """
        <div class="section-card">
          <h3>Профиль</h3>
          <p>Вся информация по аккаунту, подписке, лимитам и безопасности в одном месте.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Логин", str(profile.get("username", "—")))
    c2.metric("Тариф", str(subscription.get("plan_title", "Нет")) if subscription else "Нет")
    c3.metric("Статус", str(subscription.get("status", "inactive")) if subscription else "inactive")

    with st.container():
        st.subheader("Данные аккаунта")
        st.markdown(f"**Логин:** `{profile.get('username', user)}`")
        st.markdown(f"**Email:** `{profile.get('email') or 'не указан'}`")
        st.markdown(f"**Создан:** `{_format_datetime_value(profile.get('created_at'))}`")

    st.subheader("Подписка и оплата")
    if subscription and subscription.get("status") == "active":
        st.success(f"Активный тариф: {subscription.get('plan_title')} ({subscription.get('price_rub')} ₽/мес)")
    elif subscription:
        st.warning(f"Тариф: {subscription.get('plan_title')} (статус: {subscription.get('status')})")
    else:
        st.info("Подписка не подключена.")
    st.caption(f"Платежный режим: {provider.get('provider')}. {provider.get('message')}")

    if subscription:
        st.markdown("**Возможности тарифа:**")
        for feature in subscription.get("features", []):
            st.markdown(f"- {feature}")

    st.subheader("Лимиты текущего месяца")
    if usage:
        render_usage_table(usage)
    else:
        st.caption("Данные по лимитам пока отсутствуют.")

    st.subheader("История заказов")
    if not orders:
        st.caption("Заказов пока нет.")
    else:
        for order in orders:
            order_plan = PLANS.get(str(order["plan_id"]), PLANS["starter"]).title
            st.markdown(
                f"""
                <div class="order-table">
                  <div class="status-title">{order["order_id"]} · {order_plan} · {order["amount_rub"]} ₽</div>
                  <div class="status-text">Статус: {order["status"]} · Провайдер: {order["provider"]} · Создан: {_format_datetime_value(order["created_at"])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.subheader("Безопасность")
    _show_profile_notice()
    left, right = st.columns(2)

    with left:
        with st.expander("Изменить email", expanded=False):
            with st.form("profile_email_inline_form"):
                email_value = st.text_input("Новый email", value=str(profile.get("email") or ""), placeholder="name@example.com")
                save_email = st.form_submit_button("Сохранить email", use_container_width=True)
            if save_email:
                ok, message = update_user_email(user, email_value)
                st.success(message) if ok else st.error(message)

    with right:
        with st.expander("Сменить пароль", expanded=False):
            with st.form("profile_password_inline_form"):
                current_password = st.text_input("Текущий пароль", type="password")
                new_password = st.text_input("Новый пароль", type="password")
                repeat_password = st.text_input("Повторите новый пароль", type="password")
                save_password = st.form_submit_button("Сменить пароль", use_container_width=True)
            if save_password:
                if new_password != repeat_password:
                    st.error("Новый пароль и подтверждение не совпадают.")
                else:
                    ok, message = change_user_password(user, current_password, new_password)
                    st.success(message) if ok else st.error(message)


def render_settings_page() -> None:
    st.subheader("Настройки проекта")
    left, right = st.columns(2)
    with left:
        st.text_input("Ключевые слова (через запятую)", key="config_keywords_raw")
        st.text_area("Целевые запросы (по одному на строку)", key="config_queries_raw", height=150)
        st.text_area("Конкуренты (URL, по одному на строку)", key="config_competitors_raw", height=120)
        st.text_input("Авто-поиск конкурентов (SERP запрос)", key="config_auto_competitor_query")
        st.slider("Макс. конкурентов", 1, 10, key="config_competitor_limit")
    with right:
        st.text_input("Проект", key="config_project_name")
        st.text_input("Workspace", key="config_workspace_name")
        st.text_input("White-label бренд", key="config_brand_name")
        st.text_input("Webhook URL", key="config_webhook_url")
        provider = st.selectbox("AI-провайдер", AI_PROVIDERS, key="config_ai_provider")
        if provider == "OpenAI":
            st.text_input("OpenAI модель", key="config_openai_model")
            st.text_input("OpenAI API key (текущая сессия)", type="password", key="config_openai_api_key")
        elif str(provider).startswith("Ollama"):
            st.text_input("Ollama модель", key="config_ollama_model")
            st.text_input("Ollama URL", key="config_ollama_base_url")
        else:
            st.caption("AI отключен. Выберите OpenAI или Ollama, чтобы включить AI-функции.")

    st.divider()
    st.subheader("Интеграции и внешние данные")
    ext_left, ext_right = st.columns(2)
    with ext_left:
        st.text_input("PageSpeed API key", type="password", key="config_pagespeed_api_key")
        st.selectbox("PageSpeed стратегия", ["mobile", "desktop"], key="config_pagespeed_strategy")
    with ext_right:
        st.caption(
            "Подключите реальный performance-сигнал через Google PageSpeed API. "
            "Это усиливает доказательность отчета."
        )
        st.caption("Для GSC/GA4 доступны 2 режима: прямой API (Service Account) или импорт CSV.")

    st.markdown("**Google API (прямое подключение)**")
    api_left, api_right = st.columns(2)
    with api_left:
        sa_file = st.file_uploader("Service Account JSON", type=["json"], key="config_google_service_account_file")
        if sa_file is not None:
            try:
                st.session_state["config_google_service_account_json"] = sa_file.getvalue().decode("utf-8")
                st.success("Service Account JSON загружен.")
            except Exception as error:  # noqa: BLE001
                st.error(f"Не удалось прочитать Service Account JSON: {error}")
        st.text_input("GSC Site URL", key="config_gsc_site_url", placeholder="sc-domain:example.com")
        st.text_input("GA4 Property ID", key="config_ga4_property_id", placeholder="123456789")
    with api_right:
        st.text_input("Период: start_date (YYYY-MM-DD)", key="config_google_start_date")
        st.text_input("Период: end_date (YYYY-MM-DD)", key="config_google_end_date")
        if st.button("Проверить Google API коннекторы", key="btn_refresh_google_api", use_container_width=True):
            _refresh_google_api_integrations_state(_settings())
            _attach_integrations_to_action_pack()

    gsc_api_data = st.session_state.get("integration_gsc_api_data", {})
    ga4_api_data = st.session_state.get("integration_ga4_api_data", {})
    if gsc_api_data:
        if bool(gsc_api_data.get("ok")):
            st.success(
                f"GSC API подключен: строки {gsc_api_data.get('rows', 0)}, "
                f"клики {gsc_api_data.get('total_clicks', 0)}, показы {gsc_api_data.get('total_impressions', 0)}."
            )
        else:
            st.warning(str(gsc_api_data.get("error", "Ошибка подключения GSC API.")))
    if ga4_api_data:
        if bool(ga4_api_data.get("ok")):
            st.success(
                f"GA4 API подключен: строки {ga4_api_data.get('rows', 0)}, "
                f"сеансы {ga4_api_data.get('total_sessions', 0)}, пользователи {ga4_api_data.get('total_users', 0)}."
            )
        else:
            st.warning(str(ga4_api_data.get("error", "Ошибка подключения GA4 API.")))

    st.markdown("**CSV fallback (если API не подключен)**")
    st.file_uploader("Импорт GSC CSV (Search Console)", type=["csv"], key="config_gsc_csv")
    st.file_uploader("Импорт GA4 CSV (Landing page report)", type=["csv"], key="config_ga4_csv")
    _refresh_uploaded_integrations_state()

    gsc_data = st.session_state.get("integration_gsc_data", {})
    ga4_data = st.session_state.get("integration_ga4_data", {})

    if gsc_data:
        if bool(gsc_data.get("ok")):
            st.success(
                f"GSC подключен: строк {gsc_data.get('rows', 0)}, "
                f"клики {gsc_data.get('total_clicks', 0)}, показы {gsc_data.get('total_impressions', 0)}."
            )
        else:
            st.warning(str(gsc_data.get("error", "Ошибка чтения GSC CSV.")))
    if ga4_data:
        if bool(ga4_data.get("ok")):
            st.success(
                f"GA4 подключен: строк {ga4_data.get('rows', 0)}, "
                f"сеансы {ga4_data.get('total_sessions', 0)}, пользователи {ga4_data.get('total_users', 0)}."
            )
        else:
            st.warning(str(ga4_data.get("error", "Ошибка чтения GA4 CSV.")))

    st.success("Настройки применяются автоматически.")
    st.divider()
    st.subheader("Платежные переменные окружения")
    st.code(
        """PAYMENT_PROVIDER=payment_links
PAYMENT_LINK_STARTER=https://...
PAYMENT_LINK_GROWTH=https://...
PAYMENT_LINK_PRO=https://...
PAYMENT_LINK_AGENCY=https://...
PAYMENT_ALLOW_MANUAL_CONFIRM=false
""",
        language="bash",
    )
    provider = payment_provider_status()
    st.caption(f"Текущий платежный режим: {provider['provider']}. {provider['message']}")


def _prepare_download(slot: str, title: str, data: str | bytes, filename: str, mime: str) -> None:
    prep_key = f"prepared_{slot}"
    left, right = st.columns([1, 1])
    if left.button(f"Подготовить {title}", key=f"btn_prepare_{slot}", use_container_width=True):
        if _consume_action(ACTION_EXPORT, show_success=False):
            st.session_state[prep_key] = True
            st.success(f"{title} готов к скачиванию.")
    if st.session_state.get(prep_key, False):
        right.download_button(f"Скачать {title}", data, filename, mime, key=f"download_{slot}", use_container_width=True)
    else:
        right.caption("Сначала подготовьте файл")


def render_new_audit_page() -> None:
    settings = _settings()
    st.markdown(
        """
        <div class="section-card">
          <h3>Новый аудит</h3>
          <p>Проверка URL или текста статьи.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_url, tab_text = st.tabs(["Проверить сайт по URL", "Проверить текст статьи"])
    with tab_url:
        with st.form("url_form"):
            url = st.text_input("Ссылка на страницу", key="url_input_value", placeholder="https://example.com/page")
            submit = st.form_submit_button("Проверить страницу", type="primary")
        if submit:
            if not _active_subscription():
                st.warning("Нет активного тарифа. Оформите подписку в разделе «Тарифы».")
                if st.button("Открыть тарифы", key="go_tariffs_from_url"):
                    _go("Тарифы")
            elif not url.strip():
                st.error("Введите URL страницы.")
            else:
                try:
                    render_loader("Собираем HTML и считаем SEO-метрики...")
                    html = load_html_from_url(url.strip())
                    result = analyze_html(source=url.strip(), html=html, keywords=list(settings["keywords"]) or None)
                    source_text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
                    if not _consume_action(ACTION_URL_AUDIT):
                        return
                    _refresh_pagespeed_state(url.strip(), settings)
                    _refresh_google_api_integrations_state(settings)
                    _save_analysis_result(result, source_text, url.strip(), settings)
                    _refresh_history_state(result, settings)
                    _run_competitor_benchmark(result, url.strip(), settings)
                    _attach_integrations_to_action_pack()
                    st.success("URL успешно проанализирован.")
                    _go("Результат")
                except Exception as error:  # noqa: BLE001
                    st.error(f"Не удалось проанализировать URL: {error}")

    with tab_text:
        with st.form("text_form"):
            title = st.text_input("Заголовок статьи (необязательно)", key="text_title_value")
            text = st.text_area("Текст статьи", key="text_input_value", height=280)
            submit = st.form_submit_button("Проверить текст")
        if submit:
            if not _active_subscription():
                st.warning("Нет активного тарифа. Оформите подписку в разделе «Тарифы».")
                if st.button("Открыть тарифы", key="go_tariffs_from_text"):
                    _go("Тарифы")
            elif not text.strip():
                st.error("Вставьте текст статьи.")
            else:
                render_loader("Анализируем структуру и полезность текста...")
                result = analyze_text_article(
                    source="article_text",
                    text=text,
                    keywords=list(settings["keywords"]) or None,
                    title=title,
                )
                if not _consume_action(ACTION_TEXT_AUDIT):
                    return
                st.session_state["integration_pagespeed_data"] = {}
                _refresh_google_api_integrations_state(settings)
                _save_analysis_result(result, text, "article_text", settings)
                _refresh_history_state(result, settings)
                st.session_state["competitor_benchmark"] = {}
                _attach_integrations_to_action_pack()
                st.success("Текст успешно проанализирован.")
                _go("Результат")


def render_result_page() -> None:
    result: AnalysisResult | None = st.session_state.get("analysis_result")
    if not result:
        st.info("Результата еще нет. Перейдите в «Новый аудит».")
        return

    high = sum(1 for i in result.issues if i.priority == "HIGH")
    medium = sum(1 for i in result.issues if i.priority == "MEDIUM")
    low = sum(1 for i in result.issues if i.priority == "LOW")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Эвристический индекс", f"{result.score}/100")
    c2.metric("Критично", high)
    c3.metric("Важно", medium)
    c4.metric("Желательно", low)
    st.progress(min(max(result.score, 0), 100) / 100)
    st.caption("Индекс показывает приоритеты по нашей модели и не является абсолютной SEO-истиной.")

    st.subheader("Приоритет проблем")
    for issue in sorted_issues(result)[:16]:
        priority_label = PRIORITY_LABELS.get(issue.priority, issue.priority)
        priority_class = {
            "HIGH": "issue-priority-high",
            "MEDIUM": "issue-priority-medium",
            "LOW": "issue-priority-low",
        }.get(issue.priority, "issue-priority-low")
        title_safe = html.escape(str(issue.title))
        category_safe = html.escape(str(issue.category))
        rec_safe = html.escape(str(issue.recommendation))
        st.markdown(
            f"""
            <div class="issue-card">
              <div class="issue-head">
                <span class="issue-priority {priority_class}">{priority_label}</span>
                <span class="issue-title">- {title_safe}</span>
              </div>
              <div class="issue-meta">Категория | {category_safe} | Приоритет | {priority_label}</div>
              <div class="issue-rec">- {rec_safe}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.subheader("Метрики")
    st.json(result.metrics)

    st.subheader("Глубина и источники анализа")
    source_flags = []
    if st.session_state.get("query_audit"):
        source_flags.append("query/intent аудит")
    if st.session_state.get("competitor_benchmark"):
        source_flags.append("данные конкурентов")
    if st.session_state.get("changelog"):
        source_flags.append("история изменений")
    if not source_flags:
        source_flags.append("базовые on-page эвристики")
    st.markdown(f"- Использованы источники: {', '.join(source_flags)}.")
    st.markdown("- Для продакшн-решений дополнительно подключайте GSC/GA4 и performance-данные.")

    st.subheader("Внешние данные (интеграции)")
    pagespeed_data = st.session_state.get("integration_pagespeed_data", {})
    gsc_api_data = st.session_state.get("integration_gsc_api_data", {})
    ga4_api_data = st.session_state.get("integration_ga4_api_data", {})
    gsc_data = st.session_state.get("integration_gsc_data", {})
    ga4_data = st.session_state.get("integration_ga4_data", {})

    if pagespeed_data:
        if bool(pagespeed_data.get("ok")):
            st.markdown("**PageSpeed API**")
            scores = pagespeed_data.get("scores", {}) or {}
            ps1, ps2, ps3, ps4 = st.columns(4)
            ps1.metric("Performance", scores.get("performance", "—"))
            ps2.metric("SEO", scores.get("seo", "—"))
            ps3.metric("Accessibility", scores.get("accessibility", "—"))
            ps4.metric("Best Practices", scores.get("best-practices", "—"))
            cwv = pagespeed_data.get("field_core_web_vitals", {}) or {}
            lab = pagespeed_data.get("lab_metrics", {}) or {}
            st.caption(
                f"CWV field: LCP {cwv.get('field_lcp_ms', '—')} ms | "
                f"INP {cwv.get('field_inp_ms', '—')} ms | CLS {cwv.get('field_cls', '—')}"
            )
            st.caption(
                f"Lab: FCP {lab.get('fcp_ms', '—')} ms | "
                f"LCP {lab.get('lcp_ms', '—')} ms | TBT {lab.get('tbt_ms', '—')} ms"
            )
        else:
            st.warning(str(pagespeed_data.get("error", "PageSpeed данные недоступны.")))
    else:
        st.info("PageSpeed API не подключен.")

    if gsc_api_data:
        if bool(gsc_api_data.get("ok")):
            st.markdown(
                f"**GSC API**: клики {gsc_api_data.get('total_clicks', 0)}, "
                f"показы {gsc_api_data.get('total_impressions', 0)}, CTR {gsc_api_data.get('avg_ctr', 0)}%, "
                f"средняя позиция {gsc_api_data.get('avg_position', '—')}."
            )
        else:
            st.warning(str(gsc_api_data.get("error", "GSC API данные недоступны.")))
    elif gsc_data:
        if bool(gsc_data.get("ok")):
            st.markdown(
                f"**GSC CSV**: клики {gsc_data.get('total_clicks', 0)}, "
                f"показы {gsc_data.get('total_impressions', 0)}, CTR {gsc_data.get('avg_ctr', 0)}%, "
                f"средняя позиция {gsc_data.get('avg_position', '—')}."
            )
        else:
            st.warning(str(gsc_data.get("error", "GSC данные недоступны.")))
    if ga4_api_data:
        if bool(ga4_api_data.get("ok")):
            st.markdown(
                f"**GA4 API**: сеансы {ga4_api_data.get('total_sessions', 0)}, "
                f"пользователи {ga4_api_data.get('total_users', 0)}, "
                f"конверсии {ga4_api_data.get('total_conversions', 0)}."
            )
        else:
            st.warning(str(ga4_api_data.get("error", "GA4 API данные недоступны.")))
    elif ga4_data:
        if bool(ga4_data.get("ok")):
            st.markdown(
                f"**GA4 CSV**: сеансы {ga4_data.get('total_sessions', 0)}, "
                f"пользователи {ga4_data.get('total_users', 0)}, "
                f"конверсии {ga4_data.get('total_conversions', 0)}."
            )
        else:
            st.warning(str(ga4_data.get("error", "GA4 данные недоступны.")))

    one_page = build_one_page_report(result, brand_name=str(_settings()["brand"]))
    st.session_state["one_page_report_md"] = one_page
    report_json = json.dumps({**asdict(result), "issues": [asdict(i) for i in result.issues]}, ensure_ascii=False, indent=2)

    st.subheader("Экспорт")
    _prepare_download("export_md", "отчет .md", st.session_state["analysis_report_md"], "seo_report.md", "text/markdown")
    _prepare_download("export_json", "отчет .json", report_json, "seo_report.json", "application/json")
    try:
        pdf_bytes = markdown_to_pdf_bytes(one_page, title="SEO One-Page")
        _prepare_download("export_pdf", "one-page .pdf", pdf_bytes, "seo_one_page.pdf", "application/pdf")
    except RuntimeError as error:
        st.warning(str(error))


def render_action_lab_page() -> None:
    action_pack = st.session_state.get("action_pack", {})
    if not action_pack:
        st.info("Action Pack появится после анализа.")
        return

    playbook = action_pack.get("problem_playbook", []) or []
    query_audit_rows = st.session_state.get("query_audit", []) or action_pack.get("query_audit", []) or []
    meta_variants = action_pack.get("meta_title_description_variants", []) or []
    json_ld_templates = action_pack.get("json_ld_templates", {}) or {}
    outline = action_pack.get("h1_h2_outline", {}) or {}
    content_brief = action_pack.get("content_brief", {}) or {}
    additions = action_pack.get("what_to_add_on_page", []) or []
    internal_links = action_pack.get("internal_link_suggestions", []) or []
    dev_tickets = action_pack.get("dev_tickets", []) or []
    indexation_summary = action_pack.get("indexation_summary", {}) or {}
    data_sources_summary = action_pack.get("data_sources_summary", {}) or {}
    integrations = action_pack.get("integrations", {}) or {}

    st.markdown(
        """
        <div class="section-card">
          <h3>Action Lab</h3>
          <p>Готовые действия для контента и разработки: от проблем к внедрению и проверке.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Проблем", len(playbook))
    m2.metric("Query audit", len(query_audit_rows))
    m3.metric("Внутренние ссылки", len(internal_links))
    m4.metric("Dev tickets", len(dev_tickets))

    tab_exec, tab_content, tab_dev = st.tabs(["План действий", "Контент и структура", "Dev и экспорт"])

    with tab_exec:
        st.subheader("Problem -> Evidence -> Why -> Fix -> Verify")
        if not playbook:
            st.markdown('<div class="al-empty">Данных пока нет. Запустите аудит, и здесь появится план исправлений.</div>', unsafe_allow_html=True)
        for idx, item in enumerate(playbook, start=1):
            priority = str(item.get("priority", "LOW"))
            priority_class = {
                "HIGH": "al-chip-high",
                "MEDIUM": "al-chip-medium",
                "LOW": "al-chip-low",
            }.get(priority, "al-chip-low")
            priority_label = PRIORITY_LABELS.get(priority, priority)
            st.markdown(
                f"""
                <div class="al-card">
                  <span class="al-chip {priority_class}">{priority_label}</span>
                  <p class="al-title">{idx}. {html.escape(str(item.get("problem", "")))}</p>
                  <p class="al-sub">Категория | {html.escape(str(item.get("category", "")))} | Приоритет | {priority_label}</p>
                  <p class="al-text"><b>Доказательство:</b> {html.escape(str(item.get("evidence", "")))}</p>
                  <p class="al-text"><b>Почему важно:</b> {html.escape(str(item.get("why_it_matters", "")))}</p>
                  <p class="al-text"><b>Что исправить:</b> {html.escape(str(item.get("what_to_fix", "")))}</p>
                  <p class="al-text"><b>Готовый патч:</b> {html.escape(str(item.get("ready_patch", "")))}</p>
                  <p class="al-text"><b>Как проверить:</b> {html.escape(str(item.get("post_release_check", "")))}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.subheader("Query / Intent Audit")
        if not query_audit_rows:
            st.markdown('<div class="al-empty">Query/intent данные пока отсутствуют.</div>', unsafe_allow_html=True)
        for row in query_audit_rows:
            status_raw = str(row.get("status", "unknown"))
            status_map = {"covered": "покрыт", "partial": "частично", "gap": "пробел"}
            status_label = status_map.get(status_raw, status_raw)
            st.markdown(
                f"""
                <div class="al-card">
                  <p class="al-title">{html.escape(str(row.get("query", "—")))}</p>
                  <p class="al-sub">Статус | {html.escape(status_label)} | Покрытие | {html.escape(str(row.get("coverage_score", "—")))}%</p>
                  <p class="al-text"><b>Что добавить:</b> {html.escape(str(row.get("recommendation", "—")))}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.subheader("Индексация и рендер")
        if indexation_summary:
            st.markdown('<div class="al-card">', unsafe_allow_html=True)
            st.markdown(f"**Вердикт:** {indexation_summary.get('verdict', '—')}")
            checks = indexation_summary.get("checks", []) or []
            for check in checks:
                name = html.escape(str(check.get("name", "—")))
                value = html.escape(str(check.get("value", "—")))
                st.markdown(f"- **{name}:** {value}")
            st.markdown(
                f"**Как проверить после релиза:** {indexation_summary.get('post_release_check', '—')}"
            )
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.markdown('<div class="al-empty">Данные индексации отсутствуют.</div>', unsafe_allow_html=True)

        st.subheader("Данные и ограничения модели")
        if data_sources_summary:
            st.markdown('<div class="al-card">', unsafe_allow_html=True)
            st.markdown(f"- Тип оценки: **{html.escape(str(data_sources_summary.get('score_type', 'heuristic')))}**")
            st.markdown(f"- Режим анализа: **{html.escape(str(data_sources_summary.get('analysis_mode', 'n/a')))}**")
            st.markdown(
                f"- Query audit строк: **{html.escape(str(data_sources_summary.get('query_audit_rows', 0)))}**"
            )
            ext_ok = bool(data_sources_summary.get("has_external_competitor_data", False))
            st.markdown(f"- Внешние конкурентные данные: **{'доступны' if ext_ok else 'не подключены'}**")
            for note in data_sources_summary.get("notes", []) or []:
                st.markdown(f"- {note}")
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.markdown('<div class="al-empty">Сводка источников данных пока отсутствует.</div>', unsafe_allow_html=True)

        st.subheader("Внешние интеграции")
        pagespeed_data = integrations.get("pagespeed", {}) if isinstance(integrations, dict) else {}
        gsc_api_data = integrations.get("gsc_api", {}) if isinstance(integrations, dict) else {}
        ga4_api_data = integrations.get("ga4_api", {}) if isinstance(integrations, dict) else {}
        gsc_data = integrations.get("gsc_csv", {}) if isinstance(integrations, dict) else {}
        ga4_data = integrations.get("ga4_csv", {}) if isinstance(integrations, dict) else {}

        if pagespeed_data:
            if bool(pagespeed_data.get("ok")):
                st.markdown('<div class="al-card">', unsafe_allow_html=True)
                st.markdown(
                    f"**PageSpeed** ({pagespeed_data.get('strategy', 'mobile')}): "
                    f"Performance {pagespeed_data.get('scores', {}).get('performance', '—')} | "
                    f"SEO {pagespeed_data.get('scores', {}).get('seo', '—')}"
                )
                for opp in pagespeed_data.get("opportunities", [])[:5]:
                    st.markdown(f"- {opp.get('title', '—')}: {opp.get('display_value', '—')}")
                st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.warning(str(pagespeed_data.get("error", "PageSpeed данные недоступны.")))
        else:
            st.info("PageSpeed не подключен.")

        if gsc_api_data:
            if bool(gsc_api_data.get("ok")):
                st.markdown(
                    f"**GSC API**: клики {gsc_api_data.get('total_clicks', 0)} | "
                    f"показы {gsc_api_data.get('total_impressions', 0)} | "
                    f"CTR {gsc_api_data.get('avg_ctr', 0)}% | "
                    f"позиция {gsc_api_data.get('avg_position', '—')}."
                )
                top_queries = gsc_api_data.get("top_queries_by_clicks", []) or []
                for row in top_queries[:5]:
                    st.markdown(f"- Query: {row.get('name', '—')} ({row.get('value', 0)} кликов)")
            else:
                st.warning(str(gsc_api_data.get("error", "GSC API данные недоступны.")))
        elif gsc_data:
            if bool(gsc_data.get("ok")):
                st.markdown(
                    f"**GSC**: клики {gsc_data.get('total_clicks', 0)} | "
                    f"показы {gsc_data.get('total_impressions', 0)} | "
                    f"CTR {gsc_data.get('avg_ctr', 0)}%."
                )
            else:
                st.warning(str(gsc_data.get("error", "GSC данные недоступны.")))
        if ga4_api_data:
            if bool(ga4_api_data.get("ok")):
                st.markdown(
                    f"**GA4 API**: сеансы {ga4_api_data.get('total_sessions', 0)} | "
                    f"пользователи {ga4_api_data.get('total_users', 0)} | "
                    f"конверсии {ga4_api_data.get('total_conversions', 0)}."
                )
                top_pages = ga4_api_data.get("top_landing_pages_by_sessions", []) or []
                for row in top_pages[:5]:
                    st.markdown(f"- Landing page: {row.get('name', '—')} ({row.get('value', 0)} сеансов)")
            else:
                st.warning(str(ga4_api_data.get("error", "GA4 API данные недоступны.")))
        elif ga4_data:
            if bool(ga4_data.get("ok")):
                st.markdown(
                    f"**GA4**: сеансы {ga4_data.get('total_sessions', 0)} | "
                    f"пользователи {ga4_data.get('total_users', 0)} | "
                    f"конверсии {ga4_data.get('total_conversions', 0)}."
                )
            else:
                st.warning(str(ga4_data.get("error", "GA4 данные недоступны.")))

    with tab_content:
        st.subheader("Meta title / description (3 варианта)")
        if not meta_variants:
            st.markdown('<div class="al-empty">Варианты мета пока не сформированы.</div>', unsafe_allow_html=True)
        for idx, row in enumerate(meta_variants, start=1):
            st.markdown(
                f"""
                <div class="al-card">
                  <p class="al-title">Вариант {idx}</p>
                  <p class="al-kv"><b>Title:</b> {html.escape(str(row.get("title", "")))}</p>
                  <p class="al-kv"><b>Description:</b> {html.escape(str(row.get("description", "")))}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.subheader("H1 / H2 Outline")
        h1 = str(outline.get("h1", ""))
        h2_items = outline.get("h2_outline", []) or []
        st.markdown(
            f"""
            <div class="al-card">
              <p class="al-kv"><b>H1:</b> {html.escape(h1)}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if h2_items:
            for item in h2_items:
                st.markdown(f"- {item}")

        st.subheader("Content Brief")
        if content_brief:
            st.markdown('<div class="al-card">', unsafe_allow_html=True)
            for key, value in content_brief.items():
                if isinstance(value, list):
                    st.markdown(f"**{key}**")
                    for list_item in value:
                        st.markdown(f"- {list_item}")
                else:
                    st.markdown(f"**{key}**: {value}")
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.markdown('<div class="al-empty">Content brief пока не сформирован.</div>', unsafe_allow_html=True)

        st.subheader("Что добавить на страницу")
        if additions:
            st.markdown('<div class="al-card">', unsafe_allow_html=True)
            for item in additions:
                st.markdown(f"- {item}")
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.markdown('<div class="al-empty">Дополнения не требуются.</div>', unsafe_allow_html=True)

        st.subheader("JSON-LD шаблоны")
        if not json_ld_templates:
            st.markdown('<div class="al-empty">JSON-LD шаблоны отсутствуют.</div>', unsafe_allow_html=True)
        for name, payload in json_ld_templates.items():
            with st.expander(name):
                st.code(str(payload), language="json")

    with tab_dev:
        st.subheader("Внутренние ссылки")
        if not internal_links:
            st.markdown('<div class="al-empty">Рекомендации по внутренним ссылкам отсутствуют.</div>', unsafe_allow_html=True)
        for row in internal_links:
            st.markdown(
                f"""
                <div class="al-card">
                  <p class="al-kv"><b>Анкор:</b> {html.escape(str(row.get("anchor", "—")))}</p>
                  <p class="al-kv"><b>Куда:</b> {html.escape(str(row.get("target_url", "—")))}</p>
                  <p class="al-kv"><b>Где разместить:</b> {html.escape(str(row.get("placement", "—")))}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.subheader("Dev tickets")
        if not dev_tickets:
            st.markdown('<div class="al-empty">Dev tickets пока отсутствуют.</div>', unsafe_allow_html=True)
        for ticket in dev_tickets:
            priority = str(ticket.get("priority", "LOW"))
            priority_class = {
                "HIGH": "al-chip-high",
                "MEDIUM": "al-chip-medium",
                "LOW": "al-chip-low",
            }.get(priority, "al-chip-low")
            priority_label = PRIORITY_LABELS.get(priority, priority)
            st.markdown(
                f"""
                <div class="al-card">
                  <span class="al-chip {priority_class}">{priority_label}</span>
                  <p class="al-title">{html.escape(str(ticket.get("ticket_id", "SEO-XXX")))} — {html.escape(str(ticket.get("title", "")))}</p>
                  <p class="al-text"><b>Критерий приемки:</b> {html.escape(str(ticket.get("acceptance_criteria", "")))}</p>
                  <p class="al-text"><b>Заметки:</b> {html.escape(str(ticket.get("implementation_notes", "")))}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

    _prepare_download(
        "export_tickets_md",
        "dev tickets (.md)",
        build_dev_tickets_markdown(dev_tickets),
        "seo_dev_tickets.md",
        "text/markdown",
    )
    _prepare_download(
        "export_action_json",
        "action pack (.json)",
        json.dumps(action_pack, ensure_ascii=False, indent=2),
        "seo_action_pack.json",
        "application/json",
    )

    benchmark = st.session_state.get("competitor_benchmark", {})
    if benchmark:
        st.subheader("Конкурентный бенчмарк")
        rows = benchmark.get("rows", []) or []
        for row in rows:
            row_url = html.escape(str(row.get("url", "—")))
            row_score = html.escape(str(row.get("score", "—")))
            row_status = html.escape(str(row.get("status", "—")))
            row_indexability = html.escape(str(row.get("indexability_status", "n/a")))
            row_cta = html.escape(str(row.get("cta_status", "n/a")))
            row_flag = "Целевая страница" if bool(row.get("is_target")) else "Конкурент"
            st.markdown(
                f"""
                <div class="al-card">
                  <p class="al-kv"><b>{row_flag}:</b> {row_url}</p>
                  <p class="al-kv"><b>Эвристический индекс:</b> {row_score} | <b>Статус:</b> {row_status}</p>
                  <p class="al-kv"><b>Indexability:</b> {row_indexability} | <b>CTA:</b> {row_cta}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        insights = benchmark.get("insights", []) or []
        if insights:
            st.markdown('<div class="al-card">', unsafe_allow_html=True)
            st.markdown("**Инсайты**")
            for item in insights:
                st.markdown(f"- {item}")
            st.markdown("</div>", unsafe_allow_html=True)


def render_history_page() -> None:
    changelog = st.session_state.get("changelog", [])
    alerts = st.session_state.get("alerts", [])
    if changelog:
        st.subheader("Changelog")
        for item in changelog:
            st.write(f"- {item}")
        _prepare_download(
            "export_changelog_md",
            "changelog (.md)",
            _build_changelog_markdown(changelog),
            "seo_changelog.md",
            "text/markdown",
        )
    else:
        st.info("История изменений пока пуста.")

    if alerts:
        st.subheader("Alerts")
        for item in alerts:
            st.warning(item)
        webhook = str(_settings()["webhook_url"]).strip()
        if webhook and st.button("Отправить Alerts в webhook"):
            ok, msg = _send_webhook(webhook, {"source": st.session_state.get("analysis_source", ""), "alerts": alerts})
            st.success(msg) if ok else st.error(msg)
    else:
        st.success("Алертов нет.")


def render_ai_studio_page() -> None:
    result: AnalysisResult | None = st.session_state.get("analysis_result")
    if not result:
        st.info("Сначала выполните аудит.")
        return

    settings = _settings()
    provider = str(settings["ai_provider"])
    model = str(settings["openai_model"]) if provider == "OpenAI" else str(settings["ollama_model"])
    api_key = str(settings["openai_key"])
    ollama_url = str(settings["ollama_base_url"])
    article_text = st.session_state.get("analysis_text", "")

    col1, col2 = st.columns(2)
    with col1:
        rec_click = st.button("Сгенерировать AI-рекомендации", type="primary")
    with col2:
        txt_click = st.button("Сгенерировать улучшенный текст")

    if provider == "Без AI":
        st.info("Выберите AI-провайдера в разделе «Настройки».")
        return
    if provider == "OpenAI" and not api_key:
        st.warning("Нужен OpenAI API key.")
        return
    if provider.startswith("Ollama"):
        ok, msg = _check_ollama_available(ollama_url)
        if not ok:
            st.warning(msg)
            return

    if rec_click and _consume_action(ACTION_AI):
        render_loader("Генерируем AI-рекомендации...")
        if provider == "OpenAI":
            st.session_state["ai_recommendations"] = generate_ai_recommendations(result, api_key, model) or ""
        else:
            st.session_state["ai_recommendations"] = generate_ai_recommendations_ollama(result, model, ollama_url) or ""

    if txt_click:
        if not article_text.strip():
            st.warning("Нет исходного текста для переработки.")
        elif _consume_action(ACTION_AI):
            issues_summary = [f"{i.priority}: {i.title}. {i.recommendation}" for i in sorted_issues(result)]
            render_loader("Генерируем варианты текста...")
            if provider == "OpenAI":
                st.session_state["ai_variants"] = generate_improved_text_variants(
                    source_text=article_text,
                    issues_summary=issues_summary,
                    keywords=st.session_state.get("analysis_keywords", []),
                    api_key=api_key,
                    model=model,
                ) or ""
            else:
                st.session_state["ai_variants"] = generate_improved_text_variants_ollama(
                    source_text=article_text,
                    issues_summary=issues_summary,
                    keywords=st.session_state.get("analysis_keywords", []),
                    model=model,
                    base_url=ollama_url,
                ) or ""

    if st.session_state.get("ai_recommendations"):
        st.subheader("AI-рекомендации")
        st.markdown(st.session_state["ai_recommendations"])
    if st.session_state.get("ai_variants"):
        st.subheader("AI-варианты улучшенного текста")
        st.markdown(st.session_state["ai_variants"])


def render_billing_page() -> None:
    user = _current_user()
    sub = get_subscription(user) if user else None
    provider = payment_provider_status()

    st.markdown(
        """
        <div class="section-card">
          <h3>Тарифы</h3>
          <p>Выберите план под ваш объем задач: от быстрого старта до enterprise-масштаба.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="section-card">
          <h3>Почему это окупается</h3>
          <p>Меньше ручной рутины, больше управляемых SEO-действий: аудит, приоритеты, action-план и клиентский отчет в одном кабинете.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    mode_text = "demo" if provider["provider"] == PAYMENT_PROVIDER_DEMO else "payment links"
    mode_hint = (
        "Демо-режим: заказ подтверждается вручную в интерфейсе."
        if provider["provider"] == PAYMENT_PROVIDER_DEMO
        else "Режим платежных ссылок: пользователь переходит на внешнюю оплату."
    )
    st.info(f"Платежный режим: `{mode_text}`. {mode_hint}")
    if not bool(provider["configured"]):
        st.error(str(provider["message"]))

    if sub:
        status = str(sub.get("status", "unknown"))
        if status == "active":
            st.success(
                f"Ваш активный тариф: {sub.get('plan_title')} · "
                f"{sub.get('price_rub_display') or (str(sub.get('price_rub')) + ' ₽ / мес')}"
            )
        else:
            st.warning(f"Подписка найдена, но не активна (status={status}).")
    else:
        st.info("Подписка еще не подключена.")

    plan_copy = {
        "starter": {
            "badge": "Start fast",
            "tagline": "Для фриланса и первого продукта: быстро запустить аудит и получить план улучшений.",
        },
        "growth": {
            "badge": "Best value",
            "tagline": "Для малого бизнеса: постоянный поток задач, AI-автоматизация и weekly-отчеты.",
        },
        "pro": {
            "badge": "Team scale",
            "tagline": "Для команд и агентств: несколько брендов, white-label и глубокая аналитика.",
        },
        "agency": {
            "badge": "Enterprise",
            "tagline": "Для крупных команд: API, роли, клиентские кабинеты и приоритетная поддержка.",
        },
    }

    plan_items = list(PLANS.items())
    cols = st.columns(len(plan_items))
    button_items: list[dict[str, object]] = []
    for idx, (plan_id, plan) in enumerate(plan_items):
        info = plan_copy.get(plan_id, {"badge": "Тариф", "tagline": ""})
        is_recommended = plan_id == "growth"
        is_active = bool(sub and sub.get("plan_id") == plan_id and sub.get("status") == "active")
        badge = info["badge"]
        if is_recommended:
            badge = "Рекомендуем"
        features_html = "".join(f"<div class='plan-feature'>• {feature}</div>" for feature in plan.features)
        limits_html = "".join(
            f"<div class='plan-feature'>• {ACTION_LABELS.get(action, action)}: {'∞' if limit < 0 else limit}</div>"
            for action, limit in plan.limits.items()
        )
        card_class = "plan-card plan-card-highlight" if is_recommended else "plan-card"

        with cols[idx]:
            st.markdown(
                f"""
                <div class="{card_class}">
                  <div class="plan-head">
                    <div class="plan-title">{plan.title}</div>
                    <div class="plan-badge">{badge}</div>
                  </div>
                  <div class="plan-price">{plan.price_rub_display}</div>
                  <div class="plan-period">{plan.price_usdt_display}</div>
                  <div class="plan-copy">
                    <div class="plan-tagline">{info["tagline"]}</div>
                    <div class="plan-tagline">{plan.description}</div>
                  </div>
                  <div class="plan-features">{features_html}</div>
                  <div class="plan-limits">
                    <div class="plan-muted">Лимиты в месяц:</div>
                    {limits_html}
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            button_items.append(
                {
                    "plan_id": plan_id,
                    "plan_title": plan.title,
                    "is_active": is_active,
                }
            )

    button_cols = st.columns(len(plan_items))
    for idx, item in enumerate(button_items):
        plan_id = str(item["plan_id"])
        plan_title = str(item["plan_title"])
        is_active = bool(item["is_active"])
        btn_label = "Тариф активен" if is_active else f"Оформить {plan_title}"
        with button_cols[idx]:
            if st.button(btn_label, key=f"activate_plan_{plan_id}", use_container_width=True, disabled=is_active):
                if not user:
                    st.error("Сначала войдите в аккаунт.")
                else:
                    ok, payload = create_checkout_order(user, plan_id)
                    if not ok:
                        st.error(str(payload))
                    else:
                        order = dict(payload)
                        st.success(f"Заказ {order['order_id']} создан.")
                        if order["provider"] == PAYMENT_PROVIDER_LINKS and order["checkout_url"]:
                            st.link_button("Перейти к оплате", str(order["checkout_url"]), use_container_width=True)
                        else:
                            st.caption("Это demo checkout.")
                        st.rerun()

    if sub and sub.get("status") == "active":
        if st.button("Приостановить подписку", use_container_width=False):
            set_subscription(user, str(sub.get("plan_id")), status="paused")
            st.warning("Подписка приостановлена.")
            st.rerun()

    st.subheader("Заказы оплаты")
    orders = list_checkout_orders(user, limit=25) if user else []
    if not orders:
        st.caption("Заказов пока нет.")
    else:
        for order in orders:
            order_status = str(order["status"])
            order_plan = PLANS.get(str(order["plan_id"]), PLANS["starter"]).title
            st.markdown(
                f"""
                <div class="order-table">
                  <div class="status-title">{order["order_id"]} · {order_plan} · {order["amount_rub"]} ₽</div>
                  <div class="status-text">Статус: {order_status} · Провайдер: {order["provider"]} · Создан: {_format_datetime_value(order["created_at"])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            c1, c2, c3 = st.columns(3)
            if order["status"] == "pending":
                if str(order["provider"]) == PAYMENT_PROVIDER_LINKS and str(order["checkout_url"]).strip():
                    c1.link_button("Открыть оплату", str(order["checkout_url"]), use_container_width=True)
                if bool(provider["manual_confirmation"]):
                    if c2.button("Подтвердить оплату", key=f"confirm_order_{order['order_id']}", use_container_width=True):
                        ok, message = confirm_checkout_order(user, str(order["order_id"]), payment_ref="manual-confirm")
                        st.success(message) if ok else st.error(message)
                        st.rerun()
                if c3.button("Отменить заказ", key=f"cancel_order_{order['order_id']}", use_container_width=True):
                    ok, message = cancel_checkout_order(user, str(order["order_id"]))
                    st.success(message) if ok else st.error(message)
                    st.rerun()

    usage = usage_snapshot(user) if user else []
    if usage:
        st.subheader("Текущая утилизация лимитов")
        render_usage_table(usage)


def main() -> None:
    st.set_page_config(page_title="SEO Control Hub", layout="wide")

    init_auth_db()
    init_billing_db()
    init_session_state()
    _is_authenticated()
    _restore_auth_from_persistent_token()
    inject_ui_styles()
    inject_motion_script()
    render_app_header()

    if not render_auth_gate():
        st.stop()

    inject_post_auth_form_styles()

    if st.session_state.get("nav_page") not in APP_PAGES:
        st.session_state["nav_page"] = DASHBOARD_PAGE
    if st.session_state.get("page_menu") not in MENU_PAGES:
        st.session_state["page_menu"] = DASHBOARD_PAGE
    if st.session_state.get("nav_page") in MENU_PAGES:
        st.session_state["page_menu"] = st.session_state["nav_page"]

    render_sidebar()
    page = st.session_state.get("nav_page", APP_PAGES[0])
    main_area = st.container()
    with main_area:
        if not _active_subscription() and page in BLOCKED_WITHOUT_SUBSCRIPTION:
            st.warning("Доступ к этому разделу требует активной подписки.")
            render_billing_page()
        else:
            if page == "Дашборд":
                render_dashboard()
            elif page == "Новый аудит":
                render_new_audit_page()
            elif page == "Результат":
                render_result_page()
            elif page == "Action Lab":
                render_action_lab_page()
            elif page == "История":
                render_history_page()
            elif page == "AI Studio":
                render_ai_studio_page()
            elif page == "Тарифы":
                render_billing_page()
            elif page == "Профиль":
                render_profile_page()
            elif page == "Настройки":
                render_settings_page()
        st.markdown('<div class="app-bottom-gap"></div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()




