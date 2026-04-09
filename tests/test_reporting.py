import unittest

from seo_ai_analyzer.models import AnalysisResult, SEOIssue
from seo_ai_analyzer.reporting import build_one_page_report, build_roi_actions, markdown_to_pdf_bytes


class ReportingTests(unittest.TestCase):
    def test_build_roi_actions_sorted(self) -> None:
        result = AnalysisResult(
            source='test',
            score=70,
            metrics={},
            issues=[
                SEOIssue(
                    priority='LOW',
                    category='Медиа и ссылки',
                    title='Low issue',
                    recommendation='Fix low',
                    penalty=1,
                ),
                SEOIssue(
                    priority='HIGH',
                    category='Техническое SEO',
                    title='High issue',
                    recommendation='Fix high',
                    penalty=9,
                ),
            ],
        )
        actions = build_roi_actions(result)
        self.assertGreater(len(actions), 0)
        self.assertEqual(actions[0]['title'], 'High issue')

    def test_one_page_contains_sections(self) -> None:
        result = AnalysisResult(
            source='test',
            score=80,
            metrics={},
            issues=[
                SEOIssue(
                    priority='MEDIUM',
                    category='Качество контента',
                    title='Content issue',
                    recommendation='Improve content',
                    penalty=4,
                )
            ],
        )
        report = build_one_page_report(result)
        self.assertIn('One-Page SEO Аудит', report)
        self.assertIn('ROI-Приоритеты', report)
        self.assertIn('30-Дневный План', report)

    def test_pdf_export_handles_cyrillic_text(self) -> None:
        pdf = markdown_to_pdf_bytes("# Отчет\n\nПривет мир")
        self.assertGreater(len(pdf), 500)


if __name__ == '__main__':
    unittest.main()
