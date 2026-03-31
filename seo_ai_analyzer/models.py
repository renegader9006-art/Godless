from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SEOIssue:
    priority: str
    title: str
    recommendation: str
    penalty: int


@dataclass(slots=True)
class AnalysisResult:
    source: str
    score: int
    metrics: dict[str, Any]
    issues: list[SEOIssue] = field(default_factory=list)
    keyword_stats: dict[str, float] = field(default_factory=dict)
    ai_recommendations: str | None = None
