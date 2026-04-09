import unittest

from seo_ai_analyzer.analyzer import analyze_html, analyze_text_article


class AnalyzerSmokeTests(unittest.TestCase):
    def test_html_analysis_returns_categorized_issues(self) -> None:
        html = '''
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
        '''
        result = analyze_html('https://example.com', html, keywords=['seo'])
        self.assertGreater(len(result.issues), 0)
        categories = {issue.category for issue in result.issues}
        self.assertIn('Техническое SEO', categories)
        self.assertIn('Интент и полезность', categories)

    def test_text_analysis_detects_content_depth_issue(self) -> None:
        text = 'Очень короткий текст без структуры и практической пользы.'
        result = analyze_text_article('article_text', text, keywords=['seo'], title='Тест')
        self.assertTrue(any('глубина' in issue.title.lower() for issue in result.issues))
        self.assertLess(result.score, 100)

    def test_keyword_density_for_target_keywords(self) -> None:
        text = 'SEO аудит SEO стратегия контент SEO'
        result = analyze_text_article(
            'article_text',
            text,
            keywords=['seo', 'контент'],
            title='SEO аудит',
        )
        self.assertIn('seo', result.keyword_stats)
        self.assertIn('контент', result.keyword_stats)

    def test_cta_with_real_buttons_is_not_marked_missing(self) -> None:
        html = '''
        <html lang="ru">
          <head>
            <title>SEO аудит для бизнеса с готовыми действиями и отчетом</title>
            <meta name="description" content="Полноценный аудит контента, индексации и структуры страницы." />
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <link rel="canonical" href="https://example.com/audit">
          </head>
          <body>
            <h1>SEO аудит сайта</h1>
            <h2>Что проверяем</h2>
            <h2>Как внедрять</h2>
            <a href="/pricing">Get started</a>
            <button>Download report</button>
            <p>Подробный аудит, примеры и FAQ по внедрению.</p>
          </body>
        </html>
        '''
        result = analyze_html('https://example.com/audit', html, keywords=['seo аудит'])
        self.assertEqual(result.metrics.get('cta_status'), 'strong')
        self.assertFalse(any(issue.title == 'CTA не обнаружен' for issue in result.issues))

    def test_weak_cta_generates_soft_issue(self) -> None:
        html = '''
        <html lang="ru">
          <head>
            <title>Гайд по SEO для менеджера и команды</title>
            <meta name="description" content="Практический гайд по SEO-аудиту." />
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <link rel="canonical" href="https://example.com/guide">
          </head>
          <body>
            <h1>Гайд по SEO</h1>
            <h2>Чек-лист</h2>
            <h2>FAQ</h2>
            <a href="/more">Подробнее</a>
            <p>Что делать и как внедрить изменения.</p>
          </body>
        </html>
        '''
        result = analyze_html('https://example.com/guide', html, keywords=['seo'])
        self.assertEqual(result.metrics.get('cta_status'), 'weak')
        self.assertTrue(any(issue.title == 'CTA есть, но выглядит слабым' for issue in result.issues))


if __name__ == '__main__':
    unittest.main()
