from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from .models import AnalysisResult


def build_problem_playbook(result: AnalysisResult) -> list[dict[str, str]]:
    playbook: list[dict[str, str]] = []
    for issue in result.issues:
        evidence = _build_evidence(issue.title, result.metrics)
        playbook.append(
            {
                'problem': issue.title,
                'category': issue.category,
                'priority': issue.priority,
                'evidence': evidence,
                'why_it_matters': _why_it_matters(issue.category),
                'what_to_fix': issue.recommendation,
                'ready_patch': _ready_patch_hint(issue.title, issue.category),
                'post_release_check': _post_release_check(issue.title, issue.category),
            }
        )
    return playbook


def build_meta_variants(
    source_url: str,
    current_title: str,
    current_description: str,
    queries: list[str],
) -> list[dict[str, str]]:
    site = urlparse(source_url).netloc or 'Ваш сайт'
    main_query = queries[0] if queries else 'SEO аудит контента'
    second_query = queries[1] if len(queries) > 1 else 'поисковая оптимизация'
    base = current_title.strip() or main_query.title()

    variants = [
        {
            'title': f'{base}: как улучшить позиции и трафик',
            'description': f'Практический разбор по теме {main_query}. Что исправить на странице {site}, чтобы усилить SEO-результат.',
        },
        {
            'title': f'{main_query.title()} — пошаговый план + чек-лист',
            'description': f'Готовые действия по {main_query} и {second_query}: структура, интент, контент, технические сигналы.',
        },
        {
            'title': f'{base} | аудит, приоритеты, быстрые победы',
            'description': 'Краткий и практический аудит: приоритетные правки, доказательства проблем и что проверить после релиза.',
        },
    ]
    if current_description.strip():
        variants[0]['description'] = current_description[:160]
    return variants


def build_jsonld_templates(source_url: str, headline: str, description: str) -> dict[str, str]:
    article = {
        '@context': 'https://schema.org',
        '@type': 'Article',
        'headline': headline or 'Заголовок страницы',
        'description': description or 'Краткое описание страницы',
        'mainEntityOfPage': source_url,
        'author': {'@type': 'Person', 'name': 'Имя автора'},
        'datePublished': '2026-04-07',
        'dateModified': '2026-04-07',
    }
    faq = {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        'mainEntity': [
            {
                '@type': 'Question',
                'name': 'Как улучшить SEO этой страницы?',
                'acceptedAnswer': {
                    '@type': 'Answer',
                    'text': 'Исправить структуру, усилить полезность под интент и закрыть технические сигналы.',
                },
            },
            {
                '@type': 'Question',
                'name': 'Как проверить результат после релиза?',
                'acceptedAnswer': {
                    '@type': 'Answer',
                    'text': 'Сравнить score, критичные проблемы и изменения в позициях/трафике.',
                },
            },
        ],
    }
    return {
        'article_json_ld': json.dumps(article, ensure_ascii=False, indent=2),
        'faq_json_ld': json.dumps(faq, ensure_ascii=False, indent=2),
    }


def build_h_outline(queries: list[str], base_topic: str = '') -> dict[str, list[str] | str]:
    topic = base_topic.strip() or (queries[0] if queries else 'SEO аудит контента')
    h1 = f'{topic}: практический аудит и план улучшений'
    h2 = [
        '1) Что не так сейчас: ключевые риски страницы',
        '2) Что важно для пользователя и поискового интента',
        '3) Что исправить в первую очередь (быстрые победы)',
        '4) Технические правки: metadata, schema, links',
        '5) Контентный план на 30 дней',
        '6) FAQ и контроль после релиза',
    ]
    return {'h1': h1, 'h2_outline': h2}


def build_content_brief(queries: list[str], query_audit: list[dict[str, str | int | float]]) -> dict[str, object]:
    primary = queries[0] if queries else 'SEO аудит контента'
    secondary = queries[1:5] if len(queries) > 1 else ['структура страницы', 'интент', 'внутренние ссылки']
    weak_queries = [str(item['query']) for item in query_audit if item.get('status') in {'gap', 'partial'}][:5]
    return {
        'goal': 'Усилить релевантность страницы под целевые запросы и повысить полезность контента.',
        'primary_query': primary,
        'secondary_queries': secondary,
        'query_gaps_to_close': weak_queries,
        'must_have_sections': [
            'Проблема и контекст',
            'Пошаговые действия',
            'Примеры до/после',
            'FAQ',
            'Проверка результата после релиза',
        ],
        'recommended_length_words': '600-1200 (в зависимости от темы и интента)',
        'tone': 'Экспертный, конкретный, без агрессивных обещаний',
    }


def build_add_to_page_block(result: AnalysisResult) -> list[str]:
    add_block: list[str] = []
    metrics = result.metrics

    if int(metrics.get('has_canonical', 0)) == 0:
        add_block.append('Добавить тег canonical.')
    if int(metrics.get('has_og_title', 0)) == 0 or int(metrics.get('has_og_description', 0)) == 0:
        add_block.append('Добавить OpenGraph-метаданные (og:title, og:description).')
    if int(metrics.get('has_faq_schema', 0)) == 0:
        add_block.append('Добавить FAQ-блок и FAQ JSON-LD.')
    if int(metrics.get('h2_count', 0)) < 2:
        add_block.append('Добавить минимум 2 смысловых H2-блока.')
    if int(metrics.get('internal_links', 0)) < 2:
        add_block.append('Добавить 3-5 внутренних ссылок на релевантные материалы.')
    if int(metrics.get('trust_signal_score', 0)) < 2:
        add_block.append('Добавить автора, дату обновления и контактный сигнал.')
    if not add_block:
        add_block.append('Существенных блоков к добавлению не выявлено, можно переходить к тонкой оптимизации.')
    return add_block


def build_internal_link_suggestions(source_url: str, queries: list[str]) -> list[dict[str, str]]:
    domain = urlparse(source_url).netloc or 'example.com'
    topics = queries[:5] if queries else ['seo-аудит', 'контент стратегия', 'чек-лист оптимизации']
    suggestions = []
    for topic in topics:
        slug = topic.lower().replace(' ', '-')
        suggestions.append(
            {
                'anchor': f'Подробнее: {topic}',
                'target_url': f'https://{domain}/{slug}',
                'placement': 'После первого тематического абзаца',
            }
        )
    return suggestions


def build_dev_tickets(playbook: list[dict[str, str]]) -> list[dict[str, str]]:
    tickets: list[dict[str, str]] = []
    for idx, item in enumerate(playbook, start=1):
        tickets.append(
            {
                'ticket_id': f'SEO-{idx:03d}',
                'title': f"{item['category']}: {item['problem']}",
                'priority': item['priority'],
                'acceptance_criteria': item['post_release_check'],
                'implementation_notes': item['ready_patch'],
            }
        )
    return tickets


def build_action_pack(
    result: AnalysisResult,
    source_url: str,
    page_text: str,
    queries: list[str],
    query_audit: list[dict[str, str | int | float]],
) -> dict[str, object]:
    meta_variants = build_meta_variants(
        source_url=source_url,
        current_title=str(result.metrics.get('title_text', '')),
        current_description=str(result.metrics.get('meta_description_text', '')),
        queries=queries,
    )
    jsonld = build_jsonld_templates(
        source_url=source_url,
        headline=queries[0] if queries else 'SEO аудит страницы',
        description='Рекомендуемое описание страницы после оптимизации',
    )
    outline = build_h_outline(queries, base_topic=queries[0] if queries else '')
    brief = build_content_brief(queries, query_audit)
    additions = build_add_to_page_block(result)
    links = build_internal_link_suggestions(source_url, queries)
    playbook = build_problem_playbook(result)
    tickets = build_dev_tickets(playbook)
    indexation = build_indexation_summary(result)
    data_sources = build_data_sources_summary(result, query_audit, source_url)

    return {
        'problem_playbook': playbook,
        'meta_title_description_variants': meta_variants,
        'json_ld_templates': jsonld,
        'h1_h2_outline': outline,
        'content_brief': brief,
        'what_to_add_on_page': additions,
        'internal_link_suggestions': links,
        'dev_tickets': tickets,
        'query_audit': query_audit,
        'indexation_summary': indexation,
        'data_sources_summary': data_sources,
        'summary': {
            'source': result.source,
            'score': result.score,
            'query_count': len(queries),
            'page_text_length': len(page_text),
            'issues_count': len(result.issues),
        },
    }


def build_dev_tickets_markdown(dev_tickets: list[dict[str, str]]) -> str:
    if not dev_tickets:
        return '# Dev Tickets\n\nНет задач.'

    lines = ['# Dev Tickets', '']
    for ticket in dev_tickets:
        lines.append(f"## {ticket.get('ticket_id', 'SEO-XXX')}: {ticket.get('title', '')}")
        lines.append(f"- Priority: {ticket.get('priority', '')}")
        lines.append(f"- Acceptance: {ticket.get('acceptance_criteria', '')}")
        lines.append(f"- Notes: {ticket.get('implementation_notes', '')}")
        lines.append('')
    return '\n'.join(lines).strip() + '\n'


def _build_evidence(issue_title: str, metrics: dict[str, Any]) -> str:
    title_lower = issue_title.lower()
    if 'title' in title_lower:
        return f"title_length={metrics.get('title_length', 'n/a')}"
    if 'description' in title_lower:
        return f"meta_description_length={metrics.get('meta_description_length', 'n/a')}"
    if 'h1' in title_lower:
        return f"h1_count={metrics.get('h1_count', 'n/a')}"
    if 'h2' in title_lower:
        return f"h2_count={metrics.get('h2_count', 'n/a')}"
    if 'контент' in title_lower or 'глубин' in title_lower:
        return f"word_count={metrics.get('word_count', 'n/a')}"
    if 'alt' in title_lower:
        return f"alt_coverage_pct={metrics.get('alt_coverage_pct', 'n/a')}"
    if 'canonical' in title_lower:
        return f"has_canonical={metrics.get('has_canonical', 'n/a')}"
    if 'open' in title_lower or 'og' in title_lower:
        return (
            f"has_og_title={metrics.get('has_og_title', 'n/a')}, "
            f"has_og_description={metrics.get('has_og_description', 'n/a')}"
        )
    if 'интент' in title_lower:
        return f"intent_coverage_pct={metrics.get('intent_coverage_pct', 'n/a')}"
    if 'cta' in title_lower:
        return (
            f"cta_status={metrics.get('cta_status', 'n/a')}, "
            f"cta_elements={metrics.get('cta_element_count', 'n/a')}, "
            f"cta_strength_score={metrics.get('cta_strength_score', 'n/a')}"
        )
    if 'noindex' in title_lower:
        return f"has_noindex={metrics.get('has_noindex', 'n/a')}, robots_meta={metrics.get('robots_meta', 'n/a')}"
    return 'См. метрики в отчете'


def _why_it_matters(category: str) -> str:
    mapping = {
        'Техническое SEO': 'Влияет на индексацию, отображение сниппета и корректность сигналов для поисковых систем.',
        'Структура страницы': 'Влияет на сканируемость, читаемость и точность интерпретации страницы.',
        'Качество контента': 'Влияет на удержание пользователя, релевантность и качество ответа на запрос.',
        'Интент и полезность': 'Влияет на соответствие страницы реальному поисковому намерению.',
        'Доверие и E-E-A-T': 'Влияет на доверие пользователя и косвенно на устойчивость SEO-результата.',
        'Медиа и ссылки': 'Влияет на навигацию, доступность и внутреннюю силу разделов сайта.',
    }
    return mapping.get(category, 'Влияет на качество SEO-сигналов страницы.')


def _ready_patch_hint(issue_title: str, category: str) -> str:
    if 'canonical' in issue_title.lower():
        return '<link rel="canonical" href="https://example.com/current-page" />'
    if 'opengraph' in issue_title.lower() or 'og' in issue_title.lower():
        return (
            '<meta property="og:title" content="..." />\n'
            '<meta property="og:description" content="..." />'
        )
    if 'title' in issue_title.lower():
        return '<title>Новый SEO title с интентом</title>'
    if 'description' in issue_title.lower():
        return '<meta name="description" content="Новый meta description" />'
    if category == 'Интент и полезность':
        return "Добавить разделы: H2 'Как сделать', H2 'Частые ошибки', H2 'FAQ'."
    if category == 'Доверие и E-E-A-T':
        return 'Добавить блок автора + дату обновления + ссылку на контакты.'
    return 'См. action pack: предложен готовый шаблон изменения.'


def _post_release_check(issue_title: str, category: str) -> str:
    if 'canonical' in issue_title.lower():
        return 'Проверить source HTML: canonical присутствует и указывает на текущий URL.'
    if 'title' in issue_title.lower():
        return 'Проверить source HTML и сниппет-превью: title обновлен и не обрезается критично.'
    if 'description' in issue_title.lower():
        return 'Проверить source HTML: meta description присутствует и отображает пользу.'
    if category == 'Интент и полезность':
        return 'Повторный краул: intent_coverage_pct вырос, добавлены FAQ/CTA блоки.'
    return 'Повторный краул страницы: проблема закрыта или снижена по приоритету.'


def build_indexation_summary(result: AnalysisResult) -> dict[str, object]:
    metrics = result.metrics
    has_noindex = int(metrics.get('has_noindex', 0) or 0) == 1
    has_canonical = int(metrics.get('has_canonical', 0) or 0) == 1
    has_lang_attr = int(metrics.get('has_lang_attr', 0) or 0) == 1
    has_viewport = int(metrics.get('has_viewport', 0) or 0) == 1

    if has_noindex:
        verdict = 'Риск: страница закрыта от индексации (noindex).'
    elif not has_canonical:
        verdict = 'Предупреждение: нет canonical, возможны дубли и размывание сигналов.'
    elif not has_lang_attr or not has_viewport:
        verdict = 'Предупреждение: базовые технические сигналы неполные.'
    else:
        verdict = 'Базовая индексируемость выглядит корректно.'

    checks = [
        {'name': 'Meta robots', 'value': str(metrics.get('robots_meta', 'index, follow (default)'))},
        {'name': 'Noindex', 'value': 'Да' if has_noindex else 'Нет'},
        {'name': 'Canonical', 'value': 'Есть' if has_canonical else 'Нет'},
        {'name': 'Lang', 'value': 'Есть' if has_lang_attr else 'Нет'},
        {'name': 'Viewport', 'value': 'Есть' if has_viewport else 'Нет'},
        {'name': 'Indexability status', 'value': str(metrics.get('indexability_status', 'n/a'))},
    ]

    return {
        'verdict': verdict,
        'checks': checks,
        'post_release_check': 'После релиза повторить краул и убедиться, что noindex=0 и canonical присутствует.',
    }


def build_data_sources_summary(
    result: AnalysisResult,
    query_audit: list[dict[str, str | int | float]],
    source_url: str,
) -> dict[str, object]:
    score_type = str(result.metrics.get('score_type', 'heuristic'))
    query_rows = len(query_audit)
    mode = 'url' if source_url.startswith('http') else 'text'

    notes = [
        'SEO-оценка рассчитывается эвристически и используется как индикатор приоритетов, а не как абсолютная истина.',
        'Для финальных решений рекомендуется сверка с GSC/GA4 и бизнес-метриками.',
    ]
    if mode == 'text':
        notes.append('Режим текста не содержит данных реального краула и конкурентного окружения страницы.')

    return {
        'score_type': score_type,
        'analysis_mode': mode,
        'query_audit_rows': query_rows,
        'has_external_competitor_data': mode == 'url',
        'notes': notes,
    }
