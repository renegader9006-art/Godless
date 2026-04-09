# SEO Аудит Контента (Python)

Веб-инструмент для полноценного SEO-аудита контента страниц и текстов.

## Авторы

Проект выполняли: **faza** и **Fals043k**.

## Что делает сервис

- принимает URL страницы или текст статьи;
- формирует полноценный SEO-отчет по категориям (техника, структура, контент, интент, доверие, ссылки/медиа);
- дает понятные рекомендации по исправлению;
- строит one-page клиентский отчет с рисками и ROI-приоритетами;
- поддерживает экспорт отчетов в `.md`, `.json`, `.pdf`;
- поддерживает AI-блок:
  - OpenAI (облачный);
  - Ollama (локально, бесплатно, например Qwen).

## Важная оговорка по оценке

Итоговый балл в отчете — **эвристическая оценка** для приоритизации работ, а не абсолютная истина SEO.

## Что анализируется

- базовые on-page сигналы: title, description, H1/H2, alt, canonical, OpenGraph;
- качество структуры и глубины контента;
- признаки агрессивного copywriting;
- признаки повторяющегося/мусорного DOM;
- признаки проблем рендера (например, `Loading...` в финальном контенте);
- приблизительное покрытие интента пользователя;
- сигналы доверия (автор, дата, контакты);
- структурированные данные (JSON-LD, FAQ/Breadcrumb сигналы);
- плотность ключевых слов как вторичный, слабый сигнал.

## Установка

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Запуск веб-приложения

```powershell
streamlit run web_app.py
```

Открыть: `http://127.0.0.1:8501`

## Запуск CLI

```powershell
python -m seo_ai_analyzer --file index.html
python -m seo_ai_analyzer --url https://example.com
python -m seo_ai_analyzer --file index.html --format json --output report.json
```

## Проверка Тестами

```powershell
python -m unittest tests\test_analyzer_smoke.py -v
```

## AI: OpenAI

```powershell
$env:OPENAI_API_KEY="ваш_ключ"
```

## AI: Ollama (бесплатно, локально)

1. Установите Ollama.
2. Скачайте модель, например:

```powershell
ollama pull qwen2.5:7b
```

3. Запустите Ollama (обычно API на `http://127.0.0.1:11434`).
4. В приложении выберите провайдер `Ollama (локально, бесплатно)`.

## Публичный деплой (Streamlit Cloud)

1. Загрузите проект в GitHub.
2. В Streamlit Cloud создайте app:
   - Repository: ваш репозиторий;
   - Branch: `main`;
   - Main file path: `web_app.py`.
3. Для OpenAI добавьте Secret:

```toml
OPENAI_API_KEY="ваш_ключ"
```

Для продажи тарифов через платежные ссылки добавьте в Secrets:

```toml
PAYMENT_PROVIDER="payment_links"
PAYMENT_LINK_START="https://..."
PAYMENT_LINK_GROWTH="https://..."
PAYMENT_LINK_SCALE="https://..."
PAYMENT_ALLOW_MANUAL_CONFIRM="false"
```

## Структура проекта

```text
seo_ai_analyzer/
  __main__.py
  cli.py
  analyzer.py
  fetcher.py
  ai_layer.py
  models.py
web_app.py
CLIENT_READY_CHECKLIST.md
HOW_TO_PRESENT.md
requirements.txt
```

## Новые возможности (client-ready)

- Конкурентный бенчмарк: сравнение вашей страницы с конкурентами по score, intent, структуре и контенту.
- Авто-поиск конкурентов по SERP-запросу (DuckDuckGo) + ручной список конкурентов.
- Регистрация и вход пользователей (локальная SQLite-база) перед доступом к функционалу.
- Query/Intent audit: покрытие целевых запросов со статусами `covered / partial / gap`.
- Action Pack с готовыми артефактами:
  - JSON-LD (Article/FAQ),
  - meta title/description в 3 вариантах,
  - H1/H2-outline,
  - content brief,
  - блок "что добавить на страницу",
  - internal links,
  - dev tickets.
- История и мониторинг:
  - snapshots по проектам/workspaces,
  - changelog с прошлого краула,
  - alerts (score drop, noindex, canonical, контентные просадки),
  - webhook-отправка алертов.
- White-label one-page отчет и экспорты: `.md`, `.json`, `.pdf`, `dev tickets.md`, `changelog.md`.

## Монетизация и продажи

- Раздел `Тарифы` теперь работает через checkout-заказы (`pending -> paid -> active`).
- Поддерживаются два режима оплаты:
  - `demo` (ручное подтверждение в интерфейсе);
  - `payment_links` (внешние ссылки оплаты по тарифам).
- Раздел `Запуск` показывает чеклист готовности к продаже.

## Документы запуска

- `DEPLOY_SALES.md` — пошаговый запуск SaaS и продаж.
- `PUBLIC_OFFER.md` — шаблон оферты.
- `PRIVACY_POLICY.md` — шаблон политики конфиденциальности.
- `.env.example` — пример переменных окружения.
