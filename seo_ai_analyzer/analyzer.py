from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .models import AnalysisResult, SEOIssue

CAT_TECH = 'Техническое SEO'
CAT_STRUCTURE = 'Структура страницы'
CAT_CONTENT = 'Качество контента'
CAT_INTENT = 'Интент и полезность'
CAT_TRUST = 'Доверие и E-E-A-T'
CAT_MEDIA = 'Медиа и ссылки'

STOP_WORDS = {
    'a',
    'an',
    'and',
    'are',
    'as',
    'at',
    'be',
    'by',
    'for',
    'from',
    'in',
    'is',
    'it',
    'of',
    'on',
    'or',
    'that',
    'the',
    'to',
    'was',
    'were',
    'with',
    'и',
    'в',
    'на',
    'с',
    'по',
    'за',
    'к',
    'до',
    'от',
    'что',
    'это',
    'как',
    'для',
    'из',
    'не',
}

RENDER_PATTERNS = ('loading', 'loading...', 'загрузка', 'подождите', 'skeleton', 'shimmer')
RISK_COPY_PATTERNS = (
    'лучший',
    'гарантированно',
    '100%',
    'без усилий',
    'без вложений',
    'мгновенно',
    'только сегодня',
    'секрет',
    'номер 1',
)
INTENT_PATTERNS = (
    'как',
    'пошаг',
    'инструкц',
    'пример',
    'кейс',
    'ошибк',
    'что делать',
    'сравнени',
    'чек-лист',
)
CTA_PATTERNS = (
    'оставьте заявку',
    'свяжитесь',
    'заказать',
    'купить',
    'скачать',
    'попробовать',
    'зарегистрироваться',
)
GENERIC_ANCHORS = {'читать', 'подробнее', 'узнать больше', 'ссылка', 'here', 'click here'}
WORD_RE = re.compile(r'[A-Za-zА-Яа-яЁё0-9]+')


def _clean_text(raw_text: str) -> str:
    return re.sub(r'\s+', ' ', raw_text).strip()


def _tokenize(text: str) -> list[str]:
    tokens = WORD_RE.findall(text.lower())
    return [token for token in tokens if token not in STOP_WORDS and len(token) > 2]


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]


def _add_issue(
    issues: list[SEOIssue],
    priority: str,
    category: str,
    title: str,
    recommendation: str,
    penalty: int,
) -> None:
    issues.append(
        SEOIssue(
            priority=priority,
            category=category,
            title=title,
            recommendation=recommendation,
            penalty=penalty,
        )
    )


def analyze_html(source: str, html: str, keywords: list[str] | None = None) -> AnalysisResult:
    soup = BeautifulSoup(html, 'html.parser')
    issues: list[SEOIssue] = []
    keywords = keywords or []

    html_tag = soup.find('html')
    title = (soup.title.string or '').strip() if soup.title else ''
    desc_tag = soup.find('meta', attrs={'name': 'description'})
    description = (desc_tag.get('content', '') or '').strip() if desc_tag else ''
    h1_tags = soup.find_all('h1')
    h2_tags = soup.find_all('h2')
    canonical = bool(soup.find('link', attrs={'rel': 'canonical'}))
    og_title = bool(soup.find('meta', property='og:title'))
    og_description = bool(soup.find('meta', property='og:description'))
    robots = (soup.find('meta', attrs={'name': 'robots'}) or {}).get('content', '')
    has_noindex = 'noindex' in str(robots).lower()

    ld_scripts = soup.find_all('script', attrs={'type': 'application/ld+json'})
    schema_count = len(ld_scripts)
    has_faq_schema = any('faqpage' in (s.get_text(' ', strip=True) or '').lower() for s in ld_scripts)
    has_breadcrumb_schema = any('breadcrumblist' in (s.get_text(' ', strip=True) or '').lower() for s in ld_scripts)

    text = _clean_text(soup.get_text(' ', strip=True))
    text_lower = text.lower()
    words = _tokenize(text)
    word_count = len(words)
    unique_ratio = round((len(set(words)) / word_count), 3) if word_count else 0.0
    sentences = _split_sentences(text)
    sentence_count = len(sentences)
    avg_sentence_len = round((word_count / sentence_count), 2) if sentence_count else 0.0

    paragraph_texts = []
    for tag in soup.find_all(['p', 'li']):
        p = _clean_text(tag.get_text(' ', strip=True))
        if len(p) >= 30:
            paragraph_texts.append(p)
    paragraph_count = len(paragraph_texts)
    paragraph_lengths = [len(_tokenize(p)) for p in paragraph_texts]
    avg_paragraph_len = round(sum(paragraph_lengths) / len(paragraph_lengths), 2) if paragraph_lengths else 0.0
    long_paragraph_share = (
        round((sum(1 for p in paragraph_lengths if p >= 120) / len(paragraph_lengths)) * 100, 2)
        if paragraph_lengths
        else 0.0
    )

    images = soup.find_all('img')
    images_with_alt = [img for img in images if (img.get('alt') or '').strip()]
    alt_coverage = round((len(images_with_alt) / len(images)) * 100, 2) if images else 100.0
    images_without_alt = len(images) - len(images_with_alt)

    links = [a for a in soup.find_all('a') if a.get('href')]
    internal_links, external_links = _count_links(source, links)
    generic_anchor_share = _generic_anchor_share(links)

    heading_jumps = _heading_hierarchy_jumps(soup)
    duplicate_block_pct = _duplicate_block_ratio(soup)
    has_loading_placeholder = _has_render_placeholder(text_lower, soup)
    risky_copy_hits = _count_hits(text_lower, RISK_COPY_PATTERNS)
    cta_hits = _count_hits(text_lower, CTA_PATTERNS)
    intent_coverage_pct = _estimate_intent_coverage(text_lower, h2_tags, keywords, title, h1_tags)
    faq_signal_count = _faq_signal_count(text, has_faq_schema)

    has_author_signal = bool(
        soup.find('meta', attrs={'name': 'author'})
        or soup.find(attrs={'itemprop': 'author'})
        or re.search(r'\b(автор|author)\b', text_lower)
    )
    has_date_signal = bool(
        soup.find('time')
        or soup.find('meta', attrs={'property': 'article:published_time'})
        or re.search(r'\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b', text)
    )
    has_contact_signal = bool(
        soup.find('a', href=re.compile(r'^mailto:', re.I))
        or soup.find('a', href=re.compile(r'^tel:', re.I))
        or re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', text)
        or re.search(r'\+?\d[\d\-\s()]{7,}\d', text)
        or re.search(r'\b(контакты|contact)\b', text_lower)
    )
    trust_signal_score = sum([has_author_signal, has_date_signal, has_contact_signal])

    has_lang_attr = bool(html_tag and (html_tag.get('lang') or '').strip())
    has_viewport = bool(soup.find('meta', attrs={'name': 'viewport'}))
    script_count = len(soup.find_all('script'))
    script_to_text_ratio = round((script_count / word_count), 3) if word_count else float(script_count)

    h1_text = h1_tags[0].get_text(' ', strip=True) if h1_tags else ''
    h2_texts = [tag.get_text(' ', strip=True) for tag in h2_tags]

    metrics: dict[str, int | float | str | list[str]] = {
        'score_type': 'heuristic',
        'title_text': title,
        'meta_description_text': description,
        'h1_text': h1_text,
        'h2_texts': h2_texts,
        'title_length': len(title),
        'meta_description_length': len(description),
        'h1_count': len(h1_tags),
        'h2_count': len(h2_tags),
        'heading_jumps': heading_jumps,
        'word_count': word_count,
        'sentence_count': sentence_count,
        'avg_sentence_length_words': avg_sentence_len,
        'paragraph_count': paragraph_count,
        'avg_paragraph_length_words': avg_paragraph_len,
        'long_paragraph_share_pct': long_paragraph_share,
        'unique_word_ratio': unique_ratio,
        'image_count': len(images),
        'images_with_alt': len(images_with_alt),
        'images_without_alt': images_without_alt,
        'alt_coverage_pct': alt_coverage,
        'total_links': len(links),
        'internal_links': internal_links,
        'external_links': external_links,
        'generic_anchor_share_pct': round(generic_anchor_share, 2),
        'has_canonical': 1 if canonical else 0,
        'has_og_title': 1 if og_title else 0,
        'has_og_description': 1 if og_description else 0,
        'has_lang_attr': 1 if has_lang_attr else 0,
        'has_viewport': 1 if has_viewport else 0,
        'has_noindex': 1 if has_noindex else 0,
        'schema_count': schema_count,
        'has_faq_schema': 1 if has_faq_schema else 0,
        'has_breadcrumb_schema': 1 if has_breadcrumb_schema else 0,
        'duplicate_text_block_pct': round(duplicate_block_pct, 2),
        'has_loading_placeholder_text': 1 if has_loading_placeholder else 0,
        'risky_copywriting_hits': risky_copy_hits,
        'intent_coverage_pct': round(intent_coverage_pct, 2),
        'cta_signal_hits': cta_hits,
        'faq_signal_count': faq_signal_count,
        'trust_signal_score': trust_signal_score,
        'has_author_signal': 1 if has_author_signal else 0,
        'has_date_signal': 1 if has_date_signal else 0,
        'has_contact_signal': 1 if has_contact_signal else 0,
        'script_count': script_count,
        'dom_script_to_text_ratio': script_to_text_ratio,
    }

    _audit_tech(
        issues,
        title,
        description,
        has_lang_attr,
        has_viewport,
        has_noindex,
        canonical,
        og_title,
        og_description,
        schema_count,
    )
    _audit_structure(
        issues,
        len(h1_tags),
        len(h2_tags),
        heading_jumps,
        duplicate_block_pct,
        has_loading_placeholder,
        script_to_text_ratio,
    )
    _audit_content(
        issues,
        word_count,
        paragraph_count,
        avg_sentence_len,
        long_paragraph_share,
        unique_ratio,
        risky_copy_hits,
    )
    _audit_intent(
        issues,
        intent_coverage_pct,
        faq_signal_count,
        cta_hits,
        keywords,
        title,
        h1_tags,
        text_lower,
    )
    _audit_media_links(issues, alt_coverage, internal_links, external_links, generic_anchor_share)
    _audit_trust(
        issues,
        trust_signal_score,
        has_author_signal,
        has_date_signal,
        has_contact_signal,
        has_breadcrumb_schema,
    )

    keyword_stats = _keyword_density(words, keywords)
    _add_keyword_density_hints(issues, keyword_stats, keywords)

    score = max(0, 100 - sum(issue.penalty for issue in issues))
    return AnalysisResult(source=source, score=score, metrics=metrics, issues=issues, keyword_stats=keyword_stats)


def analyze_text_article(
    source: str,
    text: str,
    keywords: list[str] | None = None,
    title: str = '',
) -> AnalysisResult:
    issues: list[SEOIssue] = []
    keywords = keywords or []
    cleaned = _clean_text(text)
    text_lower = cleaned.lower()
    words = _tokenize(cleaned)
    word_count = len(words)
    unique_ratio = round((len(set(words)) / word_count), 3) if word_count else 0.0
    sentences = _split_sentences(cleaned)
    sentence_count = len(sentences)
    avg_sentence_len = round((word_count / sentence_count), 2) if sentence_count else 0.0
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    paragraph_count = len(paragraphs)
    paragraph_lengths = [len(_tokenize(p)) for p in paragraphs]
    long_paragraph_share = (
        round((sum(1 for p in paragraph_lengths if p >= 120) / len(paragraph_lengths)) * 100, 2)
        if paragraph_lengths
        else 0.0
    )

    risky_copy_hits = _count_hits(text_lower, RISK_COPY_PATTERNS)
    cta_hits = _count_hits(text_lower, CTA_PATTERNS)
    intent_coverage_pct = _estimate_intent_coverage(text_lower, [], keywords, title, [])
    faq_signal_count = _faq_signal_count(cleaned, False)
    has_author_signal = bool(re.search(r'\b(автор|author)\b', text_lower))
    has_date_signal = bool(re.search(r'\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b', cleaned))
    has_contact_signal = bool(
        re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', cleaned)
        or re.search(r'\+?\d[\d\-\s()]{7,}\d', cleaned)
    )
    trust_signal_score = sum([has_author_signal, has_date_signal, has_contact_signal])

    metrics: dict[str, int | float | str | list[str]] = {
        'score_type': 'heuristic',
        'title_text': title.strip(),
        'meta_description_text': '',
        'h1_text': title.strip(),
        'h2_texts': [],
        'title_length': len(title.strip()),
        'word_count': word_count,
        'sentence_count': sentence_count,
        'avg_sentence_length_words': avg_sentence_len,
        'paragraph_count': paragraph_count,
        'long_paragraph_share_pct': long_paragraph_share,
        'unique_word_ratio': unique_ratio,
        'risky_copywriting_hits': risky_copy_hits,
        'intent_coverage_pct': round(intent_coverage_pct, 2),
        'cta_signal_hits': cta_hits,
        'faq_signal_count': faq_signal_count,
        'trust_signal_score': trust_signal_score,
        'has_author_signal': 1 if has_author_signal else 0,
        'has_date_signal': 1 if has_date_signal else 0,
        'has_contact_signal': 1 if has_contact_signal else 0,
    }

    if not title.strip():
        _add_issue(issues, 'MEDIUM', CAT_STRUCTURE, 'Отсутствует заголовок', 'Добавьте информативный title статьи.', 5)
    elif len(title.strip()) < 30:
        _add_issue(issues, 'LOW', CAT_STRUCTURE, 'Слишком короткий title', 'Уточните title, чтобы раскрыть тему и интент.', 2)

    _audit_content(
        issues,
        word_count,
        paragraph_count,
        avg_sentence_len,
        long_paragraph_share,
        unique_ratio,
        risky_copy_hits,
    )
    _audit_intent(issues, intent_coverage_pct, faq_signal_count, cta_hits, keywords, title, [], text_lower)
    _audit_trust(issues, trust_signal_score, has_author_signal, has_date_signal, has_contact_signal, False)

    keyword_stats = _keyword_density(words, keywords)
    _add_keyword_density_hints(issues, keyword_stats, keywords)

    score = max(0, 100 - sum(issue.penalty for issue in issues))
    return AnalysisResult(source=source, score=score, metrics=metrics, issues=issues, keyword_stats=keyword_stats)


def _audit_tech(
    issues: list[SEOIssue],
    title: str,
    description: str,
    has_lang_attr: bool,
    has_viewport: bool,
    has_noindex: bool,
    canonical: bool,
    og_title: bool,
    og_description: bool,
    schema_count: int,
) -> None:
    if len(title) < 35:
        _add_issue(issues, 'HIGH', CAT_TECH, 'Слабый title', 'Сделайте title 45-65 символов с ключевой пользой.', 9)
    elif len(title) > 70:
        _add_issue(issues, 'MEDIUM', CAT_TECH, 'Слишком длинный title', 'Сократите title, чтобы он не обрезался в выдаче.', 4)

    if len(description) < 90:
        _add_issue(issues, 'MEDIUM', CAT_TECH, 'Meta description отсутствует или короткий', 'Добавьте meta description 110-160 символов.', 4)
    elif len(description) > 180:
        _add_issue(issues, 'LOW', CAT_TECH, 'Meta description слишком длинный', 'Сократите meta description.', 2)

    if not has_lang_attr:
        _add_issue(issues, 'LOW', CAT_TECH, 'Нет атрибута lang', 'Добавьте lang в тег html.', 2)
    if not has_viewport:
        _add_issue(issues, 'MEDIUM', CAT_TECH, 'Нет viewport', 'Добавьте meta viewport для мобильных устройств.', 4)
    if has_noindex:
        _add_issue(issues, 'HIGH', CAT_TECH, 'Страница в noindex', 'Уберите noindex, если страница должна ранжироваться.', 10)
    if not canonical:
        _add_issue(issues, 'LOW', CAT_TECH, 'Нет canonical', 'Добавьте canonical ссылку.', 2)
    if not og_title or not og_description:
        _add_issue(issues, 'LOW', CAT_TECH, 'Нет OpenGraph-данных', 'Добавьте og:title и og:description.', 2)
    if schema_count == 0:
        _add_issue(issues, 'LOW', CAT_TECH, 'Нет JSON-LD schema', 'Добавьте FAQ/Article/Breadcrumb schema.', 2)


def _audit_structure(
    issues: list[SEOIssue],
    h1_count: int,
    h2_count: int,
    heading_jumps: int,
    duplicate_block_pct: float,
    has_loading_placeholder: bool,
    script_to_text_ratio: float,
) -> None:
    if h1_count != 1:
        _add_issue(issues, 'HIGH', CAT_STRUCTURE, 'Неверная структура H1', 'На странице должен быть ровно один H1.', 9)
    if h2_count < 2:
        _add_issue(issues, 'MEDIUM', CAT_STRUCTURE, 'Слабая структура разделов', 'Добавьте логичные H2/H3 под интенты.', 4)
    if heading_jumps > 0:
        _add_issue(issues, 'LOW', CAT_STRUCTURE, 'Скачки уровней заголовков', 'Используйте последовательную иерархию H1 -> H2 -> H3.', 2)
    if duplicate_block_pct >= 35:
        _add_issue(issues, 'MEDIUM', CAT_STRUCTURE, 'Повторяющиеся блоки DOM', 'Сократите дублирующиеся фрагменты в шаблоне.', 4)
    if has_loading_placeholder:
        _add_issue(issues, 'MEDIUM', CAT_STRUCTURE, 'Обнаружены placeholder-блоки', 'Проверьте рендер: не должен оставаться Loading/skeleton текст.', 4)
    if script_to_text_ratio > 0.15:
        _add_issue(issues, 'LOW', CAT_STRUCTURE, 'Много скриптов относительно контента', 'Оптимизируйте рендер или увеличьте полезный контент.', 2)


def _audit_content(
    issues: list[SEOIssue],
    word_count: int,
    paragraph_count: int,
    avg_sentence_len: float,
    long_paragraph_share: float,
    unique_ratio: float,
    risky_copy_hits: int,
) -> None:
    if word_count < 140:
        _add_issue(issues, 'HIGH', CAT_CONTENT, 'Недостаточная глубина контента', 'Расширьте материал практическими ответами и примерами.', 9)
    elif word_count < 260:
        _add_issue(issues, 'MEDIUM', CAT_CONTENT, 'Контента мало', 'Добавьте блоки с конкретикой под целевые запросы.', 4)

    if paragraph_count < 3:
        _add_issue(issues, 'MEDIUM', CAT_CONTENT, 'Мало смысловых абзацев', 'Разбейте текст на логические абзацы и подзаголовки.', 4)
    if avg_sentence_len > 24:
        _add_issue(issues, 'MEDIUM', CAT_CONTENT, 'Сложные длинные предложения', 'Упростите синтаксис и сократите предложения.', 4)
    if long_paragraph_share > 45:
        _add_issue(issues, 'LOW', CAT_CONTENT, 'Слишком длинные абзацы', 'Разбейте крупные абзацы на короткие блоки.', 2)
    if unique_ratio < 0.35 and word_count > 150:
        _add_issue(issues, 'LOW', CAT_CONTENT, 'Низкое разнообразие лексики', 'Добавьте примеры и конкретные формулировки.', 2)

    if risky_copy_hits >= 4:
        _add_issue(issues, 'MEDIUM', CAT_CONTENT, 'Рискованный copywriting', 'Уберите агрессивные обещания и усилите доказательность.', 4)
    elif risky_copy_hits >= 2:
        _add_issue(issues, 'LOW', CAT_CONTENT, 'Маркетинговые обещания без доказательств', 'Добавьте факты, источники и ограничения.', 2)


def _audit_intent(
    issues: list[SEOIssue],
    intent_coverage_pct: float,
    faq_signal_count: int,
    cta_hits: int,
    keywords: list[str],
    title: str,
    h1_tags: list,
    text_lower: str,
) -> None:
    if intent_coverage_pct < 45:
        _add_issue(issues, 'HIGH', CAT_INTENT, 'Слабое покрытие интента', 'Добавьте блоки: как сделать, ошибки, сравнение, FAQ.', 9)
    elif intent_coverage_pct < 70:
        _add_issue(issues, 'MEDIUM', CAT_INTENT, 'Частичное покрытие интента', 'Усилите контент примерами и пошаговыми действиями.', 4)

    if faq_signal_count == 0:
        _add_issue(issues, 'LOW', CAT_INTENT, 'Нет FAQ-сигнала', 'Добавьте FAQ-блок из 3-5 вопросов.', 2)
    if cta_hits == 0:
        _add_issue(issues, 'LOW', CAT_INTENT, 'Нет CTA', 'Добавьте естественный CTA в конце страницы.', 2)

    if keywords:
        h1_text = h1_tags[0].get_text(' ', strip=True).lower() if h1_tags else ''
        core = f'{title.lower()} {h1_text}'
        if not any(k.lower() in core for k in keywords):
            _add_issue(issues, 'MEDIUM', CAT_INTENT, 'Ключевые фразы не отражены в title/H1', 'Добавьте целевые фразы в title и H1.', 4)
        if not any(k.lower() in text_lower for k in keywords):
            _add_issue(issues, 'LOW', CAT_INTENT, 'Ключевые фразы отсутствуют в тексте', 'Добавьте ключевые фразы в тематические блоки.', 2)


def _audit_media_links(
    issues: list[SEOIssue],
    alt_coverage: float,
    internal_links: int,
    external_links: int,
    generic_anchor_share: float,
) -> None:
    if alt_coverage < 85:
        _add_issue(issues, 'MEDIUM', CAT_MEDIA, 'Низкое покрытие alt у изображений', 'Заполните alt-атрибуты у изображений.', 4)
    if internal_links < 2:
        _add_issue(issues, 'LOW', CAT_MEDIA, 'Мало внутренних ссылок', 'Добавьте внутренние ссылки на релевантные страницы.', 2)
    if external_links == 0:
        _add_issue(issues, 'LOW', CAT_MEDIA, 'Нет внешних источников', 'Добавьте 1-2 ссылки на авторитетные источники.', 2)
    if generic_anchor_share >= 60:
        _add_issue(issues, 'LOW', CAT_MEDIA, 'Слишком общие анкоры', 'Используйте конкретные анкоры вместо «подробнее».', 2)


def _audit_trust(
    issues: list[SEOIssue],
    trust_signal_score: int,
    has_author_signal: bool,
    has_date_signal: bool,
    has_contact_signal: bool,
    has_breadcrumb_schema: bool,
) -> None:
    if trust_signal_score <= 1:
        _add_issue(issues, 'MEDIUM', CAT_TRUST, 'Слабые сигналы доверия', 'Добавьте автора, дату, контакты и фактологию.', 4)
    if not has_author_signal:
        _add_issue(issues, 'LOW', CAT_TRUST, 'Нет автора', 'Добавьте блок автора/эксперта.', 2)
    if not has_date_signal:
        _add_issue(issues, 'LOW', CAT_TRUST, 'Нет даты обновления', 'Укажите дату публикации и обновления.', 2)
    if not has_contact_signal:
        _add_issue(issues, 'LOW', CAT_TRUST, 'Нет контактного сигнала', 'Добавьте email, телефон или страницу контактов.', 2)
    if not has_breadcrumb_schema:
        _add_issue(issues, 'LOW', CAT_TRUST, 'Нет breadcrumb-schema', 'Добавьте BreadcrumbList schema.', 1)


def _count_links(source: str, links: list) -> tuple[int, int]:
    source_domain = urlparse(source).netloc if source.startswith('http') else ''
    internal = 0
    external = 0
    for link in links:
        href = (link.get('href') or '').strip()
        if not href or href.startswith('#') or href.startswith('mailto:'):
            continue
        if href.startswith('/') or href.startswith('./'):
            internal += 1
            continue
        if href.startswith('http'):
            domain = urlparse(href).netloc
            if source_domain and domain == source_domain:
                internal += 1
            else:
                external += 1
            continue
        internal += 1
    return internal, external


def _heading_hierarchy_jumps(soup: BeautifulSoup) -> int:
    headings = soup.find_all(re.compile(r'^h[1-6]$'))
    prev = 0
    jumps = 0
    for heading in headings:
        level = int(heading.name[1])
        if prev and level > prev + 1:
            jumps += 1
        prev = level
    return jumps


def _duplicate_block_ratio(soup: BeautifulSoup) -> float:
    blocks = []
    for tag in soup.find_all(['p', 'li', 'a', 'button', 'span', 'div']):
        t = _clean_text(tag.get_text(' ', strip=True))
        if 8 <= len(t) <= 140:
            blocks.append(t.lower())
    if not blocks:
        return 0.0
    counts = Counter(blocks)
    duplicates = sum(count - 1 for count in counts.values() if count > 1)
    return (duplicates / len(blocks)) * 100


def _has_render_placeholder(text_lower: str, soup: BeautifulSoup) -> bool:
    if any(pattern in text_lower for pattern in RENDER_PATTERNS):
        return True
    for tag in soup.find_all(attrs={'class': True}):
        classes = ' '.join(tag.get('class', [])).lower()
        if any(pattern in classes for pattern in ('skeleton', 'loading', 'shimmer')):
            return True
    return False


def _count_hits(text: str, patterns: tuple[str, ...]) -> int:
    return sum(text.count(p) for p in patterns)


def _estimate_intent_coverage(
    text_lower: str,
    h2_tags: list,
    keywords: list[str],
    title: str,
    h1_tags: list,
) -> float:
    checks = 0
    score = 0

    checks += 1
    if any(p in text_lower for p in INTENT_PATTERNS):
        score += 1

    checks += 1
    if len(text_lower) > 1200:
        score += 1

    checks += 1
    if len(h2_tags) >= 2:
        score += 1

    checks += 1
    if any(p in text_lower for p in ('пример', 'кейс', 'ошибка', 'сравнение')):
        score += 1

    checks += 1
    if any(p in text_lower for p in ('faq', 'вопрос', 'ответ', 'что делать')):
        score += 1

    if keywords:
        checks += 1
        h1_text = h1_tags[0].get_text(' ', strip=True).lower() if h1_tags else ''
        if any(k.lower() in f'{title.lower()} {h1_text}' for k in keywords):
            score += 1

    return (score / checks) * 100 if checks else 0.0


def _faq_signal_count(text: str, has_faq_schema: bool) -> int:
    lower = text.lower()
    count = 0
    if has_faq_schema:
        count += 1
    if 'faq' in lower or 'вопрос' in lower:
        count += 1
    if text.count('?') >= 2:
        count += 1
    return count


def _generic_anchor_share(links: list) -> float:
    anchors = []
    for link in links:
        text = _clean_text(link.get_text(' ', strip=True)).lower()
        if text:
            anchors.append(text)
    if not anchors:
        return 0.0
    generic = 0
    for a in anchors:
        if a in GENERIC_ANCHORS or (len(a) <= 6 and a in {'тут', 'here', 'link'}):
            generic += 1
    return (generic / len(anchors)) * 100


def _keyword_density(words: list[str], keywords: list[str] | None = None) -> dict[str, float]:
    if not words:
        return {}
    counts = Counter(words)
    total = len(words)
    if keywords:
        norm = [k.strip().lower() for k in keywords if k.strip()]
        return {k: round((counts.get(k, 0) / total) * 100, 2) for k in norm}
    return {word: round((count / total) * 100, 2) for word, count in counts.most_common(10)}


def _add_keyword_density_hints(
    issues: list[SEOIssue],
    keyword_stats: dict[str, float],
    keywords: list[str] | None,
) -> None:
    if not keywords or not keyword_stats:
        return

    for keyword, density in keyword_stats.items():
        if density > 4.5:
            _add_issue(
                issues,
                'LOW',
                CAT_INTENT,
                f'Переспам ключом: {keyword}',
                'Уменьшите частоту ключа, добавьте естественные синонимы и контекст.',
                penalty=1,
            )
        elif 0 < density < 0.15:
            _add_issue(
                issues,
                'LOW',
                CAT_INTENT,
                f'Слабый сигнал ключа: {keyword}',
                'Добавьте ключ в релевантные блоки и заголовки без переспама.',
                penalty=1,
            )
