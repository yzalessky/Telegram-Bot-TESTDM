import asyncio
import html
import logging
import os
import re
from datetime import datetime
from typing import Optional

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes, ConversationHandler

import media_utils
import researcher_bridge
import transcriber
import user_manager
from states import (
    WAIT_AGE,
    WAIT_CHILDREN_COUNT,
    WAIT_CHILDREN_INFO,
    WAIT_FEEDBACK,
    WAIT_GENDER,
    WAIT_HAS_CHILDREN,
    WAIT_NAME,
)

logger = logging.getLogger(__name__)

_GENDER_KB = ReplyKeyboardMarkup([["Мужской", "Женский"]], one_time_keyboard=True, resize_keyboard=True)
_YES_NO_KB = ReplyKeyboardMarkup([["Да", "Нет"]], one_time_keyboard=True, resize_keyboard=True)
_EXT_PATTERN = re.compile(r"^[a-zA-Z0-9]{1,10}$")
_BOT_PREFIX = "<b>Бот-помощник:</b>"
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # лимит публичного Bot API на скачивание файла
_MEDIA_HUMAN = {
    "video": "видео", "video_note": "кружок", "audio": "аудиофайл",
    "document": "документ", "voice": "голосовое", "photo": "фото",
}


async def _bot_reply(message, text: str, **kwargs):
    """Ответ бота в диалоге ПОСЛЕ регистрации — с подписью-идентификатором."""
    kwargs.setdefault("parse_mode", "HTML")
    return await message.reply_text(f"{_BOT_PREFIX}\n\n{html.escape(text, quote=False)}", **kwargs)


def _ts() -> str:
    """Метка времени с миллисекундами — чтобы избежать коллизий при быстрых сообщениях."""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


def _safe_ext(filename: Optional[str], default: str) -> str:
    """Безопасное расширение из имени файла: только буквенно-цифровое, до 10 символов."""
    if not filename or "." not in filename:
        return default
    raw = filename.rsplit(".", 1)[-1]
    if _EXT_PATTERN.match(raw):
        return f".{raw.lower()}"
    return default


def _is_allowed(user_id: int) -> bool:
    """Проверка whitelist по telegram_id. Пустой ALLOWED_TELEGRAM_IDS = доступ открыт."""
    raw = os.environ.get("ALLOWED_TELEGRAM_IDS", "").strip()
    if not raw:
        return True
    ids = {int(p.strip()) for p in raw.split(",") if p.strip().isdigit()}
    return user_id in ids


async def _download(tg_obj, save_path: str) -> None:
    file = await tg_obj.get_file()
    await file.download_to_drive(save_path)
    user_manager.upload_user_file(save_path)


async def _transcribe_and_record(update: Update, audio_path: str, entry: dict) -> str:
    """Транскрибирует файл, пишет результат в entry. Возвращает строку для ответа пользователю."""
    if not transcriber.is_configured():
        return "(транскрибация отключена — нет YANDEX_API_KEY / YANDEX_FOLDER_ID в .env)"
    try:
        await update.message.chat.send_action(ChatAction.TYPING)
        transcript = await transcriber.transcribe_file(audio_path)
        entry["transcript"] = transcript
        return f"Распознал: «{transcript}»" if transcript else "(речь не распознана)"
    except Exception as exc:
        logger.exception("Transcription failed for %s", audio_path)
        entry["transcript_error"] = str(exc)
        return "(не удалось распознать речь — детали в логах)"


async def _record_and_forward(update: Update, context: ContextTypes.DEFAULT_TYPE, entry: dict) -> str:
    """Сохраняет запись фидбека. Если ждём ответ на уточнение — помечает её ответом
    (parent_id + role). Затем пересылает в тему исследователей. Возвращает id записи."""
    user_id = update.effective_user.id
    # id сообщения в личном чате — чтобы бот мог reply'ем привязать к нему уточнение
    entry = {**entry, "chat_message_id": update.message.message_id}
    pending = context.bot_data.get("pending_clarification", {})
    qid = pending.pop(user_id, None) if isinstance(pending, dict) else None
    if qid:
        entry = {**entry, "parent_id": qid, "role": "clarification_answer"}
    fid = user_manager.append_feedback_entry(user_id, entry)
    await researcher_bridge.forward_feedback(context, user_id, fid, update.message, entry)
    return fid


def _oversize_message(type_label: str, mb: int) -> str:
    if type_label in ("video", "video_note"):
        return (f"Видео получилось тяжёлым ({mb} МБ) — Telegram не отдаёт боту файлы больше 20 МБ.\n\n"
                "В лимит обычно влезает 30–60 секунд видео (для высокого качества — ~15–30 сек). "
                "Снимите покороче, пришлите в меньшем качестве или обрежьте фрагмент.")
    if type_label == "audio":
        return (f"Аудио тяжелее 20 МБ ({mb} МБ) — Telegram не отдаёт такие боту.\n\n"
                "В лимит влезает примерно 15–20 минут при обычном качестве. Пришлите фрагмент покороче.")
    if type_label == "document":
        return (f"Файл тяжелее 20 МБ ({mb} МБ) — Telegram не отдаёт боту файлы такого размера.\n\n"
                "Пришлите файл до 20 МБ.")
    return (f"Файл тяжёлый ({mb} МБ) — Telegram не отдаёт боту файлы больше 20 МБ.\n\n"
            "Пришлите вариант полегче.")


async def _reject_if_too_big(update: Update, context: ContextTypes.DEFAULT_TYPE, media_obj, type_label: str) -> bool:
    """Файл > 20 МБ: вежливый отказ + заглушка в данные + пометка исследователю.
    Возвращает True, если обработку надо прекратить (файл нельзя скачать)."""
    size = getattr(media_obj, "file_size", None)
    if not size or size <= MAX_DOWNLOAD_BYTES:
        return False
    mb = round(size / 1024 / 1024)
    await _bot_reply(update.message, _oversize_message(type_label, mb))
    fid = user_manager.append_feedback_entry(
        update.effective_user.id,
        {"type": "oversized", "media_type": type_label, "size_bytes": size},
    )
    await researcher_bridge.forward_note(
        context, update.effective_user.id, fid,
        f"⚠️ Респондент пытался прислать {_MEDIA_HUMAN.get(type_label, 'файл')} "
        f"(~{mb} МБ) — не захвачено: превышен лимит Telegram 20 МБ.",
    )
    return True


# --- регистрация ----------------------------------------------------------

async def start_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id

    if not _is_allowed(user_id):
        logger.warning("Blocked access from telegram_id=%s", user_id)
        await update.message.reply_text("Извините, доступ к этому боту ограничен.")
        return ConversationHandler.END

    if user_manager.user_exists(user_id):
        await researcher_bridge.ensure_topic(context, user_id)
        await _bot_reply(
            update.message,
            "Вы уже зарегистрированы!\n\n"
            "Поделитесь своими ощущениями от использования микросервиса — "
            "можно текстом, голосовым, фото, видео или файлом."
        )
        return WAIT_FEEDBACK

    user_manager.create_user_folder(user_id)
    context.user_data.clear()
    await update.message.reply_text(
        "Добрый день! Давайте познакомимся.\n\nВведите ваши ФИО (Фамилия Имя Отчество):"
    )
    return WAIT_NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Сколько вам лет?")
    return WAIT_AGE


async def get_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 120):
        await update.message.reply_text("Пожалуйста, введите возраст числом (например: 34):")
        return WAIT_AGE

    context.user_data["age"] = int(text)
    await update.message.reply_text("Укажите ваш пол:", reply_markup=_GENDER_KB)
    return WAIT_GENDER


async def get_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text not in ("Мужской", "Женский"):
        await update.message.reply_text("Пожалуйста, выберите вариант:", reply_markup=_GENDER_KB)
        return WAIT_GENDER

    context.user_data["gender"] = text
    await update.message.reply_text("У вас есть дети?", reply_markup=_YES_NO_KB)
    return WAIT_HAS_CHILDREN


async def get_has_children(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text not in ("Да", "Нет"):
        await update.message.reply_text("Пожалуйста, выберите вариант:", reply_markup=_YES_NO_KB)
        return WAIT_HAS_CHILDREN

    if text == "Нет":
        context.user_data["has_children"] = False
        context.user_data["children"] = []
        return await _finish_registration(update, context)

    context.user_data["has_children"] = True
    await update.message.reply_text("Сколько у вас детей?", reply_markup=ReplyKeyboardRemove())
    return WAIT_CHILDREN_COUNT


async def get_children_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("Пожалуйста, введите число детей (например: 2):")
        return WAIT_CHILDREN_COUNT

    count = int(text)
    context.user_data["children_total"] = count
    context.user_data["children_collected"] = []
    await update.message.reply_text(
        f"Расскажите о ребёнке 1 из {count}.\n"
        "Введите возраст и пол в формате: <b>5 лет, мальчик</b>",
        parse_mode="HTML",
    )
    return WAIT_CHILDREN_INFO


async def get_children_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    children: list = context.user_data["children_collected"]
    total: int = context.user_data["children_total"]

    children.append({"index": len(children) + 1, "info": update.message.text.strip()})

    if len(children) < total:
        next_idx = len(children) + 1
        await update.message.reply_text(
            f"Расскажите о ребёнке {next_idx} из {total}.\n"
            "Введите возраст и пол в формате: <b>5 лет, мальчик</b>",
            parse_mode="HTML",
        )
        return WAIT_CHILDREN_INFO

    context.user_data["children"] = children
    return await _finish_registration(update, context)


async def _finish_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    profile = {
        "telegram_id": user.id,
        "username": f"@{user.username}" if user.username else None,
        "name": context.user_data["name"],
        "age": context.user_data["age"],
        "gender": context.user_data["gender"],
        "has_children": context.user_data["has_children"],
        "children": context.user_data.get("children", []),
        "registered_at": datetime.now().isoformat(timespec="seconds"),
    }
    user_manager.save_profile(user.id, profile)
    await researcher_bridge.ensure_topic(context, user.id)

    await _bot_reply(
        update.message,
        "✅ Анкета сохранена, спасибо!\n\n"
        "Теперь поделитесь ощущениями от использования микросервиса.\n"
        "Можно текстом, голосовым, фото, видео или файлом.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return WAIT_FEEDBACK


# --- фидбек: текст --------------------------------------------------------

async def receive_text_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _record_and_forward(update, context, {"type": "text", "text": update.message.text.strip()})
    await _bot_reply(update.message, "Записал! Присылайте ещё.")
    return WAIT_FEEDBACK


# --- фидбек: голосовое ----------------------------------------------------

async def receive_voice_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    voice = update.message.voice
    user_id = update.effective_user.id

    if await _reject_if_too_big(update, context, voice, "voice"):
        return WAIT_FEEDBACK

    filename = f"voice_{_ts()}.ogg"
    save_path = os.path.join(user_manager.media_dir(user_id, "voice"), filename)
    await _download(voice, save_path)

    entry = {
        "type": "voice",
        "file": f"voice/{filename}",
        "duration_sec": voice.duration,
    }
    line = await _transcribe_and_record(update, save_path, entry)
    await _record_and_forward(update, context, entry)

    await _bot_reply(
        update.message,
        f"Голосовое получено ({voice.duration} сек).\n\n{line}\n\nПрисылайте ещё."
    )
    return WAIT_FEEDBACK


# --- фидбек: универсальная обработка audio/video/video_note ---------------

async def _process_av(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    media_obj,
    *,
    subfolder: str,
    base_name: str,
    source_ext: str,
    type_label: str,
    reply_prefix: str,
    original_name: Optional[str] = None,
) -> int:
    """Универсальный пайплайн: скачать → ffmpeg → транскрибировать → записать → ответить."""
    user_id = update.effective_user.id

    if await _reject_if_too_big(update, context, media_obj, type_label):
        return WAIT_FEEDBACK

    source_filename = f"{base_name}{source_ext}"
    source_path = os.path.join(user_manager.media_dir(user_id, subfolder), source_filename)
    await _download(media_obj, source_path)

    entry: dict = {
        "type": type_label,
        "file": f"{subfolder}/{source_filename}",
        "duration_sec": media_obj.duration,
    }
    if original_name:
        entry["original_name"] = original_name
    if update.message.caption:
        entry["caption"] = update.message.caption

    if transcriber.is_configured():
        ogg_filename = f"{base_name}.ogg"
        ogg_path = os.path.join(user_manager.media_dir(user_id, subfolder), ogg_filename)
        try:
            await asyncio.to_thread(media_utils.extract_audio_to_oggopus, source_path, ogg_path)
            user_manager.upload_user_file(ogg_path)
            entry["audio_extracted"] = f"{subfolder}/{ogg_filename}"
            line = await _transcribe_and_record(update, ogg_path, entry)
        except Exception as exc:
            logger.exception("Audio extraction failed for %s", source_path)
            entry["transcript_error"] = str(exc)
            line = "(не удалось обработать аудиодорожку — детали в логах)"
    else:
        line = "(транскрибация отключена — нет YANDEX_API_KEY / YANDEX_FOLDER_ID в .env)"

    await _record_and_forward(update, context, entry)
    await _bot_reply(
        update.message,
        f"{reply_prefix} ({media_obj.duration} сек).\n\n{line}\n\nПрисылайте ещё."
    )
    return WAIT_FEEDBACK


async def receive_audio_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    audio = update.message.audio
    return await _process_av(
        update, context, audio,
        subfolder="audio",
        base_name=f"audio_{_ts()}",
        source_ext=_safe_ext(audio.file_name, ".mp3"),
        type_label="audio",
        reply_prefix="Аудиофайл получен",
        original_name=audio.file_name,
    )


async def receive_video_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    video = update.message.video
    return await _process_av(
        update, context, video,
        subfolder="video",
        base_name=f"video_{_ts()}",
        source_ext=".mp4",
        type_label="video",
        reply_prefix="Видео получено",
    )


async def receive_video_note_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    vn = update.message.video_note
    return await _process_av(
        update, context, vn,
        subfolder="video",
        base_name=f"video_note_{_ts()}",
        source_ext=".mp4",
        type_label="video_note",
        reply_prefix="Кругляш получен",
    )


# --- фидбек: фото ---------------------------------------------------------

async def receive_photo_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    photo = update.message.photo[-1]  # самое большое разрешение
    user_id = update.effective_user.id

    if await _reject_if_too_big(update, context, photo, "photo"):
        return WAIT_FEEDBACK

    filename = f"photo_{_ts()}.jpg"
    save_path = os.path.join(user_manager.media_dir(user_id, "photo"), filename)
    await _download(photo, save_path)

    entry = {"type": "photo", "file": f"photo/{filename}"}
    if update.message.caption:
        entry["caption"] = update.message.caption
    await _record_and_forward(update, context, entry)

    await _bot_reply(update.message, "Фото получено.\n\nПрисылайте ещё.")
    return WAIT_FEEDBACK


# --- фидбек: документ -----------------------------------------------------

async def receive_document_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    doc = update.message.document
    user_id = update.effective_user.id

    if await _reject_if_too_big(update, context, doc, "document"):
        return WAIT_FEEDBACK

    ext = _safe_ext(doc.file_name, default=".bin")
    filename = f"doc_{_ts()}{ext}"
    save_path = os.path.join(user_manager.media_dir(user_id, "document"), filename)
    await _download(doc, save_path)

    entry = {
        "type": "document",
        "file": f"document/{filename}",
        "original_name": doc.file_name,
    }
    await _record_and_forward(update, context, entry)

    display_name = (doc.file_name or "файл")[:100]
    await _bot_reply(update.message, f"Файл «{display_name}» получен.\n\nПрисылайте ещё.")
    return WAIT_FEEDBACK


# --- завершение -----------------------------------------------------------

async def stop_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Диалог намеренно НЕ завершается: бот остаётся на связи, чтобы в любой момент
    # принять новый отзыв или ответ на уточняющий вопрос исследователя.
    await _bot_reply(
        update.message,
        "Спасибо! Я остаюсь на связи — присылайте новые мысли в любой момент, "
        "и отвечайте, если что-то уточню."
    )
    return WAIT_FEEDBACK


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Диалог отменён. Напишите ТЕСТДМ, чтобы начать заново.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END
