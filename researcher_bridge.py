"""Мост «респондент ↔ исследователи» через Telegram Forum Topics.

Бот пересылает сообщения респондента в персональную тему группового чата исследователей.
Исследователь явным жестом (reply на сообщение респондента / reply на закреплённую сводку /
команда /ask) задаёт уточняющий вопрос — бот доставляет его респонденту, ответ возвращается
в тему и привязывается к исходному фидбеку (parent_id).

Фича опциональна: без RESEARCHER_GROUP_ID всё тихо пропускается, бот работает как обычно.

bot_data (persisted через PicklePersistence):
  topics:               {message_thread_id: user_id}        — тема → респондент
  topic_pinned:         {message_thread_id: pinned_msg_id}  — закреплённая сводка профиля
  msgmap:               {group_message_id: {user_id, feedback_id}} — сообщение в теме → фидбек
  pending_clarification:{user_id: question_id}              — следующий ответ юзера = ответ на вопрос
"""
import logging
import os

from telegram import ReplyParameters, Update
from telegram.ext import ContextTypes

import user_manager

logger = logging.getLogger(__name__)


def _group_id():
    raw = os.environ.get("RESEARCHER_GROUP_ID", "").strip()
    if raw and raw.lstrip("-").isdigit():
        return int(raw)
    return None


def is_enabled() -> bool:
    return _group_id() is not None


def group_id():
    """Публичный доступ к chat_id группы исследователей (или None)."""
    return _group_id()


def _topic_name(profile: dict, user_id: int) -> str:
    parts = [profile.get("name") or "Респондент"]
    if profile.get("username"):
        parts.append(profile["username"])
    parts.append(f"#{user_id}")
    return " · ".join(parts)[:128]


def _profile_summary(profile: dict, user_id: int) -> str:
    lines = [
        f"👤 {profile.get('name', '—')}",
        f"Возраст: {profile.get('age', '—')}  ·  Пол: {profile.get('gender', '—')}",
        f"Username: {profile.get('username') or '—'}",
        f"ID: {user_id}",
    ]
    if profile.get("has_children"):
        children = profile.get("children", [])
        lines.append(f"Дети: да ({len(children)})")
        for ch in children:
            lines.append(f"  • {ch.get('info', '')}")
    else:
        lines.append("Дети: нет")
    lines.append("")
    lines.append("↩️ Reply на сообщение — вопрос привяжется к нему. "
                 "Reply на эту сводку или /ask <текст> — общий вопрос.")
    return "\n".join(lines)


async def ensure_topic(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Создаёт тему для респондента, если её ещё нет. Возвращает message_thread_id или None."""
    if not is_enabled():
        return None
    gid = _group_id()
    bot = context.bot
    topics = context.bot_data.setdefault("topics", {})
    pinned = context.bot_data.setdefault("topic_pinned", {})

    profile = user_manager.get_profile(user_id)
    if profile is None:
        return None

    existing = profile.get("topic_id")
    if existing:
        topics.setdefault(int(existing), user_id)
        return int(existing)

    try:
        topic = await bot.create_forum_topic(chat_id=gid, name=_topic_name(profile, user_id))
        thread_id = topic.message_thread_id
        summary = await bot.send_message(
            chat_id=gid, message_thread_id=thread_id, text=_profile_summary(profile, user_id)
        )
        try:
            await bot.pin_chat_message(chat_id=gid, message_id=summary.message_id, disable_notification=True)
        except Exception:
            logger.warning("pin profile summary failed for %s", user_id)

        topics[thread_id] = user_id
        pinned[thread_id] = summary.message_id
        profile["topic_id"] = thread_id
        user_manager.save_profile(user_id, profile)
        logger.info("Created topic %s for user %s", thread_id, user_id)
        return thread_id
    except Exception:
        logger.exception("ensure_topic failed for user %s", user_id)
        return None


async def forward_feedback(context: ContextTypes.DEFAULT_TYPE, user_id: int, feedback_id: str, message, entry: dict):
    """Пересылает сообщение респондента в его тему и запоминает связь сообщений с фидбеком."""
    if not is_enabled():
        return
    thread_id = await ensure_topic(context, user_id)
    if not thread_id:
        return
    gid = _group_id()
    bot = context.bot
    msgmap = context.bot_data.setdefault("msgmap", {})
    sent_ids = []

    async def _post(coro):
        s = await coro
        sent_ids.append(s.message_id)

    try:
        etype = entry.get("type")
        caption = message.caption or None
        if etype == "text":
            await _post(bot.send_message(gid, entry.get("text", ""), message_thread_id=thread_id))
        elif message.voice:
            await _post(bot.send_voice(gid, message.voice.file_id, message_thread_id=thread_id))
        elif message.audio:
            await _post(bot.send_audio(gid, message.audio.file_id, caption=caption, message_thread_id=thread_id))
        elif message.video:
            await _post(bot.send_video(gid, message.video.file_id, caption=caption, message_thread_id=thread_id))
        elif message.video_note:
            await _post(bot.send_video_note(gid, message.video_note.file_id, message_thread_id=thread_id))
        elif message.photo:
            await _post(bot.send_photo(gid, message.photo[-1].file_id, caption=caption, message_thread_id=thread_id))
        elif message.document:
            await _post(bot.send_document(gid, message.document.file_id, caption=caption, message_thread_id=thread_id))

        # отдельной строкой — расшифровка (чтобы исследователь читал текст голоса/видео)
        transcript = entry.get("transcript_clean") or entry.get("transcript")
        if transcript and etype != "text":
            await _post(bot.send_message(gid, f"📝 {transcript}", message_thread_id=thread_id))
    except Exception:
        logger.exception("forward_feedback failed for user %s", user_id)

    for mid in sent_ids:
        msgmap[mid] = {"user_id": user_id, "feedback_id": feedback_id}


async def _ask(context: ContextTypes.DEFAULT_TYPE, user_id: int, text: str, parent_id):
    """Логирует уточняющий вопрос, доставляет респонденту, ставит pending."""
    text = (text or "").strip()
    if not text:
        return
    qid = user_manager.append_feedback_entry(user_id, {
        "type": "clarification_question",
        "parent_id": parent_id,
        "text": text,
        "by": "researcher",
    })
    context.bot_data.setdefault("pending_clarification", {})[user_id] = qid

    # Если вопрос привязан к конкретному фидбеку — доставляем reply'ем на исходное
    # сообщение респондента в личке (чтобы он понял, о чём речь).
    reply_params = None
    if parent_id:
        fb = user_manager.find_feedback(user_id, parent_id)
        chat_msg_id = fb.get("chat_message_id") if fb else None
        if chat_msg_id:
            reply_params = ReplyParameters(message_id=chat_msg_id, allow_sending_without_reply=True)

    delivered = True
    try:
        await context.bot.send_message(
            user_id, f"💬 Вопрос от исследователя:\n\n{text}", reply_parameters=reply_params
        )
    except Exception:
        delivered = False
        logger.exception("deliver clarification to user %s failed", user_id)

    profile = user_manager.get_profile(user_id) or {}
    thread_id = profile.get("topic_id")
    if thread_id:
        note = "✅ Вопрос отправлен респонденту." if delivered else "⚠️ Не удалось доставить вопрос респонденту."
        try:
            await context.bot.send_message(_group_id(), note, message_thread_id=int(thread_id))
        except Exception:
            pass


async def handle_researcher_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сообщение исследователя в теме. Вопрос уходит респонденту только при явном reply-жесте."""
    if not is_enabled():
        return
    msg = update.message
    if msg is None or msg.from_user is None or msg.from_user.is_bot:
        return
    thread_id = msg.message_thread_id
    if thread_id is None:
        return
    user_id = context.bot_data.get("topics", {}).get(thread_id)
    if user_id is None:
        return

    reply = msg.reply_to_message
    if reply is None:
        return  # обычное сообщение = внутренняя дискуссия, не пересылаем

    msgmap = context.bot_data.get("msgmap", {})
    pinned = context.bot_data.get("topic_pinned", {})
    info = msgmap.get(reply.message_id)
    if info and info.get("user_id") == user_id:
        parent_id = info.get("feedback_id")          # привязка к конкретному фидбеку
    elif pinned.get(thread_id) == reply.message_id:
        parent_id = None                              # общий вопрос (reply на сводку)
    else:
        return  # reply на чужое/служебное сообщение → внутреннее, игнор

    await _ask(context, user_id, msg.text, parent_id)


async def handle_ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ask <текст> в теме — общий вопрос респонденту (без привязки к фидбеку)."""
    if not is_enabled():
        return
    msg = update.message
    if msg is None or msg.from_user is None or msg.from_user.is_bot:
        return
    thread_id = msg.message_thread_id
    if thread_id is None:
        return
    user_id = context.bot_data.get("topics", {}).get(thread_id)
    if user_id is None:
        return
    text = msg.text.partition(" ")[2].strip() if msg.text else ""
    if not text:
        await msg.reply_text("Использование: /ask <текст вопроса>")
        return
    await _ask(context, user_id, text, parent_id=None)
