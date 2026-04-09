from __future__ import annotations

from statistics import median
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from .analyzer import analyze_html
from .fetcher import load_html_from_url
from .models import AnalysisResult


def discover_competitors(
    query: str,
    target_url: str,
    limit: int = 5,
    timeout: int = 12,
) -> list[str]:
    """
    Lightweight SERP discovery via DuckDuckGo HTML endpoint.
    If unavailable, returns an empty list.
    """
    q = query.strip()
    if not q:
        return []

    target_domain = _domain(target_url)
    url = 'https://duckduckgo.com/html/'
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; SEOAnalyzerBot/1.0; +https://example.local)'
    }

    try:
        response = requests.get(url, params={'q': q}, headers=headers, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException:
        return []

    html = response.text
    candidates = _extract_serp_urls(html)

    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if len(out) >= limit:
            break
        normalized = _normalize_candidate(candidate)
        if not normalized:
            continue
        domain = _domain(normalized)
        if not domain or domain == target_domain:
            continue
        if domain.endswith("duckduckgo.com"):
            continue
        if domain in seen:
            continue
        seen.add(domain)
        out.append(normalized)
    return out


def benchmark_against_competitors(
    target_result: AnalysisResult,
    target_url: str,
    competitor_urls: list[str],
    keywords: list[str] | None = None,
) -> dict[str, object]:
    """
    Crawl competitors, run same analyzer and return comparable metrics.
    """
    keywords = keywords or []
    target_metrics = _metric_subset(target_result)

    rows: list[dict[str, object]] = [
        {
            'url': target_url or target_result.source,
            'is_target': True,
            'score': target_result.score,
            **target_metrics,
            'status': 'ok',
        }
    ]

    for url in competitor_urls:
        u = url.strip()
        if not u:
            continue
        try:
            html = load_html_from_url(u)
            res = analyze_html(source=u, html=html, keywords=keywords or None)
            rows.append(
                {
                    'url': u,
                    'is_target': False,
                    'score': res.score,
                    **_metric_subset(res),
                    'status': 'ok',
                }
            )
        except Exception as error:  # noqa: BLE001
            rows.append(
                {
                    'url': u,
                    'is_target': False,
                    'score': 0,
                    'word_count': 0,
                    'internal_links': 0,
                    'h2_count': 0,
                    'intent_coverage_pct': 0,
                    'schema_count': 0,
                    'status': f'error: {error}',
                }
            )

    competitor_rows = [r for r in rows if not bool(r['is_target']) and str(r['status']) == 'ok']
    insights = _build_insights(rows[0], competitor_rows)

    return {
        'rows': rows,
        'insights': insights,
        'competitor_count': len(competitor_rows),
    }


def _metric_subset(result: AnalysisResult) -> dict[str, object]:
    metrics = result.metrics
    return {
        'word_count': int(metrics.get('word_count', 0) or 0),
        'internal_links': int(metrics.get('internal_links', 0) or 0),
        'h2_count': int(metrics.get('h2_count', 0) or 0),
        'intent_coverage_pct': float(metrics.get('intent_coverage_pct', 0) or 0),
        'schema_count': int(metrics.get('schema_count', 0) or 0),
        'indexability_status': str(metrics.get('indexability_status', 'n/a')),
        'cta_status': str(metrics.get('cta_status', 'n/a')),
        'risky_copywriting_hits': int(metrics.get('risky_copywriting_hits', 0) or 0),
    }


def _build_insights(
    target_row: dict[str, object],
    competitor_rows: list[dict[str, object]],
) -> list[str]:
    if not competitor_rows:
        return ['Недостаточно данных конкурентов для сравнения.']

    insights: list[str] = []
    fields = [
        ('score', 'score'),
        ('word_count', 'объем контента'),
        ('internal_links', 'внутренние ссылки'),
        ('h2_count', 'структура H2'),
        ('intent_coverage_pct', 'покрытие интента'),
        ('schema_count', 'schema markup'),
        ('risky_copywriting_hits', 'рискованный copywriting'),
    ]

    for field, label in fields:
        target = float(target_row.get(field, 0) or 0)
        values = [float(row.get(field, 0) or 0) for row in competitor_rows]
        med = median(values) if values else 0.0
        delta = round(target - med, 2)
        if delta >= 0:
            insights.append(f'{label}: +{delta} к медиане конкурентов.')
        else:
            insights.append(f'{label}: {delta} к медиане конкурентов.')

    return insights


def _domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower().strip()


def _extract_serp_urls(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for link in soup.select("a.result__a[href], a[href]"):
        href = (link.get("href") or "").strip()
        if href:
            urls.append(href)
    return urls


def _normalize_candidate(url: str) -> str:
    href = (url or "").strip()
    if not href:
        return ""

    if href.startswith("//"):
        href = f"https:{href}"

    parsed = urlparse(href)
    if href.startswith("/l/?") or (parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/")):
        params = parse_qs(parsed.query)
        target = params.get("uddg", [""])[0]
        href = unquote(target).strip()

    if not href.startswith(("http://", "https://")):
        return ""
    return href
