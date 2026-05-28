# Telegram-Bot-TESTDM

Telegram-бот для сбора фидбека от респондентов с автоматической транскрибацией речи и зеркалированием данных в Google Drive.

## Возможности

- Регистрация респондентов по кодовому слову **ТЕСТДМ**
- Сбор анкеты: ФИО, возраст, пол, наличие и характеристики детей
- Приём фидбека в любом формате:
  - текстовые сообщения
  - голосовые сообщения (с транскрибацией)
  - аудиофайлы mp3/m4a/прочие (с транскрибацией)
  - видео (с извлечением аудио и транскрибацией)
  - круглые видеосообщения (с транскрибацией)
  - фотографии (с подписями)
  - документы любого типа
- Транскрибация русской речи через Yandex SpeechKit STT v3 с пунктуацией и капитализацией
- Человекочитаемая карточка респондента `card.md` с рабочими ссылками на медиа (генерируется автоматически)
- Автоматическое зеркалирование всех данных в Google Drive
- Сохранение состояний диалога между перезапусками (PicklePersistence) — фидбек не теряется при коротких простоях
- Whitelist пользователей по `telegram_id`
- Глобальный error handler — бот не падает при ошибках в отдельных запросах

## Как работает

1. Пользователь пишет боту `ТЕСТДМ`
2. Бот ведёт его через анкету (ConversationHandler с inline-клавиатурой)
3. После регистрации пользователь шлёт фидбек любого типа
4. Для каждого сообщения:
   - Файл сохраняется локально в `users/{telegram_id}/{тип}/`
   - Если это аудио или видео — `ffmpeg` извлекает звук в OggOpus, файл отправляется в Yandex STT v3 async, распознанный текст с пунктуацией записывается в `feedback.jsonl`
   - Карточка `card.md` пересобирается из актуального JSON
   - В фоне запускается заливка файлов в Google Drive (сохраняется та же структура папок)
5. Пользователь видит в чате расшифровку и подтверждение сохранения

Локальный диск (JSON) — canonical source of truth; `card.md` — человекочитаемое представление, Drive — резервная копия.

## Технологический стек

- Python 3.10+
- [python-telegram-bot 21.6](https://github.com/python-telegram-bot/python-telegram-bot) — асинхронный фреймворк
- [httpx](https://www.python-httpx.org/) — HTTP-клиент для Yandex API
- [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) — ffmpeg-бинарник внутри pip-пакета
- [google-api-python-client](https://github.com/googleapis/google-api-python-client) + google-auth-oauthlib — Google Drive
- [python-dotenv](https://github.com/theskumar/python-dotenv) — загрузка `.env`
- [Yandex SpeechKit STT v3](https://yandex.cloud/ru/docs/speechkit/) — транскрибация
- [Google Drive API](https://developers.google.com/drive/api) — синхронизация

## Установка

### 1. Клонировать репозиторий

```bash
git clone https://github.com/yzalessky/Telegram-Bot-TESTDM.git
cd Telegram-Bot-TESTDM
```

### 2. Установить зависимости

```bash
pip install -r requirements.txt
```

### 3. Получить токены

#### Telegram Bot Token

1. Откройте [@BotFather](https://t.me/BotFather) в Telegram
2. Команда `/newbot`, задайте имя и username
3. Скопируйте полученный токен

#### Yandex SpeechKit

1. Создайте аккаунт в [Yandex Cloud Console](https://console.cloud.yandex.ru/)
2. Создайте сервисный аккаунт с ролью `ai.speechkit-stt.user`
3. Создайте для него API-ключ
4. Скопируйте Folder ID из URL консоли (`console.cloud.yandex.ru/folders/<вот это>`)

#### Google Drive (опционально)

1. Создайте проект в [Google Cloud Console](https://console.cloud.google.com/)
2. Включите Google Drive API
3. Настройте OAuth consent screen (тип **External**, статус Testing)
4. Добавьте свой Google-email как Test user
5. Создайте OAuth Client ID типа **Desktop app**
6. Скачайте JSON, переименуйте в `credentials.json`, положите в корень проекта
7. Создайте папку в Google Drive, скопируйте её ID из URL

### 4. Настроить .env

Скопируйте `.env.example` в `.env` и заполните значения:

```
BOT_TOKEN=...
YANDEX_API_KEY=...
YANDEX_FOLDER_ID=...
GOOGLE_DRIVE_FOLDER_ID=...      # опционально
ALLOWED_TELEGRAM_IDS=123,456    # опционально (пусто = доступ открыт всем)
```

### 5. OAuth для Google Drive (если используется)

```bash
python auth_drive.py
```

Откроется браузер, войдите в Google, разрешите доступ. В корне создастся `token.json`.

### 6. Бэкфилл существующих данных в Drive (опционально)

Если в `users/` уже есть накопленные данные и вы хотите залить их в Drive одной командой:

```bash
python backfill_drive.py
```

## Запуск

```bash
python bot.py
```

Остановка — `Ctrl+C`.

## Структура проекта

```
.
├── bot.py              # точка входа, регистрация хендлеров, error handler, persistence
├── handlers.py         # хендлеры диалога регистрации и приёма медиа
├── states.py           # константы состояний ConversationHandler
├── user_manager.py     # сохранение профиля и feedback.jsonl, генерация card.md, триггер Drive
├── card_renderer.py    # сборка человекочитаемой карточки card.md из JSON
├── transcriber.py      # клиент Yandex SpeechKit STT v3
├── media_utils.py      # ffmpeg-обёртка для извлечения аудио
├── drive_sync.py       # асинхронный клиент Google Drive с кешем папок
├── auth_drive.py       # одноразовый OAuth flow
├── backfill_drive.py   # CLI-скрипт для бэкфилла существующих данных
├── requirements.txt
├── .env.example
├── bot_state.pickle    # состояния диалогов (gitignored, создаётся при запуске)
└── users/              # данные пользователей (gitignored)
    └── {telegram_id}/
        ├── profile.json    # анкета (источник данных)
        ├── feedback.jsonl  # поток сообщений (источник данных)
        ├── card.md         # человекочитаемая карточка (генерируется из JSON)
        ├── voice/
        ├── audio/
        ├── video/
        ├── photo/
        └── document/
```

## Формат данных

`profile.json` — анкета респондента:
```json
{
  "telegram_id": 123456789,
  "username": "@example",
  "name": "Иванов Иван Иванович",
  "age": 34,
  "gender": "Мужской",
  "has_children": true,
  "children": [{"index": 1, "info": "5 лет, мальчик"}],
  "registered_at": "2026-05-26T15:00:00"
}
```

`feedback.jsonl` — поток сообщений (по одному JSON на строку):
```json
{"type": "text", "text": "Очень удобный сервис", "timestamp": "..."}
{"type": "voice", "file": "voice/voice_20260526_152325_123.ogg", "duration_sec": 5, "transcript": "Распознанный текст.", "timestamp": "..."}
{"type": "video", "file": "video/...", "audio_extracted": "video/....ogg", "transcript": "...", "timestamp": "..."}
```

`card.md` — человекочитаемая карточка, **полностью пересобирается** из JSON при каждом обновлении. Содержит анкету таблицей, данные о детях и весь фидбек хронологически с рабочими относительными ссылками на медиа и расшифровками. Ссылки кликабельны при открытии в локальном Markdown-просмотрщике (VS Code, Obsidian, Typora). JSON остаётся источником данных — `card.md` можно безопасно удалить, он пересоздастся.

## Безопасность

- Все секреты (`.env`, `credentials.json`, `token.json`) исключены через `.gitignore`
- Папка `users/` с персональными данными и `bot_state.pickle` (промежуточные данные регистрации) также не коммитятся
- Расширения загруженных документов санитизируются (только буквенно-цифровые, до 10 символов)
- `subprocess.run` использует list-аргументы — command injection невозможен
- OAuth scope ограничен `drive.file` — бот не видит другие файлы вашего Drive
- Whitelist по `telegram_id` ограничивает круг пользователей
- Полные тексты исключений идут только в логи, пользователю показывается общее сообщение

## Известные ограничения

- OAuth-приложение в "Testing"-режиме Google: `refresh_token` действует **7 дней**, после чего нужно повторно запустить `auth_drive.py`. Для production-использования приложение нужно verify в Google
- Транскрибация настроена на русский язык (`ru-RU`)
- Размер файла ограничен лимитом Telegram Bot API — 20 МБ на скачивание
- Бот работает через polling — нужен постоянно запущенный процесс

## Лицензия

Учебный проект, без формальной лицензии.
