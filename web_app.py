from __future__ import annotations

import json
import os
from dataclasses import asdict

import requests
import streamlit as st
from bs4 import BeautifulSoup

from seo_ai_analyzer.ai_layer import (
    generate_ai_recommendations,
    generate_ai_recommendations_ollama,
    generate_improved_text_variants,
    generate_improved_text_variants_ollama,
)
from seo_ai_analyzer.analyzer import analyze_html, analyze_text_article
from seo_ai_analyzer.fetcher import load_html_from_url
from seo_ai_analyzer.models import AnalysisResult
from seo_ai_analyzer.reporting import (
    build_one_page_report,
    build_roi_actions,
    markdown_to_pdf_bytes,
)


PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
PRIORITY_LABELS = {"HIGH": "Критично", "MEDIUM": "Важно", "LOW": "Желательно"}
AI_PROVIDERS = ("Без AI", "OpenAI", "Ollama (локально, бесплатно)")


def parse_keywords(raw: str) -> list[str]:
    return [keyword.strip() for keyword in raw.split(",") if keyword.strip()]


def sorted_issues(result: AnalysisResult):
    return sorted(result.issues, key=lambda issue: PRIORITY_ORDER.get(issue.priority, 9))


def category_summary(result: AnalysisResult) -> dict[str, int]:
    summary: dict[str, int] = {}
    for issue in result.issues:
        summary[issue.category] = summary.get(issue.category, 0) + 1
    return dict(sorted(summary.items(), key=lambda item: item[0]))


def init_session_state() -> None:
    defaults = {
        "analysis_result": None,
        "analysis_text": "",
        "analysis_source": "",
        "analysis_report_md": "",
        "analysis_keywords": [],
        "ai_recommendations": "",
        "ai_variants": "",
        "one_page_report_md": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _build_markdown_report(result: AnalysisResult) -> str:
    lines: list[str] = []
    lines.append("# SEO-отчет")
    lines.append("")
    lines.append("> Важно: итоговый балл является эвристической оценкой, а не абсолютной SEO-истиной.")
    lines.append("")
    lines.append(f"- Источник: {result.source}")
    lines.append(f"- Эвристическая оценка: {result.score}/100")
    lines.append("")
    lines.append("## Проблемы")
    issues = sorted_issues(result)
    if not issues:
        lines.append("- Критичных проблем не найдено.")
    else:
        for issue in issues:
            priority_label = PRIORITY_LABELS.get(issue.priority, issue.priority)
            lines.append(
                f"- **{priority_label} / {issue.category}**: {issue.title}. {issue.recommendation}"
            )

    lines.append("")
    lines.append("## Метрики")
    for key, value in result.metrics.items():
        lines.append(f"- {key}: {value}")

    lines.append("")
    lines.append("## Плотность ключевых слов (вспомогательный сигнал)")
    if not result.keyword_stats:
        lines.append("- Недостаточно данных для расчета.")
    else:
        for keyword, value in result.keyword_stats.items():
            lines.append(f"- {keyword}: {value}%")
    return "\n".join(lines)


def render_result(result: AnalysisResult) -> str:
    high_count = sum(1 for issue in result.issues if issue.priority == "HIGH")
    medium_count = sum(1 for issue in result.issues if issue.priority == "MEDIUM")
    low_count = sum(1 for issue in result.issues if issue.priority == "LOW")

    st.subheader("Executive Summary")
    c1, c2, c3 = st.columns(3)
    c1.metric("Критично", high_count)
    c2.metric("Важно", medium_count)
    c3.metric("Желательно", low_count)

    quick_wins = [
        issue.recommendation
        for issue in sorted_issues(result)
        if issue.priority in {"HIGH", "MEDIUM"}
    ][:3]
    if quick_wins:
        st.caption("Топ-3 приоритетных шага:")
        for idx, win in enumerate(quick_wins, start=1):
            st.write(f"{idx}. {win}")

    st.subheader("ROI-Приоритеты")
    roi_actions = build_roi_actions(result, limit=6)
    if roi_actions:
        st.table(
            [
                {
                    "priority": item["priority_label"],
                    "category": item["category"],
                    "title": item["title"],
                    "roi_score": item["roi_score"],
                    "effort": item["effort"],
                }
                for item in roi_actions
            ]
        )

    st.subheader("Эвристическая SEO-оценка")
    st.metric("Итог", f"{result.score}/100")
    st.progress(min(max(result.score, 0), 100) / 100)
    st.caption("Оценка — ориентир для приоритизации работ, а не абсолютный вердикт качества SEO.")

    st.subheader("Найденные проблемы")
    issues = sorted_issues(result)
    if not issues:
        st.success("Критичных SEO-проблем не найдено.")
    else:
        summary = category_summary(result)
        st.caption(
            "Сводка по категориям: "
            + ", ".join(f"{category}: {count}" for category, count in summary.items())
        )
        for issue in issues:
            priority_label = PRIORITY_LABELS.get(issue.priority, issue.priority)
            st.markdown(f"**[{priority_label}] {issue.title}**")
            st.caption(issue.category)
            st.write(issue.recommendation)

    st.subheader("Метрики")
    st.json(result.metrics)

    st.subheader("Плотность ключевых слов")
    st.caption("Это вторичный сигнал. Используйте его вместе с анализом интента и полезности.")
    if result.keyword_stats:
        st.table(
            [
                {"keyword": keyword, "density_pct": density}
                for keyword, density in result.keyword_stats.items()
            ]
        )
    else:
        st.info("Недостаточно текста для расчета плотности ключевых слов.")

    st.subheader("Пошаговый план улучшений")
    if not issues:
        st.write("1. Сохраните структуру и регулярно обновляйте контент.")
    else:
        for index, issue in enumerate(issues, start=1):
            st.write(f"{index}. {issue.recommendation}")

    return _build_markdown_report(result)


def _save_analysis_result(
    result: AnalysisResult,
    source_text: str,
    source_label: str,
    keywords: list[str],
) -> None:
    st.session_state["analysis_result"] = result
    st.session_state["analysis_text"] = source_text
    st.session_state["analysis_source"] = source_label
    st.session_state["analysis_keywords"] = keywords
    st.session_state["analysis_report_md"] = _build_markdown_report(result)
    st.session_state["one_page_report_md"] = build_one_page_report(result)
    st.session_state["ai_recommendations"] = ""
    st.session_state["ai_variants"] = ""


def maybe_run_ai(
    provider: str,
    model: str,
    api_key: str,
    ollama_base_url: str,
) -> None:
    result: AnalysisResult | None = st.session_state.get("analysis_result")
    article_text = st.session_state.get("analysis_text", "")
    keywords = st.session_state.get("analysis_keywords", [])
    if result is None:
        st.info("Сначала запустите анализ.")
        return

    ollama_available = True
    ollama_error = ""
    if provider != "OpenAI":
        ollama_available, ollama_error = _check_ollama_available(ollama_base_url)
        if not ollama_available:
            st.warning(
                f"{ollama_error} Если приложение запущено в Streamlit Cloud, "
                "выберите OpenAI или запускайте Ollama-режим локально."
            )

    col1, col2 = st.columns(2)
    with col1:
        rec_clicked = st.button(
            "Сгенерировать AI-рекомендации",
            disabled=(provider != "OpenAI" and not ollama_available),
        )
    with col2:
        variants_clicked = st.button(
            "Сгенерировать улучшенный текст",
            disabled=(provider != "OpenAI" and not ollama_available),
        )

    if rec_clicked:
        with st.spinner("Генерируем рекомендации..."):
            if provider == "OpenAI":
                text = generate_ai_recommendations(result=result, api_key=api_key, model=model)
            else:
                text = generate_ai_recommendations_ollama(
                    result=result,
                    model=model,
                    base_url=ollama_base_url,
                )
        st.session_state["ai_recommendations"] = text or ""

    if variants_clicked:
        if not article_text.strip():
            st.warning("Нет исходного текста для переработки.")
        else:
            issues_summary = [
                f"{issue.priority}: {issue.title}. {issue.recommendation}"
                for issue in sorted_issues(result)
            ]
            with st.spinner("Генерируем варианты текста..."):
                if provider == "OpenAI":
                    text = generate_improved_text_variants(
                        source_text=article_text,
                        issues_summary=issues_summary,
                        keywords=keywords,
                        api_key=api_key,
                        model=model,
                    )
                else:
                    text = generate_improved_text_variants_ollama(
                        source_text=article_text,
                        issues_summary=issues_summary,
                        keywords=keywords,
                        model=model,
                        base_url=ollama_base_url,
                    )
            st.session_state["ai_variants"] = text or ""

    if st.session_state.get("ai_recommendations"):
        st.subheader("AI-рекомендации")
        st.markdown(st.session_state["ai_recommendations"])

    if st.session_state.get("ai_variants"):
        st.subheader("AI-варианты улучшенного текста")
        st.markdown(st.session_state["ai_variants"])


def _check_ollama_available(base_url: str) -> tuple[bool, str]:
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        response = requests.get(url, timeout=3)
        response.raise_for_status()
        return True, ""
    except requests.exceptions.RequestException:
        return (
            False,
            f"Не удалось подключиться к Ollama по адресу {base_url}.",
        )


def main() -> None:
    st.set_page_config(page_title="SEO Аудит Контента", layout="wide")
    init_session_state()

    st.title("SEO Аудит Контента")
    st.caption("Менеджерский режим: вставьте URL и получите отчет. Расширенные режимы доступны ниже.")

    with st.sidebar:
        st.header("Настройки")
        raw_keywords = st.text_input(
            "Ключевые слова (через запятую)",
            value="",
            help="Пример: seo, аудит сайта, контент",
        )
        provider = st.selectbox("AI-провайдер", AI_PROVIDERS, index=0)

        api_key_input = ""
        ollama_base_url = "http://127.0.0.1:11434"
        if provider == "OpenAI":
            api_key_input = st.text_input(
                "OpenAI API key (необязательно)",
                value="",
                type="password",
                help="Оставьте пустым для OPENAI_API_KEY из окружения.",
            )
            model = st.text_input("Модель OpenAI", value="gpt-4.1-mini")
        elif provider == "Ollama (локально, бесплатно)":
            model = st.text_input("Модель Ollama", value="qwen2.5:7b")
            ollama_base_url = st.text_input(
                "URL Ollama API",
                value="http://127.0.0.1:11434",
            )
            st.caption("Ollama работает локально. На Streamlit Cloud обычно недоступен.")
        else:
            model = ""

        api_key = api_key_input.strip() or os.getenv("OPENAI_API_KEY", "")

    keywords = parse_keywords(raw_keywords)

    st.subheader("Быстрый режим: анализ URL")
    with st.form("url_form"):
        url = st.text_input("URL страницы", placeholder="https://example.com/page")
        run_url = st.form_submit_button("Запустить анализ", type="primary")

    if run_url:
        if not url.strip():
            st.error("Введите URL страницы.")
        else:
            try:
                html = load_html_from_url(url.strip())
                result = analyze_html(source=url.strip(), html=html, keywords=keywords or None)
                source_text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
                _save_analysis_result(result, source_text=source_text, source_label=url.strip(), keywords=keywords)
                st.success("Анализ URL выполнен.")
            except Exception as error:
                st.error(f"Не удалось проанализировать URL: {error}")

    with st.expander("Режим редактора: анализ текста статьи", expanded=False):
        with st.form("text_form"):
            title = st.text_input("Заголовок статьи (необязательно)")
            text = st.text_area("Текст статьи", height=280, placeholder="Вставьте текст статьи...")
            run_text = st.form_submit_button("Запустить анализ текста")
        if run_text:
            if not text.strip():
                st.error("Вставьте текст статьи.")
            else:
                result = analyze_text_article(
                    source="article_text",
                    text=text,
                    keywords=keywords or None,
                    title=title,
                )
                _save_analysis_result(result, source_text=text, source_label="article_text", keywords=keywords)
                st.success("Анализ текста выполнен.")

    current_result: AnalysisResult | None = st.session_state.get("analysis_result")
    if current_result is not None:
        report_md = render_result(current_result)
        st.session_state["analysis_report_md"] = report_md
        one_page_report_md = st.session_state.get("one_page_report_md", "")
        report_json = json.dumps(
            {
                **asdict(current_result),
                "issues": [asdict(issue) for issue in current_result.issues],
            },
            ensure_ascii=False,
            indent=2,
        )
        d1, d2, d3 = st.columns(3)
        with d1:
            st.download_button(
                "Скачать отчет (.md)",
                data=st.session_state["analysis_report_md"],
                file_name="seo_report.md",
                mime="text/markdown",
                key="download_report_md_btn",
            )
        with d2:
            st.download_button(
                "Скачать отчет (.json)",
                data=report_json,
                file_name="seo_report.json",
                mime="application/json",
                key="download_report_json_btn",
            )
        with d3:
            try:
                pdf_bytes = markdown_to_pdf_bytes(
                    one_page_report_md or st.session_state["analysis_report_md"],
                    title="SEO One-Page Audit",
                )
                st.download_button(
                    "Скачать one-page (.pdf)",
                    data=pdf_bytes,
                    file_name="seo_one_page_report.pdf",
                    mime="application/pdf",
                    key="download_onepage_pdf_btn",
                )
            except RuntimeError as error:
                st.caption(str(error))

        if one_page_report_md:
            with st.expander("One-Page Отчет (для клиента)", expanded=False):
                st.markdown(one_page_report_md)
                st.download_button(
                    "Скачать one-page (.md)",
                    data=one_page_report_md,
                    file_name="seo_one_page_report.md",
                    mime="text/markdown",
                    key="download_onepage_md_btn",
                )

        st.divider()
        st.subheader("AI-блок")
        if provider == "Без AI":
            st.info("Выберите AI-провайдер в настройках, чтобы активировать генерацию.")
        elif provider == "OpenAI" and not api_key:
            st.warning("Для OpenAI нужен API-ключ (в поле в sidebar или через OPENAI_API_KEY).")
        else:
            maybe_run_ai(
                provider=provider,
                model=model,
                api_key=api_key,
                ollama_base_url=ollama_base_url,
            )


if __name__ == "__main__":
    main()
