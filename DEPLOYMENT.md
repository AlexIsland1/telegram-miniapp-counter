# Деплоймент Telegram бота с системой напоминаний

## Варианты бесплатного хостинга

### 1. Railway (Рекомендуемый)

1. **Создайте аккаунт**: https://railway.app/
2. **Подключите GitHub репозиторий**
3. **Настройте переменные окружения**:
   ```
   BOT_TOKEN=ваш_токен_бота
   APP_URL=https://ваш-домен.railway.app
   ```
4. **Деплой**: Railway автоматически деплоит из main ветки

### 2. Render

1. **Создайте аккаунт**: https://render.com/
2. **Создайте Web Service** из GitHub репозитория  
3. **Настройте переменные**:
   ```
   BOT_TOKEN=ваш_токен_бота
   APP_URL=https://ваш-сервис.onrender.com
   ```

### 3. Fly.io

1. **Установите CLI**: `curl -L https://fly.io/install.sh | sh`
2. **Создайте app**: `fly apps create ваше-имя-app`
3. **Настройте secrets**:
   ```bash
   fly secrets set BOT_TOKEN=ваш_токен_бота
   fly secrets set APP_URL=https://ваше-имя-app.fly.dev
   ```
4. **Деплой**: `fly deploy`

## Особенности деплоя

### Что работает в облаке:
- ✅ Telegram бот (polling)
- ✅ Scheduler с проверкой каждые 5 минут
- ✅ Flask API для карточек
- ✅ SQLite база данных
- ✅ Интервальные напоминания

### Важные моменты:
- База данных SQLite сохраняется в файловой системе контейнера
- Логи пишутся в stdout (видны в консоли платформы)
- Бот и scheduler работают в одном процессе
- При падении - автоматический рестарт

## Тестирование

После деплоя проверьте:

1. **Бот отвечает**: `/start` в Telegram
2. **Веб-приложение**: Откройте APP_URL в браузере
3. **API работает**: APP_URL/api/stats
4. **Логи**: Проверьте логи в панели хостинга

## Мониторинг

### Railway:
- Логи: Railway Dashboard → Your App → Logs
- Метрики: Railway Dashboard → Metrics

### Render:
- Логи: Render Dashboard → Service → Logs  
- Статус: Dashboard → Service Status

## Решение проблем

### Бот не отвечает:
- Проверьте BOT_TOKEN в переменных окружения
- Проверьте логи на ошибки

### Scheduler не работает:
- Убедитесь что APP_URL правильный
- Проверьте логи scheduler в консоли

### База данных:
- SQLite автоматически создается при первом запуске
- Путь: `webapp/counter.db`