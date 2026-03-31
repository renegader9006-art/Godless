from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .models import AnalysisResult, SEOIssue

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "were",
    "with",
}


def _clean_text(raw_text: str) -> str:
    text = re.sub(r"\s+", " ", raw_text).strip()
    return text


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9]+", text.lower())
    return [token for token in tokens if token not in STOP_WORDS and len(token) > 2]


def _add_issue(
    issues: list[SEOIssue], priority: str, title: str, recommendation: str, penalty: int
) -> None:
    issues.append(
        SEOIssue(
            priority=priority,
            title=title,
            recommendation=recommendation,
            penalty=penalty,
        )
    )


def analyze_html(source: str, html: str, keywords: list[str] | None = None) -> AnalysisResult:
    soup = BeautifulSoup(html, "html.parser")
    issues: list[SEOIssue] = []
    metrics: dict[str, int | float | str] = {}

    title = (soup.title.string or "").strip() if soup.title else ""
    description_tag = soup.find("meta", attrs={"name": "description"})
    description = (
        (description_tag.get("content", "") or "").strip() if description_tag else ""
    )
    h1_tags = soup.find_all("h1")
    h2_tags = soup.find_all("h2")
    canonical = soup.find("link", attrs={"rel": "canonical"})
    og_title = soup.find("meta", property="og:title")
    og_description = soup.find("meta", property="og:description")

    text_content = _clean_text(soup.get_text(" ", strip=True))
    text_words = _tokenize(text_content)
    word_count = len(text_words)

    images = soup.find_all("img")
    images_with_alt = [img for img in images if (img.get("alt") or "").strip()]
    alt_coverage = (
        (len(images_with_alt) / len(images)) * 100 if len(images) > 0 else 100.0
    )

    links = soup.find_all("a")
    links_with_href = [a for a in links if a.get("href")]
    internal_links, external_links = _count_links(source, links_with_href)

    metrics.update(
        {
            "title_length": len(title),
            "meta_description_length": len(description),
            "h1_count": len(h1_tags),
            "h2_count": len(h2_tags),
            "word_count": word_count,
            "image_count": len(images),
            "images_with_alt": len(images_with_alt),
            "alt_coverage_pct": round(alt_coverage, 2),
            "total_links": len(links_with_href),
            "internal_links": internal_links,
            "external_links": external_links,
            "has_canonical": 1 if canonical else 0,
            "has_og_title": 1 if og_title else 0,
            "has_og_description": 1 if og_description else 0,
        }
    )

    if len(title) < 30:
        _add_issue(
            issues,
            "HIGH",
            "Слишком короткий title",
            "Увеличьте длину title до 50-60 символов и добавьте целевое ключевое слово.",
            penalty=12,
        )
    elif len(title) > 65:
        _add_issue(
            issues,
            "MEDIUM",
            "Слишком длинный title",
            "Старайтесь держать title в диапазоне 50-60 символов, чтобы избежать обрезки в поиске.",
            penalty=6,
        )

    if len(description) < 110:
        _add_issue(
            issues,
            "HIGH",
            "Meta description отсутствует или слишком слабый",
            "Добавьте понятный meta description длиной 120-160 символов с ключевым интентом и призывом к действию.",
            penalty=12,
        )
    elif len(description) > 170:
        _add_issue(
            issues,
            "LOW",
            "Слишком длинный meta description",
            "Сократите meta description до диапазона 120-160 символов.",
            penalty=2,
        )

    if len(h1_tags) != 1:
        _add_issue(
            issues,
            "HIGH",
            "Некорректная структура H1",
            "Используйте ровно один H1, который отражает основную тему страницы.",
            penalty=12,
        )

    if len(h2_tags) < 2:
        _add_issue(
            issues,
            "MEDIUM",
            "Недостаточно подзаголовков",
            "Добавьте информативные H2-блоки для улучшения читаемости и семантики.",
            penalty=6,
        )

    if word_count < 300:
        _add_issue(
            issues,
            "HIGH",
            "Недостаточная глубина контента",
            "Расширьте контент страницы минимум до 500+ релевантных слов с практической пользой для пользователя.",
            penalty=12,
        )

    if alt_coverage < 90:
        _add_issue(
            issues,
            "MEDIUM",
            "Низкое покрытие alt у изображений",
            "Добавьте осмысленные alt-атрибуты для всех значимых изображений.",
            penalty=6,
        )

    if internal_links < 2:
        _add_issue(
            issues,
            "LOW",
            "Мало внутренних ссылок",
            "Добавьте ссылки на релевантные внутренние страницы, чтобы улучшить обход сайта и тематический вес.",
            penalty=2,
        )

    if not canonical:
        _add_issue(
            issues,
            "LOW",
            "Отсутствует canonical",
            "Добавьте тег canonical, чтобы указать приоритетный URL страницы.",
            penalty=2,
        )

    if not og_title or not og_description:
        _add_issue(
            issues,
            "LOW",
            "Неполные OpenGraph-метаданные",
            "Добавьте og:title и og:description для корректного предпросмотра ссылок в соцсетях.",
            penalty=2,
        )

    keyword_stats = _keyword_density(text_words, keywords)
    score = max(0, 100 - sum(issue.penalty for issue in issues))

    return AnalysisResult(
        source=source,
        score=score,
        metrics=metrics,
        issues=issues,
        keyword_stats=keyword_stats,
    )


def analyze_text_article(
    source: str,
    text: str,
    keywords: list[str] | None = None,
    title: str = "",
) -> AnalysisResult:
    issues: list[SEOIssue] = []
    cleaned_text = _clean_text(text)
    words = _tokenize(cleaned_text)
    word_count = len(words)
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    paragraph_count = len(paragraphs)
    sentences = _split_sentences(cleaned_text)
    sentence_count = len(sentences)
    avg_sentence_len = round((word_count / sentence_count), 2) if sentence_count else 0.0

    long_sentence_count = 0
    for sentence in sentences:
        if len(_tokenize(sentence)) > 28:
            long_sentence_count += 1
    long_sentence_share = (
        round((long_sentence_count / sentence_count) * 100, 2) if sentence_count else 0.0
    )

    metrics: dict[str, int | float] = {
        "title_length": len(title.strip()),
        "word_count": word_count,
        "paragraph_count": paragraph_count,
        "sentence_count": sentence_count,
        "avg_sentence_length_words": avg_sentence_len,
        "long_sentence_share_pct": long_sentence_share,
    }

    normalized_title = title.strip()
    if not normalized_title:
        _add_issue(
            issues,
            "HIGH",
            "Отсутствует заголовок статьи",
            "Добавьте понятный SEO-заголовок длиной 50-60 символов с основным ключевым словом.",
            penalty=12,
        )
    elif len(normalized_title) < 30:
        _add_issue(
            issues,
            "MEDIUM",
            "Слишком короткий заголовок статьи",
            "Расширьте заголовок до 50-60 символов, чтобы улучшить видимость в поисковой выдаче.",
            penalty=6,
        )
    elif len(normalized_title) > 65:
        _add_issue(
            issues,
            "LOW",
            "Слишком длинный заголовок статьи",
            "Держите длину заголовка в районе 50-60 символов, чтобы снизить риск обрезки.",
            penalty=2,
        )

    if word_count < 300:
        _add_issue(
            issues,
            "HIGH",
            "Недостаточная глубина контента",
            "Расширьте статью минимум до 500 релевантных слов с конкретными примерами.",
            penalty=12,
        )
    elif word_count < 500:
        _add_issue(
            issues,
            "MEDIUM",
            "Глубину контента можно улучшить",
            "Рекомендуется увеличить объем статьи до 500+ слов для более сильного тематического покрытия.",
            penalty=6,
        )

    if paragraph_count < 3:
        _add_issue(
            issues,
            "MEDIUM",
            "Слабая структура абзацев",
            "Разделите текст на короткие логические абзацы и добавьте подзаголовки.",
            penalty=6,
        )

    if avg_sentence_len > 24:
        _add_issue(
            issues,
            "MEDIUM",
            "Слишком длинные предложения в среднем",
            "Сократите длину предложений, чтобы улучшить читаемость и вовлеченность.",
            penalty=6,
        )

    if long_sentence_share > 35:
        _add_issue(
            issues,
            "LOW",
            "Слишком много длинных предложений",
            "Перепишите сложные фрагменты в более короткие и удобные для чтения предложения.",
            penalty=2,
        )

    keyword_stats = _keyword_density(words, keywords)
    if keywords and word_count > 0:
        for keyword, density in keyword_stats.items():
            if density < 0.5:
                _add_issue(
                    issues,
                    "MEDIUM",
                    f"Низкая частота ключевого слова: {keyword}",
                    "Используйте ключевое слово естественно в заголовках, вступлении и ключевых разделах.",
                    penalty=6,
                )
            elif density > 3.5:
                _add_issue(
                    issues,
                    "LOW",
                    f"Возможен переспам ключевым словом: {keyword}",
                    "Снизьте повторяемость и добавьте тематически близкие формулировки.",
                    penalty=2,
                )

    score = max(0, 100 - sum(issue.penalty for issue in issues))
    return AnalysisResult(
        source=source,
        score=score,
        metrics=metrics,
        issues=issues,
        keyword_stats=keyword_stats,
    )


def _count_links(source: str, links: list) -> tuple[int, int]:
    source_domain = urlparse(source).netloc if source.startswith("http") else ""
    internal = 0
    external = 0
    for link in links:
        href = (link.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("mailto:"):
            continue
        if href.startswith("/") or href.startswith("./"):
            internal += 1
            continue
        if href.startswith("http"):
            domain = urlparse(href).netloc
            if source_domain and domain == source_domain:
                internal += 1
            elif source_domain:
                external += 1
            else:
                external += 1
            continue
        internal += 1
    return internal, external


def _keyword_density(words: list[str], keywords: list[str] | None = None) -> dict[str, float]:
    if not words:
        return {}
    counts = Counter(words)
    total = len(words)

    if keywords:
        normalized = [keyword.strip().lower() for keyword in keywords if keyword.strip()]
        return {
            keyword: round((counts.get(keyword, 0) / total) * 100, 2)
            for keyword in normalized
        }

    top = counts.most_common(10)
    return {word: round((count / total) * 100, 2) for word, count in top}


def _split_sentences(text: str) -> list[str]:
    raw = re.split(r"[.!?]+", text)
    return [sentence.strip() for sentence in raw if sentence.strip()]
