from __future__ import annotations

import os

import streamlit as st
from bs4 import BeautifulSoup

from seo_ai_analyzer.ai_layer import (
    generate_ai_recommendations,
    generate_improved_text_variants,
)
from seo_ai_analyzer.analyzer import analyze_html, analyze_text_article
from seo_ai_analyzer.fetcher import load_html_from_url
from seo_ai_analyzer.models import AnalysisResult


PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
PRIORITY_LABELS = {"HIGH": "Критично", "MEDIUM": "Важно", "LOW": "Желательно"}


def parse_keywords(raw: str) -> list[str]:
    return [keyword.strip() for keyword in raw.split(",") if keyword.strip()]


def sorted_issues(result: AnalysisResult):
    return sorted(result.issues, key=lambda issue: PRIORITY_ORDER.get(issue.priority, 9))


def _build_markdown_report(result: AnalysisResult) -> str:
    lines: list[str] = []
    lines.append("# SEO отчет")
    lines.append("")
    lines.append(f"- Источник: {result.source}")
    lines.append(f"- Итоговый балл: {result.score}/100")
    lines.append("")
    lines.append("## Проблемы")
    issues = sorted_issues(result)
    if not issues:
        lines.append("- Критичных проблем не найдено.")
    else:
        for issue in issues:
            priority_label = PRIORITY_LABELS.get(issue.priority, issue.priority)
            lines.append(f"- **{priority_label}**: {issue.title}. {issue.recommendation}")

    lines.append("")
    lines.append("## Метрики")
    for key, value in result.metrics.items():
        lines.append(f"- {key}: {value}")

    lines.append("")
    lines.append("## Плотность ключевых слов")
    if not result.keyword_stats:
        lines.append("- Недостаточно данных для расчета.")
    else:
        for keyword, value in result.keyword_stats.items():
            lines.append(f"- {keyword}: {value}%")
    return "\n".join(lines)


def render_result(result: AnalysisResult) -> str:
    st.subheader("SEO балл")
    st.metric("Итоговая оценка", f"{result.score}/100")
    st.progress(min(max(result.score, 0), 100) / 100)

    st.subheader("Найденные проблемы")
    issues = sorted_issues(result)
    if not issues:
        st.success("Критичных SEO-проблем не найдено.")
    else:
        for issue in issues:
            priority_label = PRIORITY_LABELS.get(issue.priority, issue.priority)
            st.markdown(f"**[{priority_label}] {issue.title}**")
            st.write(issue.recommendation)

    st.subheader("Метрики")
    st.json(result.metrics)

    st.subheader("Плотность ключевых слов (%)")
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
        st.write("1. Сохраните текущую структуру и публикуйте регулярные обновления.")
    else:
        for index, issue in enumerate(issues, start=1):
            st.write(f"{index}. {issue.recommendation}")
    return _build_markdown_report(result)


def maybe_render_ai_blocks(
    result: AnalysisResult,
    article_text: str,
    keywords: list[str],
    use_ai_recommendations: bool,
    generate_variants: bool,
    api_key: str,
    model: str,
) -> None:
    if not use_ai_recommendations and not generate_variants:
        return

    if not api_key:
        st.warning(
            "AI-опции включены, но API-ключ не задан. "
            "Добавьте OPENAI_API_KEY на сервере или укажите ключ в боковой панели."
        )
        return

    if use_ai_recommendations:
        with st.spinner("Формируем AI-рекомендации..."):
            ai_text = generate_ai_recommendations(
                result=result,
                api_key=api_key,
                model=model,
            )
        st.subheader("AI-рекомендации")
        st.markdown(ai_text or "Рекомендации не сгенерированы.")

    if generate_variants:
        if not article_text.strip():
            st.info("Нет исходного текста для генерации вариантов.")
            return
        issues_summary = [
            f"{issue.priority}: {issue.title}. {issue.recommendation}"
            for issue in sorted_issues(result)
        ]
        with st.spinner("Генерируем улучшенные варианты текста..."):
            variants_markdown = generate_improved_text_variants(
                source_text=article_text,
                issues_summary=issues_summary,
                keywords=keywords,
                api_key=api_key,
                model=model,
            )
        st.subheader("AI-варианты улучшенного текста")
        st.markdown(variants_markdown)


def main() -> None:
    st.set_page_config(page_title="SEO Аудит Контента", layout="wide")
    st.title("SEO Аудит Контента")
    st.caption(
        "Проверяйте URL-страницы или текст статьи, находите SEO-проблемы и получайте понятные рекомендации."
    )

    with st.sidebar:
        st.header("Настройки")
        raw_keywords = st.text_input(
            "Целевые ключевые слова (через запятую)",
            value="",
            help="Пример: seo, контент маркетинг, технический аудит",
        )
        use_ai_recommendations = st.checkbox("Сгенерировать AI-рекомендации", value=False)
        generate_variants = st.checkbox("Сгенерировать улучшенные варианты текста", value=False)
        api_key_input = st.text_input(
            "OpenAI API key (необязательно)",
            value="",
            type="password",
            help="Оставьте пустым, чтобы использовать OPENAI_API_KEY из окружения сервера.",
        )
        model = st.text_input("AI модель", value="gpt-4.1-mini")
        api_key = api_key_input.strip() or os.getenv("OPENAI_API_KEY", "")

    keywords = parse_keywords(raw_keywords)
    source_mode = st.radio("Тип входных данных", ["URL страницы", "Текст статьи"], horizontal=True)

    if source_mode == "URL страницы":
        url = st.text_input("URL страницы", placeholder="https://example.com/page")
        analyze_clicked = st.button("Запустить SEO-анализ", type="primary", key="analyze_url")
        if analyze_clicked:
            if not url.strip():
                st.error("Сначала введите URL.")
                return
            try:
                html = load_html_from_url(url.strip())
                result = analyze_html(source=url.strip(), html=html, keywords=keywords or None)
                article_text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            except Exception as error:
                st.error(f"Не удалось проанализировать URL: {error}")
                return

            markdown_report = render_result(result)
            st.download_button(
                "Скачать отчет (.md)",
                data=markdown_report,
                file_name="seo_report.md",
                mime="text/markdown",
            )
            maybe_render_ai_blocks(
                result=result,
                article_text=article_text,
                keywords=keywords,
                use_ai_recommendations=use_ai_recommendations,
                generate_variants=generate_variants,
                api_key=api_key,
                model=model,
            )
    else:
        title = st.text_input("Заголовок статьи (необязательно)")
        text = st.text_area("Текст статьи", height=340, placeholder="Вставьте текст статьи...")
        analyze_clicked = st.button("Запустить SEO-анализ", type="primary", key="analyze_text")
        if analyze_clicked:
            if not text.strip():
                st.error("Сначала вставьте текст статьи.")
                return

            result = analyze_text_article(
                source="article_text",
                text=text,
                keywords=keywords or None,
                title=title,
            )
            markdown_report = render_result(result)
            st.download_button(
                "Скачать отчет (.md)",
                data=markdown_report,
                file_name="seo_report.md",
                mime="text/markdown",
            )
            maybe_render_ai_blocks(
                result=result,
                article_text=text,
                keywords=keywords,
                use_ai_recommendations=use_ai_recommendations,
                generate_variants=generate_variants,
                api_key=api_key,
                model=model,
            )


if __name__ == "__main__":
    main()
