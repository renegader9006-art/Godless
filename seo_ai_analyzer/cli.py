from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

import requests

from .ai_layer import generate_ai_recommendations
from .analyzer import analyze_html
from .fetcher import load_html_from_file, load_html_from_url
from .models import AnalysisResult


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seo-ai-analyzer",
        description="CLI-инструмент для базового SEO-аудита HTML/URL.",
    )
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--url", help="URL страницы для анализа.")
    target_group.add_argument("--file", help="Локальный путь к HTML-файлу.")

    parser.add_argument(
        "--keyword",
        action="append",
        default=[],
        help="Ключевая фраза для проверки вхождений. Можно указывать несколько раз.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Формат отчета.",
    )
    parser.add_argument(
        "--output",
        help="Путь для сохранения отчета.",
    )
    parser.add_argument(
        "--use-ai",
        action="store_true",
        help="Добавить AI-рекомендации через OpenAI API.",
    )
    parser.add_argument(
        "--model",
        default="gpt-4.1-mini",
        help="Модель OpenAI для AI-блока.",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="OpenAI API key (или переменная OPENAI_API_KEY).",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        source, html = _load_source(args.url, args.file)
    except requests.exceptions.ProxyError as error:
        print(
            "Ошибка сети: прокси-сервер недоступен или неверно настроен. "
            "Проверьте HTTP_PROXY/HTTPS_PROXY и повторите.",
            file=sys.stderr,
        )
        print(f"Детали: {error}", file=sys.stderr)
        return 2
    except requests.exceptions.SSLError as error:
        print(
            "Ошибка SSL: не удалось проверить сертификат HTTPS-страницы. "
            "Проверьте сертификаты системы и сетевое окружение.",
            file=sys.stderr,
        )
        print(f"Детали: {error}", file=sys.stderr)
        return 2
    except requests.exceptions.RequestException as error:
        print(f"Ошибка HTTP-запроса: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"Ошибка чтения файла: {error}", file=sys.stderr)
        return 2

    result = analyze_html(source=source, html=html, keywords=args.keyword or None)

    if args.use_ai:
        api_key = args.api_key or os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            result.ai_recommendations = (
                "AI-блок отключен: не найден OpenAI API key. "
                "Передайте --api-key или задайте OPENAI_API_KEY."
            )
        else:
            result.ai_recommendations = generate_ai_recommendations(
                result=result,
                api_key=api_key,
                model=args.model,
            )

    rendered = render_report(result, output_format=args.format)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as output_file:
            output_file.write(rendered)
    else:
        print(rendered)

    return 0


def _load_source(url: str | None, file_path: str | None) -> tuple[str, str]:
    if url:
        return url, load_html_from_url(url)
    if file_path:
        return file_path, load_html_from_file(file_path)
    raise ValueError("Необходимо указать --url или --file.")


def render_report(result: AnalysisResult, output_format: str) -> str:
    if output_format == "json":
        payload = asdict(result)
        payload["issues"] = [asdict(item) for item in result.issues]
        return json.dumps(payload, ensure_ascii=False, indent=2)

    lines = [
        "SEO-аудит (эвристический отчет)",
        f"Источник: {result.source}",
        f"Оценка: {result.score}/100",
        "",
        "Примечание: оценка носит ориентировочный характер и нужна для приоритизации задач.",
        "",
    ]
    high_count = sum(1 for issue in result.issues if issue.priority == "HIGH")
    medium_count = sum(1 for issue in result.issues if issue.priority == "MEDIUM")
    low_count = sum(1 for issue in result.issues if issue.priority == "LOW")
    lines.extend(
        [
            "Сводка:",
            f"- Критично: {high_count}",
            f"- Важно: {medium_count}",
            f"- Желательно: {low_count}",
            "",
            "Топ-3 действия:",
        ]
    )
    sorted_issues = sorted(
        result.issues,
        key=lambda issue: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(issue.priority, 9),
    )
    top_steps = [issue.recommendation for issue in sorted_issues[:3]]
    if top_steps:
        for index, step in enumerate(top_steps, start=1):
            lines.append(f"- {index}. {step}")
    else:
        lines.append("- 1. Критичных проблем не обнаружено.")

    lines.extend(
        [
            "",
            "Метрики:",
        ]
    )
    for key, value in result.metrics.items():
        lines.append(f"- {key}: {value}")

    lines.append("")
    lines.append("Проблемы:")
    if result.issues:
        for issue in result.issues:
            lines.append(
                f"- [{issue.priority}] ({issue.category}) {issue.title}: {issue.recommendation}"
            )
    else:
        lines.append("- Проблем не найдено.")

    lines.append("")
    lines.append("Плотность ключевых слов (%):")
    if result.keyword_stats:
        for key, value in result.keyword_stats.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- Ключевые слова не заданы.")

    if result.ai_recommendations:
        lines.append("")
        lines.append("AI-рекомендации:")
        lines.append(result.ai_recommendations)

    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(run())
