import unittest
from unittest.mock import Mock, patch

from seo_ai_analyzer.integrations import (
    fetch_ga4_api_data,
    fetch_gsc_api_data,
    fetch_pagespeed_data,
    parse_ga4_csv,
    parse_gsc_csv,
)


class IntegrationsTests(unittest.TestCase):
    def test_parse_gsc_csv(self) -> None:
        csv_bytes = (
            "Query,Page,Clicks,Impressions,CTR,Position\n"
            "seo аудит,https://example.com/audit,10,100,0.1,8.2\n"
            "seo чек лист,https://example.com/checklist,5,80,0.0625,11.4\n"
        ).encode("utf-8")
        parsed = parse_gsc_csv(csv_bytes)
        self.assertTrue(parsed.get("ok"))
        self.assertEqual(parsed.get("rows"), 2)
        self.assertEqual(parsed.get("total_clicks"), 15.0)
        self.assertEqual(parsed.get("total_impressions"), 180.0)

    def test_parse_ga4_csv(self) -> None:
        csv_bytes = (
            "Landing page,Sessions,Users,Engagement rate,Conversions\n"
            "/audit,120,95,0.61,8\n"
            "/checklist,80,66,0.55,4\n"
        ).encode("utf-8")
        parsed = parse_ga4_csv(csv_bytes)
        self.assertTrue(parsed.get("ok"))
        self.assertEqual(parsed.get("rows"), 2)
        self.assertEqual(parsed.get("total_sessions"), 200.0)
        self.assertEqual(parsed.get("total_users"), 161.0)

    def test_fetch_pagespeed_data(self) -> None:
        payload = {
            "lighthouseResult": {
                "categories": {
                    "performance": {"score": 0.75},
                    "seo": {"score": 0.92},
                    "accessibility": {"score": 0.88},
                    "best-practices": {"score": 0.83},
                },
                "audits": {
                    "first-contentful-paint": {"numericValue": 1500.0},
                    "largest-contentful-paint": {"numericValue": 2300.0},
                    "total-blocking-time": {"numericValue": 120.0},
                    "cumulative-layout-shift": {"numericValue": 0.06},
                    "speed-index": {"numericValue": 2200.0},
                    "unused-css-rules": {"title": "Unused CSS", "score": 0.3, "displayValue": "120 KiB"},
                },
            },
            "loadingExperience": {
                "metrics": {
                    "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2400},
                    "EXPERIMENTAL_INTERACTION_TO_NEXT_PAINT": {"percentile": 210},
                    "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 0.08},
                }
            },
        }
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload

        with patch("seo_ai_analyzer.integrations.requests.get", return_value=response):
            parsed = fetch_pagespeed_data("https://example.com", "api-key", strategy="mobile")

        self.assertTrue(parsed.get("ok"))
        self.assertEqual(parsed.get("scores", {}).get("performance"), 75.0)
        self.assertEqual(parsed.get("strategy"), "mobile")
        self.assertGreater(len(parsed.get("opportunities", [])), 0)

    def test_gsc_api_validation(self) -> None:
        parsed = fetch_gsc_api_data("", "sc-domain:example.com", "2026-04-01", "2026-04-09")
        self.assertFalse(parsed.get("ok"))
        self.assertIn("Service Account", str(parsed.get("error", "")))

    def test_ga4_api_validation(self) -> None:
        parsed = fetch_ga4_api_data("{}", "", "2026-04-01", "2026-04-09")
        self.assertFalse(parsed.get("ok"))
        self.assertIn("Property ID", str(parsed.get("error", "")))


if __name__ == "__main__":
    unittest.main()
