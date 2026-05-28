import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    PicklePersistence,
    filters,
)

from handlers import (
    cancel,
    get_age,
    get_children_count,
    get_children_info,
    get_gender,
    get_has_children,
    get_name,
    receive_audio_feedback,
    receive_document_feedback,
    receive_photo_feedback,
    receive_text_feedback,
    receive_video_feedback,
    receive_video_note_feedback,
    receive_voice_feedback,
    start_registration,
    stop_feedback,
)
from states import (
    WAIT_AGE,
    WAIT_CHILDREN_COUNT,
    WAIT_CHILDREN_INFO,
    WAIT_FEEDBACK,
    WAIT_GENDER,
    WAIT_HAS_CHILDREN,
    WAIT_NAME,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
# Чтобы Google API клиент не засорял лог INFO-сообщениями
logging.getLogger("googleapiclient").setLevel(logging.WARNING)
logging.getLogger("google_auth_httplib2").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Файл с состояниями диалогов — рядом с bot.py, не зависит от папки запуска
PERSISTENCE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_state.pickle")


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальный обработчик исключений — логирует и (если возможно) сообщает пользователю."""
    logger.exception("Unhandled exception", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Произошла внутренняя ошибка. Попробуйте ещё раз — детали записаны в логи."
            )
        except Exception:
            pass


def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не задан. Создайте файл .env с BOT_TOKEN=ваш_токен")

    persistence = PicklePersistence(filepath=PERSISTENCE_PATH)
    app = Application.builder().token(token).persistence(persistence).build()

    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"(?i)тестдм"), start_registration)
        ],
        states={
            WAIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            WAIT_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_age)],
            WAIT_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_gender)],
            WAIT_HAS_CHILDREN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_has_children)],
            WAIT_CHILDREN_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_children_count)],
            WAIT_CHILDREN_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_children_info)],
            WAIT_FEEDBACK: [
                CommandHandler("stop", stop_feedback),
                MessageHandler(filters.VOICE, receive_voice_feedback),
                MessageHandler(filters.AUDIO, receive_audio_feedback),
                MessageHandler(filters.VIDEO, receive_video_feedback),
                MessageHandler(filters.VIDEO_NOTE, receive_video_note_feedback),
                MessageHandler(filters.PHOTO, receive_photo_feedback),
                MessageHandler(filters.Document.ALL, receive_document_feedback),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text_feedback),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="main_conversation",
        persistent=True,
    )

    app.add_handler(conv)
    app.add_error_handler(_error_handler)

    print("Бот запущен. Нажмите Ctrl+C для остановки.")
    app.run_polling()


if __name__ == "__main__":
    main()
