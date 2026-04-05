import unittest

from seo_ai_analyzer.analyzer import analyze_html, analyze_text_article


class AnalyzerSmokeTests(unittest.TestCase):
    def test_html_analysis_returns_categorized_issues(self) -> None:
        html = """
        <html lang="ru">
          <head>
            <title>Короткий</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
          </head>
          <body>
            <h1>Тест</h1>
            <p>Loading... лучший сервис 100% мгновенно</p>
          </body>
        </html>
        """
        result = analyze_html("https://example.com", html, keywords=["seo"])
        self.assertGreater(len(result.issues), 0)
        categories = {issue.category for issue in result.issues}
        self.assertIn("Техническое SEO", categories)
        self.assertIn("Интент и полезность", categories)

    def test_text_analysis_detects_content_depth_issue(self) -> None:
        text = "Очень короткий текст без структуры и практической пользы."
        result = analyze_text_article("article_text", text, keywords=["seo"], title="Тест")
        self.assertTrue(any("глубин" in issue.title.lower() for issue in result.issues))
        self.assertLess(result.score, 100)

    def test_keyword_density_for_target_keywords(self) -> None:
        text = "SEO аудит SEO стратегия контент SEO"
        result = analyze_text_article(
            "article_text",
            text,
            keywords=["seo", "контент"],
            title="SEO аудит",
        )
        self.assertIn("seo", result.keyword_stats)
        self.assertIn("контент", result.keyword_stats)


if __name__ == "__main__":
    unittest.main()
