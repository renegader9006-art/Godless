import unittest
from unittest.mock import Mock, patch

from seo_ai_analyzer.competitive import discover_competitors


class CompetitiveTests(unittest.TestCase):
    def test_discover_competitors_skips_duckduckgo_redirect_domains(self) -> None:
        html = """
        <html><body>
            <a class="result__a" href="/l/?uddg=https%3A%2F%2Falpha.example%2Fpage">Alpha</a>
            <a class="result__a" href="/l/?uddg=https%3A%2F%2Fbeta.example%2Fpost">Beta</a>
            <a class="result__a" href="https://duckduckgo.com/">DuckDuckGo</a>
        </body></html>
        """
        response = Mock()
        response.text = html
        response.raise_for_status.return_value = None

        with patch("seo_ai_analyzer.competitive.requests.get", return_value=response):
            result = discover_competitors("seo аудит", "https://target.example", limit=5)

        self.assertIn("https://alpha.example/page", result)
        self.assertIn("https://beta.example/post", result)
        self.assertFalse(any("duckduckgo.com" in item for item in result))


if __name__ == "__main__":
    unittest.main()
