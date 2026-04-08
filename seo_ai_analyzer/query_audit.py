from __future__ import annotations

import re

WORD_RE = re.compile(r'[A-Za-zА-Яа-яЁё0-9]+')


def classify_intent(query: str) -> str:
    q = query.lower().strip()
    if any(token in q for token in ('купить', 'цена', 'стоимость', 'заказать', 'тариф')):
        return 'transactional'
    if any(token in q for token in ('лучший', 'сравнение', 'обзор', 'vs', 'топ')):
        return 'commercial'
    if any(token in q for token in ('войти', 'вход', 'login', 'официальный сайт')):
        return 'navigational'
    return 'informational'


def audit_queries(
    queries: list[str],
    page_text: str,
    title: str,
    h1_text: str,
    h2_texts: list[str],
) -> list[dict[str, str | int | float]]:
    text_lower = page_text.lower()
    title_h1 = f'{title} {h1_text}'.lower()
    h2_joined = ' '.join(h2_texts).lower()
    audit: list[dict[str, str | int | float]] = []

    for raw_query in queries:
        query = raw_query.strip()
        if not query:
            continue

        query_lower = query.lower()
        intent = classify_intent(query)
        token_count = max(len(WORD_RE.findall(query_lower)), 1)

        in_title_h1 = 1 if query_lower in title_h1 else 0
        in_h2 = 1 if query_lower in h2_joined else 0
        in_body = text_lower.count(query_lower)

        token_hits = 0
        for token in WORD_RE.findall(query_lower):
            if token and token in text_lower:
                token_hits += 1

        token_coverage = (token_hits / token_count) * 100
        coverage_score = min(
            100.0,
            (in_title_h1 * 35) + (in_h2 * 20) + min(in_body * 10, 25) + (token_coverage * 0.2),
        )

        status = 'covered'
        if coverage_score < 40:
            status = 'gap'
        elif coverage_score < 70:
            status = 'partial'

        if status == 'gap':
            recommendation = (
                'Добавьте отдельный блок под запрос: уточните заголовок, выделите H2 и дайте практический ответ.'
            )
        elif status == 'partial':
            recommendation = 'Усилите покрытие запроса примерами, FAQ и конкретными шагами.'
        else:
            recommendation = 'Покрытие запроса достаточное, поддерживайте актуальность и факты.'

        audit.append(
            {
                'query': query,
                'intent': intent,
                'coverage_score': round(coverage_score, 2),
                'status': status,
                'in_title_h1': in_title_h1,
                'in_h2': in_h2,
                'body_mentions': in_body,
                'recommendation': recommendation,
            }
        )

    audit.sort(key=lambda item: float(item['coverage_score']))
    return audit
