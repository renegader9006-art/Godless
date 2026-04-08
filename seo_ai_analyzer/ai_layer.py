from __future__ import annotations

import json
from typing import Any

import requests

from .models import AnalysisResult


def generate_ai_recommendations(
    result: AnalysisResult,
    api_key: str,
    model: str,
) -> str | None:
    payload = {
        'source': result.source,
        'score': result.score,
        'metrics': result.metrics,
        'issues': [
            {
                'priority': issue.priority,
                'category': issue.category,
                'title': issue.title,
                'recommendation': issue.recommendation,
            }
            for issue in result.issues
        ],
        'keyword_stats': result.keyword_stats,
    }

    system_prompt = (
        'Ты SEO-стратег. Дай приоритетные практические рекомендации на русском языке. '
        "Формат: markdown с разделами 'Быстрые улучшения', 'Стратегические улучшения', 'Примеры переписывания'."
    )
    user_prompt = (
        'Проанализируй SEO-отчет и дай конкретные рекомендации:\n\n'
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return _openai_chat(system_prompt, user_prompt, api_key=api_key, model=model)


def generate_improved_text_variants(
    source_text: str,
    issues_summary: list[str],
    keywords: list[str],
    api_key: str,
    model: str,
) -> str:
    prompt_payload = {
        'keywords': keywords,
        'issues': issues_summary,
        'text_preview': source_text[:7000],
    }
    system_prompt = (
        'Ты SEO-копирайтер. Улучши текст под интент и читаемость. '
        "Верни markdown строго с двумя блоками: 'Вариант A' и 'Вариант B'."
    )
    user_prompt = (
        'Перепиши текст, сохрани смысл и факты. Сделай лучше по SEO:\n\n'
        f"{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}"
    )
    return _openai_chat(system_prompt, user_prompt, api_key=api_key, model=model)


def generate_ai_recommendations_ollama(
    result: AnalysisResult,
    model: str,
    base_url: str = 'http://127.0.0.1:11434',
) -> str:
    payload = {
        'source': result.source,
        'score': result.score,
        'metrics': result.metrics,
        'issues': [
            {
                'priority': issue.priority,
                'category': issue.category,
                'title': issue.title,
                'recommendation': issue.recommendation,
            }
            for issue in result.issues
        ],
        'keyword_stats': result.keyword_stats,
    }
    prompt = (
        'Ты SEO-стратег. Дай рекомендации на русском языке.\n'
        "Формат: markdown с разделами 'Быстрые улучшения', 'Стратегические улучшения', 'Примеры переписывания'.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return _ollama_generate(prompt=prompt, model=model, base_url=base_url)


def generate_improved_text_variants_ollama(
    source_text: str,
    issues_summary: list[str],
    keywords: list[str],
    model: str,
    base_url: str = 'http://127.0.0.1:11434',
) -> str:
    payload = {
        'keywords': keywords,
        'issues': issues_summary,
        'text_preview': source_text[:7000],
    }
    prompt = (
        'Ты SEO-копирайтер. Улучши текст на русском языке.\n'
        "Верни markdown строго с двумя блоками: 'Вариант A' и 'Вариант B'.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return _ollama_generate(prompt=prompt, model=model, base_url=base_url)


def _openai_chat(system_prompt: str, user_prompt: str, api_key: str, model: str) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        return 'Пакет openai не установлен. Выполните: pip install openai'

    if not api_key.strip():
        return 'Не найден OpenAI API-ключ.'

    client = OpenAI(api_key=api_key)
    try:
        response = client.responses.create(
            model=model,
            input=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            temperature=0.2,
        )
    except Exception as error:  # noqa: BLE001
        return _format_openai_error(error)

    text = _extract_text(response)
    return text or 'AI-ответ пустой.'


def _ollama_generate(prompt: str, model: str, base_url: str) -> str:
    url = f"{base_url.rstrip('/')}/api/generate"
    try:
        response = requests.post(
            url,
            json={'model': model, 'prompt': prompt, 'stream': False},
            timeout=180,
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        return (
            'Не удалось подключиться к Ollama. '
            'Проверьте, что Ollama запущен локально и доступен на 127.0.0.1:11434.'
        )
    except requests.exceptions.RequestException as error:
        return f'Ошибка Ollama API: {error}'

    payload = response.json()
    text = (payload.get('response') or '').strip()
    if not text:
        return 'Ollama вернул пустой ответ.'
    return text


def _extract_text(response: Any) -> str:
    if hasattr(response, 'output_text'):
        return (response.output_text or '').strip()

    output = getattr(response, 'output', None)
    if not output:
        return ''

    chunks: list[str] = []
    for item in output:
        content = getattr(item, 'content', None)
        if not content:
            continue
        for block in content:
            if getattr(block, 'type', '') == 'output_text':
                text = getattr(block, 'text', '')
                if text:
                    chunks.append(text.strip())
    return '\n\n'.join(chunks).strip()


def _format_openai_error(error: Exception) -> str:
    error_name = error.__class__.__name__
    text = str(error).strip()

    if 'RateLimitError' in error_name or 'rate limit' in text.lower():
        return (
            'Лимит OpenAI API достигнут. Проверьте квоту/баланс, '
            'подождите и повторите запрос.'
        )
    if 'AuthenticationError' in error_name or 'invalid_api_key' in text.lower():
        return 'Ошибка авторизации OpenAI API. Проверьте OPENAI_API_KEY.'
    if 'PermissionDeniedError' in error_name:
        return 'Нет доступа к выбранной модели OpenAI.'
    if 'APITimeoutError' in error_name or 'timeout' in text.lower():
        return 'OpenAI API не ответил вовремя. Попробуйте позже.'
    if 'APIConnectionError' in error_name or 'connection' in text.lower():
        return 'Не удалось подключиться к OpenAI API. Проверьте сеть.'

    return f'Ошибка OpenAI API: {error_name}. {text}'
