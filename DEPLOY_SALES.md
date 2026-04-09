# Deploy and Sales Guide

Этот документ — практический план запуска SEO-сервиса в продажу по подписке.

## 1) Базовая инфраструктура

1. Подготовьте публичный репозиторий.
2. Настройте деплой Streamlit Cloud (или VPS + reverse proxy).
3. Проверьте доступность приложения по HTTPS-домену.

## 2) Переменные окружения

Используйте `.env` или Secrets в Streamlit Cloud.

```bash
OPENAI_API_KEY=your_openai_key
PAYMENT_PROVIDER=payment_links
PAYMENT_LINK_START=https://payment-provider/link-start
PAYMENT_LINK_GROWTH=https://payment-provider/link-growth
PAYMENT_LINK_SCALE=https://payment-provider/link-scale
PAYMENT_ALLOW_MANUAL_CONFIRM=false
```

Если вы на этапе демонстрации, можно временно использовать:

```bash
PAYMENT_PROVIDER=demo
PAYMENT_ALLOW_MANUAL_CONFIRM=true
```

## 3) Что проверить перед продажей

1. Регистрация и автоматический вход после регистрации.
2. Создание заказа в разделе `Тарифы`.
3. Переход на оплату (или demo-подтверждение).
4. Активация подписки после статуса `paid`.
5. Работа лимитов: URL audit, text audit, AI, export.
6. Экспорт `pdf/json/md`.

## 4) Рекомендации для production

1. Включите webhook-подтверждение оплат от платежного провайдера.
2. Отключите ручное подтверждение (`PAYMENT_ALLOW_MANUAL_CONFIRM=false`).
3. Добавьте резервное копирование `.seo_data/`.
4. Подключите мониторинг uptime и error-логов.

## 5) Коммерческая упаковка

1. Опубликуйте тарифную сетку и оффер.
2. Добавьте публичные документы: оферта и политика конфиденциальности.
3. Подготовьте demo-кейс с реальной страницей и результатом аудита.
4. Настройте воронку: лендинг -> регистрация -> тариф -> оплата.
