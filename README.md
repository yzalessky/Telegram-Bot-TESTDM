# Telegram-Bot-TESTDM

Telegram-бот для сбора фидбека от респондентов в UX/продуктовом исследовании: регистрация, приём сообщений в любом формате, транскрибация русской речи, человекочитаемые карточки, зеркалирование в Google Drive и **живой канал «исследователь ↔ респондент»** через Telegram Forum Topics.

## Возможности

- Регистрация респондентов по кодовому слову **ТЕСТДМ** + анкета (ФИО, возраст, пол, дети)
- Приём фидбека в любом формате: текст, голосовое, аудиофайл, видео, кружок, фото, документ
- Транскрибация русской речи через **Yandex SpeechKit STT v3** (пунктуация, капитализация)
- **Очистка транскриптов** (опционально, через подписку Claude — без платного API): исправление ошибок распознавания и сегментации без переформулировки; сырой STT всегда сохраняется
- Человекочитаемая карточка респондента `card.md` с рабочими ссылками на медиа
- **Взаимодействие с исследователями через Forum Topics**: каждое сообщение респондента уходит в персональную тему группового чата; исследователь reply'ем или `/ask` задаёт уточняющий вопрос; ответ возвращается в тему и привязывается к исходному фидбеку
- Зеркалирование всех данных в Google Drive (фоново, fire-and-forget)
- Сохранение состояний диалога между перезапусками (`PicklePersistence`)
- Whitelist пользователей по `telegram_id`, глобальный error handler

## Как работает

### Сбор фидбека (респондент)
1. Пользователь пишет боту `ТЕСТДМ` → анкета (`ConversationHandler`) → `profile.json`.
2. Дальше любое сообщение респондента:
   - файл сохраняется локально в `users/{telegram_id}/{тип}/` (имя с миллисекундной меткой);
   - аудио/видео → `ffmpeg` извлекает звук в OggOpus → Yandex STT v3 (двухэтапный async API);
   - запись добавляется в `feedback.jsonl`, карточка `card.md` пересобирается;
   - файлы фоном заливаются в Google Drive;
   - если настроен мост исследователей — сообщение дублируется в тему группы.

Локальный JSON — источник истины; `card.md` и Drive — производные.

### Взаимодействие с исследователями (Forum Topics)
- При регистрации создаётся **тема** в групповом чате исследователей с именем `ФИО · @username · #id` и закреплённой сводкой профиля.
- Каждое сообщение респондента дублируется в его тему (медиа + расшифровка), под заголовком **«Респондент:»**.
- Исследователь задаёт уточняющий вопрос **явным жестом**:

  | Действие в теме | Результат |
  |---|---|
  | **Reply** на сообщение респондента | Вопрос → респонденту, привязан к этому фидбеку |
  | **Reply** на закреплённую сводку профиля | Общий вопрос → респонденту |
  | **`/ask <текст>`** | Общий вопрос → респонденту |
  | Обычный текст / reply другому исследователю | Внутренняя дискуссия, респонденту **не** уходит |

- Респондент получает вопрос с подписью **«Сообщение от исследователя:»**, реплаем на своё исходное сообщение (видит контекст).
- Ответ респондента возвращается в тему **реплаем на сообщение-вопрос** и в `card.md` встаёт вложенным тредом под нужным фидбеком (`id`/`parent_id`).
- Ответы бота респонденту после регистрации подписаны **«Бот-помощник:»**.

### Очистка транскриптов (опционально)
Сырые расшифровки STT можно «причесать» для удобного чтения, **строго сохраняя смысл и слова говорящего** (исправляются только ошибки распознавания и сегментации). Реализовано как Claude Code / Cowork **скилл `clean-transcripts`** — работает на локальных файлах через подписку, без платного API. Добавляет поле `transcript_clean`; сырой `transcript` никогда не теряется. `card.md` показывает очищенную версию + строку «STT-оригинал» при отличии.

## Технологический стек

- Python 3.11+
- [python-telegram-bot 21.6](https://github.com/python-telegram-bot/python-telegram-bot) — асинхронный фреймворк (Forum Topics, PicklePersistence)
- [httpx](https://www.python-httpx.org/) — HTTP-клиент для Yandex API
- [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) — ffmpeg внутри pip-пакета
- [google-api-python-client](https://github.com/googleapis/google-api-python-client) + google-auth-oauthlib — Google Drive
- [python-dotenv](https://github.com/theskumar/python-dotenv) — конфиг из `.env`
- [Yandex SpeechKit STT v3](https://yandex.cloud/ru/docs/speechkit/) — транскрибация

## Установка

```bash
git clone https://github.com/yzalessky/Telegram-Bot-TESTDM.git
cd Telegram-Bot-TESTDM
pip install -r requirements.txt
```

### Получить токены и ключи

**Telegram:** [@BotFather](https://t.me/BotFather) → `/newbot` → токен.

**Yandex SpeechKit:** [Yandex Cloud Console](https://console.cloud.yandex.ru/) → сервисный аккаунт с ролью `ai.speechkit-stt.user` → API-ключ; Folder ID из URL консоли.

**Google Drive (опционально):** [Google Cloud Console](https://console.cloud.google.com/) → включить Drive API → OAuth consent screen (External, Testing) → добавить себя в Test users → OAuth Client ID типа **Desktop app** → скачать JSON, переименовать в `credentials.json` в корень. Создать папку в Drive, взять её ID из URL.

**Группа исследователей (опционально):** создать супергруппу → включить **Topics** (форум) → добавить бота **админом** с правом **«Управление темами»**. Узнать `chat_id`: добавить бота в группу, запустить, отправить в группе `/chatid` — бот ответит id вида `-100…`.

### Настроить .env

Скопируйте `.env.example` в `.env`:
```
BOT_TOKEN=...
YANDEX_API_KEY=...
YANDEX_FOLDER_ID=...
GOOGLE_DRIVE_FOLDER_ID=...      # опционально (зеркало в Drive)
RESEARCHER_GROUP_ID=-100...     # опционально (мост исследователей)
ALLOWED_TELEGRAM_IDS=123,456    # опционально (пусто = доступ всем)
```

### OAuth для Google Drive (если используется)
```bash
python auth_drive.py     # откроется браузер; создаст token.json
```

## Запуск

```bash
python bot.py            # Ctrl+C для остановки
```

Вспомогательные скрипты:
- `python backfill_drive.py` — разово залить всё из `users/` в Drive.
- В группе `/chatid` — узнать chat_id (для `RESEARCHER_GROUP_ID`).

## Структура проекта

```
.
├── bot.py              # точка входа: хендлеры, error handler, persistence, /chatid, мост группы
├── handlers.py         # анкета + приём всех типов медиа, подписи ответов
├── states.py           # константы состояний ConversationHandler
├── user_manager.py     # profile.json / feedback.jsonl (id записей), card.md, триггер Drive
├── card_renderer.py    # сборка card.md из JSON, вложенные треды уточнений
├── transcriber.py      # клиент Yandex SpeechKit STT v3
├── media_utils.py      # ffmpeg-обёртка
├── researcher_bridge.py# Forum Topics: темы, форвардинг, уточнения, треды
├── drive_sync.py       # Google Drive (сериализованные заливки, атомарный токен)
├── auth_drive.py       # одноразовый OAuth
├── backfill_drive.py   # CLI-бэкфилл
├── requirements.txt
├── .env.example
└── users/              # данные пользователей (gitignored)
    └── {telegram_id}/
        ├── profile.json    # анкета + topic_id
        ├── feedback.jsonl  # поток сообщений + уточнения (источник данных)
        ├── card.md         # человекочитаемая карточка (генерируется)
        └── voice|audio|video|photo|document/
```

## Формат данных

`feedback.jsonl` — поток записей, у каждой уникальный `id` (по одному JSON на строку):
```json
{"id":"fb_...","type":"text","text":"Удобный сервис","chat_message_id":42,"timestamp":"..."}
{"id":"fb_...","type":"voice","file":"voice/...ogg","duration_sec":5,"transcript":"сырой","transcript_clean":"Чистый.","chat_message_id":43,"timestamp":"..."}
{"id":"fb_...","type":"clarification_question","parent_id":"fb_...","text":"Что именно удобно?","by":"researcher","timestamp":"..."}
{"id":"fb_...","type":"text","text":"Всё в одном окне","parent_id":"fb_...","role":"clarification_answer","timestamp":"..."}
```
- `transcript` — сырой STT (источник истины), `transcript_clean` — очищенный (опционально).
- `clarification_question` / `clarification_answer` связаны через `parent_id` → в `card.md` рендерятся вложенным тредом.
- `chat_message_id` — id личного сообщения (чтобы бот реплаил уточнение на него).

## Безопасность

- Секреты (`.env`, `credentials.json`, `token.json`) и данные (`users/`, `bot_state.pickle`) — в `.gitignore`.
- Динамический контент в сообщениях экранируется (`html.escape`) — `parse_mode=HTML` безопасен.
- Расширения документов санитизируются; `subprocess.run` только list-аргументы (нет injection).
- OAuth scope ограничен `drive.file` — бот видит только свои файлы.
- Заливки в Drive сериализованы (один token-refresh за раз) — нет гонок и `invalid_grant`.
- Исключения идут в логи; пользователю — общее сообщение.

## Известные ограничения

- **Google OAuth в test-режиме:** `refresh_token` живёт 7 дней → периодически повторять `auth_drive.py` (или verify приложения / перейти на S3). Нельзя смешивать API-заливку с ручным копированием в ту же папку Drive (scope `drive.file` не видит чужие файлы → дубликаты).
- **Удаление темы** ботом требует права админа «Удаление сообщений» (не только «Управление темами»).
- Транскрибация — `ru-RU`. Скачивание ботом — лимит 20 МБ (Bot API).
- Бот работает через polling — нужен постоянно запущенный процесс (план: облачная VM 24/7).

## Статус

Учебный проект, доведённый до рабочего прототипа. Дальнейшее развитие (облако 24/7, Yandex Object Storage, AI-аналитика) — см. `PRODUCTION_SPEC.md`. Без формальной лицензии.
