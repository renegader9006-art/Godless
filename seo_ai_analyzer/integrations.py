from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

import requests

PAGESPEED_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def fetch_pagespeed_data(url: str, api_key: str, strategy: str = "mobile", timeout: int = 25) -> dict[str, Any]:
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "error": "PageSpeed: нужен корректный URL (http/https)."}
    if not api_key.strip():
        return {"ok": False, "error": "PageSpeed: API key не задан."}

    params = {
        "url": url.strip(),
        "strategy": strategy if strategy in {"mobile", "desktop"} else "mobile",
        "key": api_key.strip(),
    }
    try:
        response = requests.get(PAGESPEED_API_URL, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as error:
        return {"ok": False, "error": f"PageSpeed request error: {error}"}
    except ValueError:
        return {"ok": False, "error": "PageSpeed: не удалось разобрать JSON-ответ."}

    lighthouse = payload.get("lighthouseResult", {}) or {}
    categories = lighthouse.get("categories", {}) or {}
    audits = lighthouse.get("audits", {}) or {}
    loading_exp = payload.get("loadingExperience", {}) or {}
    field_metrics = loading_exp.get("metrics", {}) or {}

    scores = {}
    for key in ("performance", "seo", "accessibility", "best-practices"):
        score_value = categories.get(key, {}).get("score")
        if isinstance(score_value, (int, float)):
            scores[key] = round(float(score_value) * 100, 1)
        else:
            scores[key] = None

    lab_metrics = {
        "fcp_ms": _audit_numeric(audits, "first-contentful-paint"),
        "lcp_ms": _audit_numeric(audits, "largest-contentful-paint"),
        "tbt_ms": _audit_numeric(audits, "total-blocking-time"),
        "cls": _audit_numeric(audits, "cumulative-layout-shift"),
        "speed_index_ms": _audit_numeric(audits, "speed-index"),
    }
    field_cwv = {
        "field_lcp_ms": _field_metric_percentile(field_metrics, "LARGEST_CONTENTFUL_PAINT_MS"),
        "field_inp_ms": _field_metric_percentile(field_metrics, "EXPERIMENTAL_INTERACTION_TO_NEXT_PAINT"),
        "field_cls": _field_metric_percentile(field_metrics, "CUMULATIVE_LAYOUT_SHIFT_SCORE"),
        "field_fcp_ms": _field_metric_percentile(field_metrics, "FIRST_CONTENTFUL_PAINT_MS"),
    }

    opportunities: list[dict[str, Any]] = []
    for item in audits.values():
        details = item if isinstance(item, dict) else {}
        title = str(details.get("title", "")).strip()
        score = details.get("score")
        display_value = str(details.get("displayValue", "")).strip()
        if not title:
            continue
        if isinstance(score, (int, float)) and float(score) < 0.9 and display_value:
            opportunities.append(
                {
                    "title": title,
                    "score": round(float(score), 3),
                    "display_value": display_value,
                }
            )
    opportunities.sort(key=lambda row: row.get("score", 1.0))

    return {
        "ok": True,
        "source": "pagespeed_api_v5",
        "url": url.strip(),
        "strategy": params["strategy"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "scores": scores,
        "lab_metrics": lab_metrics,
        "field_core_web_vitals": field_cwv,
        "opportunities": opportunities[:8],
    }


def parse_gsc_csv(csv_bytes: bytes) -> dict[str, Any]:
    if not csv_bytes:
        return {"ok": False, "error": "GSC CSV пустой."}

    rows = _read_csv_rows(csv_bytes)
    if not rows:
        return {"ok": False, "error": "GSC CSV не содержит строк."}

    query_col = _pick_column(rows[0].keys(), ("query", "запрос"))
    page_col = _pick_column(rows[0].keys(), ("page", "страница"))
    clicks_col = _pick_column(rows[0].keys(), ("click", "клики"))
    impressions_col = _pick_column(rows[0].keys(), ("impression", "показы"))
    ctr_col = _pick_column(rows[0].keys(), ("ctr",))
    position_col = _pick_column(rows[0].keys(), ("position", "позиция"))

    if not (clicks_col and impressions_col):
        return {"ok": False, "error": "GSC CSV: нужны колонки clicks/impressions (или Клики/Показы)."}

    total_clicks = 0.0
    total_impressions = 0.0
    weighted_position_sum = 0.0
    weighted_ctr_sum = 0.0
    valid_ctr_weight = 0.0
    queries: list[tuple[str, float]] = []
    pages: list[tuple[str, float]] = []

    for row in rows:
        clicks = _to_float(row.get(clicks_col))
        impressions = _to_float(row.get(impressions_col))
        ctr = _to_float(row.get(ctr_col)) if ctr_col else None
        pos = _to_float(row.get(position_col)) if position_col else None

        total_clicks += clicks
        total_impressions += impressions
        if pos is not None and impressions > 0:
            weighted_position_sum += pos * impressions
        if ctr is not None and impressions > 0:
            weighted_ctr_sum += ctr * impressions
            valid_ctr_weight += impressions

        if query_col:
            query = str(row.get(query_col, "")).strip()
            if query:
                queries.append((query, clicks))
        if page_col:
            page = str(row.get(page_col, "")).strip()
            if page:
                pages.append((page, clicks))

    avg_position = (weighted_position_sum / total_impressions) if total_impressions > 0 else None
    if valid_ctr_weight > 0:
        avg_ctr = weighted_ctr_sum / valid_ctr_weight
    elif total_impressions > 0:
        avg_ctr = total_clicks / total_impressions
    else:
        avg_ctr = None

    top_queries = _top_by_value(queries, 7)
    top_pages = _top_by_value(pages, 7)
    return {
        "ok": True,
        "source": "gsc_csv",
        "rows": len(rows),
        "total_clicks": round(total_clicks, 2),
        "total_impressions": round(total_impressions, 2),
        "avg_ctr": round(avg_ctr * 100, 2) if avg_ctr is not None and avg_ctr <= 1 else round(avg_ctr or 0.0, 2),
        "avg_position": round(avg_position, 2) if avg_position is not None else None,
        "top_queries_by_clicks": top_queries,
        "top_pages_by_clicks": top_pages,
    }


def parse_ga4_csv(csv_bytes: bytes) -> dict[str, Any]:
    if not csv_bytes:
        return {"ok": False, "error": "GA4 CSV пустой."}

    rows = _read_csv_rows(csv_bytes)
    if not rows:
        return {"ok": False, "error": "GA4 CSV не содержит строк."}

    page_col = _pick_column(rows[0].keys(), ("landing page", "landing", "page path", "страница входа", "страница"))
    sessions_col = _pick_column(rows[0].keys(), ("session", "сеанс"))
    users_col = _pick_column(rows[0].keys(), ("user", "пользовател"))
    engagement_col = _pick_column(rows[0].keys(), ("engagement rate", "вовлеч"))
    conversions_col = _pick_column(rows[0].keys(), ("conversion", "конверс"))

    if not sessions_col:
        return {"ok": False, "error": "GA4 CSV: нужна колонка sessions (или Сеансы)."}

    total_sessions = 0.0
    total_users = 0.0
    total_conversions = 0.0
    weighted_engagement_sum = 0.0
    engagement_weight = 0.0
    pages: list[tuple[str, float]] = []

    for row in rows:
        sessions = _to_float(row.get(sessions_col))
        users = _to_float(row.get(users_col)) if users_col else 0.0
        conversions = _to_float(row.get(conversions_col)) if conversions_col else 0.0
        engagement = _to_float(row.get(engagement_col)) if engagement_col else None

        total_sessions += sessions
        total_users += users
        total_conversions += conversions
        if engagement is not None and sessions > 0:
            weighted_engagement_sum += engagement * sessions
            engagement_weight += sessions

        if page_col:
            page = str(row.get(page_col, "")).strip()
            if page:
                pages.append((page, sessions))

    avg_engagement = (weighted_engagement_sum / engagement_weight) if engagement_weight > 0 else None
    return {
        "ok": True,
        "source": "ga4_csv",
        "rows": len(rows),
        "total_sessions": round(total_sessions, 2),
        "total_users": round(total_users, 2),
        "total_conversions": round(total_conversions, 2),
        "avg_engagement_rate": round(avg_engagement * 100, 2) if avg_engagement is not None and avg_engagement <= 1 else round(avg_engagement or 0.0, 2),
        "top_landing_pages_by_sessions": _top_by_value(pages, 7),
    }


def fetch_gsc_api_data(
    service_account_json: str,
    site_url: str,
    start_date: str,
    end_date: str,
    row_limit: int = 50,
) -> dict[str, Any]:
    if not service_account_json.strip():
        return {"ok": False, "error": "GSC API: не передан Service Account JSON."}
    if not site_url.strip():
        return {"ok": False, "error": "GSC API: заполните Site URL (например, sc-domain:example.com)."}

    creds_result = _build_service_account_credentials(
        service_account_json,
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    )
    if not bool(creds_result.get("ok")):
        return creds_result
    credentials = creds_result["credentials"]

    try:
        from googleapiclient.discovery import build  # type: ignore
    except ImportError:
        return {"ok": False, "error": "GSC API: установите google-api-python-client и google-auth."}

    request_body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["query", "page"],
        "rowLimit": max(1, min(int(row_limit), 500)),
    }
    try:
        service = build("searchconsole", "v1", credentials=credentials, cache_discovery=False)
        response = (
            service.searchanalytics()
            .query(siteUrl=site_url.strip(), body=request_body)
            .execute()
        )
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": f"GSC API error: {error}"}

    rows = response.get("rows", []) or []
    parsed_rows: list[dict[str, Any]] = []
    total_clicks = 0.0
    total_impressions = 0.0
    weighted_position_sum = 0.0
    for row in rows:
        keys = row.get("keys", []) or []
        query = str(keys[0]) if len(keys) > 0 else ""
        page = str(keys[1]) if len(keys) > 1 else ""
        clicks = float(row.get("clicks", 0.0) or 0.0)
        impressions = float(row.get("impressions", 0.0) or 0.0)
        ctr = float(row.get("ctr", 0.0) or 0.0)
        position = float(row.get("position", 0.0) or 0.0)
        parsed_rows.append(
            {
                "query": query,
                "page": page,
                "clicks": round(clicks, 2),
                "impressions": round(impressions, 2),
                "ctr_pct": round(ctr * 100, 2),
                "position": round(position, 2),
            }
        )
        total_clicks += clicks
        total_impressions += impressions
        weighted_position_sum += position * impressions

    avg_ctr = (total_clicks / total_impressions) if total_impressions > 0 else 0.0
    avg_position = (weighted_position_sum / total_impressions) if total_impressions > 0 else 0.0
    top_queries = _aggregate_top(rows=parsed_rows, key="query", value_key="clicks", limit=7)
    top_pages = _aggregate_top(rows=parsed_rows, key="page", value_key="clicks", limit=7)

    return {
        "ok": True,
        "source": "gsc_api",
        "site_url": site_url.strip(),
        "start_date": start_date,
        "end_date": end_date,
        "rows": len(parsed_rows),
        "total_clicks": round(total_clicks, 2),
        "total_impressions": round(total_impressions, 2),
        "avg_ctr": round(avg_ctr * 100, 2),
        "avg_position": round(avg_position, 2),
        "top_queries_by_clicks": top_queries,
        "top_pages_by_clicks": top_pages,
        "sample_rows": parsed_rows[:20],
    }


def fetch_ga4_api_data(
    service_account_json: str,
    property_id: str,
    start_date: str,
    end_date: str,
    row_limit: int = 50,
) -> dict[str, Any]:
    if not service_account_json.strip():
        return {"ok": False, "error": "GA4 API: не передан Service Account JSON."}
    prop = property_id.strip()
    if not prop:
        return {"ok": False, "error": "GA4 API: укажите Property ID."}
    if prop.startswith("properties/"):
        prop = prop.split("/", 1)[1]

    creds_result = _build_service_account_credentials(
        service_account_json,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    )
    if not bool(creds_result.get("ok")):
        return creds_result
    credentials = creds_result["credentials"]

    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient  # type: ignore
        from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest  # type: ignore
    except ImportError:
        return {"ok": False, "error": "GA4 API: установите google-analytics-data и google-auth."}

    try:
        client = BetaAnalyticsDataClient(credentials=credentials)
        request = RunReportRequest(
            property=f"properties/{prop}",
            dimensions=[Dimension(name="landingPage")],
            metrics=[
                Metric(name="sessions"),
                Metric(name="activeUsers"),
                Metric(name="engagementRate"),
                Metric(name="conversions"),
            ],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            limit=max(1, min(int(row_limit), 250)),
        )
        response = client.run_report(request=request)
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": f"GA4 API error: {error}"}

    rows_data: list[dict[str, Any]] = []
    total_sessions = 0.0
    total_users = 0.0
    total_conversions = 0.0
    weighted_engagement = 0.0

    for row in response.rows:
        page = row.dimension_values[0].value if row.dimension_values else ""
        sessions = _to_float(row.metric_values[0].value if len(row.metric_values) > 0 else 0)
        users = _to_float(row.metric_values[1].value if len(row.metric_values) > 1 else 0)
        engagement = _to_float(row.metric_values[2].value if len(row.metric_values) > 2 else 0)
        conversions = _to_float(row.metric_values[3].value if len(row.metric_values) > 3 else 0)
        rows_data.append(
            {
                "landing_page": page,
                "sessions": round(sessions, 2),
                "active_users": round(users, 2),
                "engagement_rate_pct": round(engagement * 100, 2),
                "conversions": round(conversions, 2),
            }
        )
        total_sessions += sessions
        total_users += users
        total_conversions += conversions
        weighted_engagement += engagement * sessions

    avg_engagement = (weighted_engagement / total_sessions) if total_sessions > 0 else 0.0
    top_pages = _aggregate_top(rows=rows_data, key="landing_page", value_key="sessions", limit=7)

    return {
        "ok": True,
        "source": "ga4_api",
        "property_id": prop,
        "start_date": start_date,
        "end_date": end_date,
        "rows": len(rows_data),
        "total_sessions": round(total_sessions, 2),
        "total_users": round(total_users, 2),
        "total_conversions": round(total_conversions, 2),
        "avg_engagement_rate": round(avg_engagement * 100, 2),
        "top_landing_pages_by_sessions": top_pages,
        "sample_rows": rows_data[:20],
    }


def _audit_numeric(audits: dict[str, Any], key: str) -> float | None:
    value = (audits.get(key, {}) or {}).get("numericValue")
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return None


def _field_metric_percentile(field_metrics: dict[str, Any], key: str) -> float | None:
    metric = field_metrics.get(key, {}) or {}
    value = metric.get("percentile")
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return None


def _decode_csv_bytes(csv_bytes: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            return csv_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return csv_bytes.decode("utf-8", errors="ignore")


def _read_csv_rows(csv_bytes: bytes) -> list[dict[str, str]]:
    text = _decode_csv_bytes(csv_bytes)
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "," if sample.count(",") >= sample.count(";") else ";"

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows: list[dict[str, str]] = []
    for row in reader:
        if not isinstance(row, dict):
            continue
        cleaned = {str(k).strip(): str(v).strip() for k, v in row.items() if k is not None}
        if any(value for value in cleaned.values()):
            rows.append(cleaned)
    return rows


def _pick_column(columns: Any, variants: tuple[str, ...]) -> str | None:
    cols = [str(c).strip() for c in columns]
    cols_lower = {c.lower(): c for c in cols}
    for variant in variants:
        for key_lower, key_original in cols_lower.items():
            if variant in key_lower:
                return key_original
    return None


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    raw = str(value).strip().replace("\u00a0", " ").replace("%", "").replace(" ", "")
    if not raw:
        return 0.0
    if "," in raw and "." in raw:
        raw = raw.replace(",", "")
    else:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _top_by_value(items: list[tuple[str, float]], limit: int) -> list[dict[str, Any]]:
    merged: dict[str, float] = {}
    for key, value in items:
        merged[key] = merged.get(key, 0.0) + value
    out = [{"name": key, "value": round(val, 2)} for key, val in merged.items()]
    out.sort(key=lambda row: float(row["value"]), reverse=True)
    return out[:limit]


def _build_service_account_credentials(service_account_json: str, scopes: list[str]) -> dict[str, Any]:
    try:
        from google.oauth2.service_account import Credentials  # type: ignore
    except ImportError:
        return {"ok": False, "error": "Google API: установите google-auth."}

    try:
        info = json.loads(service_account_json)
        if not isinstance(info, dict):
            return {"ok": False, "error": "Google API: service account JSON имеет неверный формат."}
        credentials = Credentials.from_service_account_info(info, scopes=scopes)
    except json.JSONDecodeError:
        return {"ok": False, "error": "Google API: не удалось разобрать JSON service account."}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": f"Google API credentials error: {error}"}

    return {"ok": True, "credentials": credentials}


def _aggregate_top(rows: list[dict[str, Any]], key: str, value_key: str, limit: int = 7) -> list[dict[str, Any]]:
    agg: dict[str, float] = {}
    for row in rows:
        name = str(row.get(key, "")).strip()
        if not name:
            continue
        value = _to_float(row.get(value_key))
        agg[name] = agg.get(name, 0.0) + value
    data = [{"name": name, "value": round(val, 2)} for name, val in agg.items()]
    data.sort(key=lambda item: float(item["value"]), reverse=True)
    return data[:limit]
