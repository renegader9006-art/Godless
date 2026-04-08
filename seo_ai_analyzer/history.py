from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_ROOT = Path('.seo_data')


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r'[^A-Za-zА-Яа-яЁё0-9._-]+', '_', value.strip())
    return cleaned or 'default'


def source_key(source: str) -> str:
    return sanitize_name(source.replace('https://', '').replace('http://', ''))


def get_project_dir(project: str, workspace: str) -> Path:
    project_slug = sanitize_name(project)
    workspace_slug = sanitize_name(workspace or 'main')
    return DATA_ROOT / project_slug / workspace_slug


def load_previous_snapshot(project: str, workspace: str, source: str) -> dict[str, Any] | None:
    source_dir = get_project_dir(project, workspace) / source_key(source)
    if not source_dir.exists():
        return None
    files = sorted(source_dir.glob('*.json'))
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding='utf-8'))


def save_snapshot(project: str, workspace: str, source: str, payload: dict[str, Any]) -> Path:
    source_dir = get_project_dir(project, workspace) / source_key(source)
    source_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path = source_dir / f'{now}.json'
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def build_changelog(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> list[str]:
    if previous is None:
        return ['Первый краул: базовая точка создана.']

    changes: list[str] = []
    prev_score = int(previous.get('score', 0))
    curr_score = int(current.get('score', 0))
    delta = curr_score - prev_score
    if delta > 0:
        changes.append(f'Эвристическая оценка выросла на {delta} пунктов ({prev_score} -> {curr_score}).')
    elif delta < 0:
        changes.append(f'Эвристическая оценка снизилась на {abs(delta)} пунктов ({prev_score} -> {curr_score}).')
    else:
        changes.append('Эвристическая оценка не изменилась.')

    prev_metrics = previous.get('metrics', {})
    curr_metrics = current.get('metrics', {})
    monitored = [
        'word_count',
        'h1_count',
        'h2_count',
        'has_canonical',
        'has_noindex',
        'intent_coverage_pct',
    ]
    for key in monitored:
        if str(prev_metrics.get(key)) != str(curr_metrics.get(key)):
            changes.append(f'{key}: {prev_metrics.get(key)} -> {curr_metrics.get(key)}')

    prev_issues = {(item.get('title'), item.get('priority')) for item in previous.get('issues', [])}
    curr_issues = {(item.get('title'), item.get('priority')) for item in current.get('issues', [])}
    resolved = prev_issues - curr_issues
    appeared = curr_issues - prev_issues
    if resolved:
        changes.append(f'Закрыто проблем: {len(resolved)}')
    if appeared:
        changes.append(f'Новых проблем: {len(appeared)}')

    return changes


def build_alerts(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> list[str]:
    alerts: list[str] = []
    if previous is None:
        return alerts

    prev_metrics = previous.get('metrics', {})
    curr_metrics = current.get('metrics', {})

    prev_score = int(previous.get('score', 0))
    curr_score = int(current.get('score', 0))
    if curr_score < prev_score - 10:
        alerts.append(f'ALERT: score упал более чем на 10 пунктов ({prev_score} -> {curr_score}).')

    if int(prev_metrics.get('has_noindex', 0)) == 0 and int(curr_metrics.get('has_noindex', 0)) == 1:
        alerts.append('ALERT: страница стала noindex.')

    if int(prev_metrics.get('has_canonical', 0)) == 1 and int(curr_metrics.get('has_canonical', 0)) == 0:
        alerts.append('ALERT: canonical пропал.')

    prev_words = int(prev_metrics.get('word_count', 0))
    curr_words = int(curr_metrics.get('word_count', 0))
    if prev_words > 0 and curr_words < prev_words * 0.7:
        alerts.append(f'ALERT: объем контента снизился более чем на 30% ({prev_words} -> {curr_words}).')

    return alerts
