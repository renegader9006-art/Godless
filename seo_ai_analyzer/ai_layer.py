from __future__ import annotations

import json
from typing import Any

from .models import AnalysisResult


def generate_ai_recommendations(
    result: AnalysisResult, api_key: str, model: str
) -> str | None:
    try:
        from openai import OpenAI
    except ImportError:
        return "OpenAI package is not installed. Run: pip install openai"

    client = OpenAI(api_key=api_key)
    payload = {
        "source": result.source,
        "score": result.score,
        "metrics": result.metrics,
        "issues": [
            {
                "priority": issue.priority,
                "title": issue.title,
                "recommendation": issue.recommendation,
            }
            for issue in result.issues
        ],
        "keyword_stats": result.keyword_stats,
    }

    system_prompt = (
        "Ты SEO-стратег. Дай приоритетные и практические рекомендации. "
        "Отвечай на русском языке в markdown с разделами: "
        "'Быстрые улучшения', 'Стратегические улучшения', 'Примеры переписывания'."
    )
    user_prompt = (
        "Проанализируй SEO-отчет и дай практические рекомендации:\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )

    try:
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
    except Exception as error:
        return _format_openai_error(error)

    text = _extract_text(response)
    return text or "AI response was empty."


def generate_improved_text_variants(
    source_text: str,
    issues_summary: list[str],
    keywords: list[str],
    api_key: str,
    model: str,
) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        return "OpenAI package is not installed. Run: pip install openai"

    client = OpenAI(api_key=api_key)
    prompt_payload = {
        "keywords": keywords,
        "issues": issues_summary,
        "text_preview": source_text[:6000],
    }
    system_prompt = (
        "Ты SEO-копирайтер. Улучши статью под поисковый интент, читаемость "
        "и уместное использование ключевых слов. Отвечай на русском языке. "
        "Верни markdown строго с двумя вариантами: 'Вариант A' и 'Вариант B'."
    )
    user_prompt = (
        "Перепиши статью, сохрани факты и смысл. Улучши структуру и SEO-качество.\n\n"
        f"{json.dumps(prompt_payload, ensure_ascii=False, indent=2)}"
    )

    try:
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
        )
    except Exception as error:
        return _format_openai_error(error)

    text = _extract_text(response)
    return text or "AI text generation returned empty output."


def _extract_text(response: Any) -> str:
    if hasattr(response, "output_text"):
        return (response.output_text or "").strip()

    output = getattr(response, "output", None)
    if not output:
        return ""

    chunks: list[str] = []
    for item in output:
        content = getattr(item, "content", None)
        if not content:
            continue
        for block in content:
            if getattr(block, "type", "") == "output_text":
                text = getattr(block, "text", "")
                if text:
                    chunks.append(text.strip())
    return "\n\n".join(chunks).strip()


def _format_openai_error(error: Exception) -> str:
    error_name = error.__class__.__name__
    text = str(error).strip()

    if "RateLimitError" in error_name or "rate limit" in text.lower():
        return (
            "Лимит OpenAI API достигнут. Проверьте квоту/баланс в OpenAI, "
            "подождите немного и повторите запрос."
        )
    if "AuthenticationError" in error_name or "invalid_api_key" in text.lower():
        return (
            "Ошибка авторизации OpenAI API. Проверьте корректность OPENAI_API_KEY "
            "в Secrets."
        )
    if "PermissionDeniedError" in error_name:
        return "Доступ к выбранной модели запрещен для текущего API-ключа."
    if "APITimeoutError" in error_name or "timeout" in text.lower():
        return "OpenAI API не ответил вовремя. Повторите попытку позже."
    if "APIConnectionError" in error_name or "connection" in text.lower():
        return "Не удалось подключиться к OpenAI API. Проверьте сеть и повторите."

    return f"Ошибка OpenAI API: {error_name}. {text}"
