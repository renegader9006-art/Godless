from __future__ import annotations

import io
import os
import textwrap
from pathlib import Path
from typing import Any

from .models import AnalysisResult

PRIORITY_WEIGHT = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}

CATEGORY_EFFORT = {
    'Техническое SEO': 3,
    'Структура страницы': 2,
    'Качество контента': 3,
    'Интент и полезность': 3,
    'Доверие и E-E-A-T': 2,
    'Медиа и ссылки': 2,
}

PRIORITY_LABEL = {'HIGH': 'Критично', 'MEDIUM': 'Важно', 'LOW': 'Желательно'}


def _resolve_pdf_font_path() -> str | None:
    candidates: list[Path] = []
    env_path = os.getenv("PDF_FONT_PATH", "").strip()
    if env_path:
        candidates.append(Path(env_path))

    candidates.extend(
        [
            Path("assets/fonts/DejaVuSans.ttf"),
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        ]
    )

    for path in candidates:
        if path.exists():
            return str(path)
    return None


def build_roi_actions(result: AnalysisResult, limit: int = 8) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for issue in result.issues:
        impact = PRIORITY_WEIGHT.get(issue.priority, 1) * max(issue.penalty, 1)
        effort = CATEGORY_EFFORT.get(issue.category, 2)
        roi_score = round((impact / effort), 2)
        actions.append(
            {
                'priority': issue.priority,
                'priority_label': PRIORITY_LABEL.get(issue.priority, issue.priority),
                'category': issue.category,
                'title': issue.title,
                'recommendation': issue.recommendation,
                'impact': impact,
                'effort': effort,
                'roi_score': roi_score,
            }
        )

    actions.sort(
        key=lambda item: (
            -item['roi_score'],
            -PRIORITY_WEIGHT.get(item['priority'], 1),
            item['effort'],
        )
    )
    return actions[:limit]


def build_one_page_report(result: AnalysisResult, brand_name: str = 'SEO Audit') -> str:
    high_count = sum(1 for issue in result.issues if issue.priority == 'HIGH')
    medium_count = sum(1 for issue in result.issues if issue.priority == 'MEDIUM')
    low_count = sum(1 for issue in result.issues if issue.priority == 'LOW')
    top_risks = [issue for issue in result.issues if issue.priority in {'HIGH', 'MEDIUM'}][:5]
    roi_actions = build_roi_actions(result, limit=6)

    lines: list[str] = []
    lines.append(f'# {brand_name}: One-Page SEO Аудит')
    lines.append('')
    lines.append(f'- Источник: {result.source}')
    lines.append(f'- Эвристический индекс SEO-качества: {result.score}/100')
    lines.append(f'- Риски: Критично {high_count} | Важно {medium_count} | Желательно {low_count}')
    lines.append('- Важно: индекс используется для приоритизации задач и не является абсолютной истиной.')
    lines.append('')
    lines.append('## Ключевые Риски')
    if not top_risks:
        lines.append('- Критичных рисков не выявлено.')
    else:
        for issue in top_risks:
            lines.append(f"- [{PRIORITY_LABEL.get(issue.priority, issue.priority)}] {issue.title} ({issue.category})")

    lines.append('')
    lines.append('## ROI-Приоритеты (Что даст максимум эффекта при разумных усилиях)')
    if not roi_actions:
        lines.append('- Приоритетных действий не найдено.')
    else:
        for index, action in enumerate(roi_actions, start=1):
            lines.append(
                f"{index}. {action['title']} | ROI {action['roi_score']} | "
                f"Влияние {action['impact']} | Усилия {action['effort']}"
            )
            lines.append(f"   - Действие: {action['recommendation']}")

    lines.append('')
    lines.append('## Доказательность (фактические сигналы)')
    lines.append(f"- Indexability status: {result.metrics.get('indexability_status', 'n/a')}")
    lines.append(f"- Intent coverage: {result.metrics.get('intent_coverage_pct', 'n/a')}%")
    lines.append(f"- CTA status: {result.metrics.get('cta_status', 'n/a')}")
    lines.append(f"- Duplicate blocks: {result.metrics.get('duplicate_text_block_pct', 'n/a')}%")
    lines.append('')
    lines.append('## 30-Дневный План')
    lines.append('1. Неделя 1: закрыть критичные технические и структурные проблемы.')
    lines.append('2. Неделя 2: усилить полезность под интент и контентные блоки.')
    lines.append('3. Неделя 3: доработать E-E-A-T сигналы (автор, дата, контакты).')
    lines.append('4. Неделя 4: повторный аудит, сравнение метрик и фиксация прогресса.')
    lines.append('')
    lines.append('> Примечание: оценка и ROI-расчет являются эвристикой. Финальную валидацию делайте по данным GSC/GA4.')
    return '\n'.join(lines)


def markdown_to_pdf_bytes(markdown_text: str, title: str = 'SEO Audit Report') -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ImportError as error:
        raise RuntimeError(
            'Для экспорта PDF нужен пакет reportlab. Добавьте его в зависимости.'
        ) from error

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 40
    y = height - margin

    font_name = "Helvetica"
    font_path = _resolve_pdf_font_path()
    if font_path:
        font_name = "SEOReportFont"
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, font_path))

    title_font = font_name if font_name != "Helvetica" else "Helvetica-Bold"
    pdf.setFont(title_font, 14)
    pdf.drawString(margin, y, title)
    y -= 22
    pdf.setFont(font_name, 10)

    for raw_line in markdown_text.splitlines():
        normalized = raw_line.strip()
        if not normalized:
            y -= 8
            if y < margin:
                pdf.showPage()
                pdf.setFont(font_name, 10)
                y = height - margin
            continue

        wrapped = textwrap.wrap(raw_line, width=100, break_long_words=False) or [raw_line]
        for line in wrapped:
            if y < margin:
                pdf.showPage()
                pdf.setFont(font_name, 10)
                y = height - margin
            if font_name == "Helvetica":
                safe_line = line.encode('latin-1', 'replace').decode('latin-1')
            else:
                safe_line = line
            pdf.drawString(margin, y, safe_line)
            y -= 12

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()
