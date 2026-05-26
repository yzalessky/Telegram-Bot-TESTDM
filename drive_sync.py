"""Синхронизация файлов с Google Drive через OAuth.

Fire-and-forget: при ошибке заливки бот продолжает работать, ошибка пишется в логи.
"""
import asyncio
import logging
import os
import threading

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
_HERE = os.path.dirname(__file__)
TOKEN_PATH = os.path.join(_HERE, "token.json")
CREDENTIALS_PATH = os.path.join(_HERE, "credentials.json")

_service = None
_folder_cache: dict[str, str] = {}
_cache_lock = threading.Lock()  # защита от гонок при создании папок параллельными аплоадами


def is_configured() -> bool:
    return bool(os.environ.get("GOOGLE_DRIVE_FOLDER_ID")) and os.path.exists(TOKEN_PATH)


def _escape_query(value: str) -> str:
    """Экранирование для Drive search query (single-quoted)."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _get_service():
    global _service
    if _service is not None:
        return _service
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    _service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _service


def _find_or_create_folder(service, parent_id: str, name: str) -> str:
    cache_key = f"{parent_id}/{name}"
    # Lock на всю операцию find/create, чтобы параллельные аплоады не создали дубль папки
    with _cache_lock:
        if cache_key in _folder_cache:
            return _folder_cache[cache_key]

        query = (
            f"name='{_escape_query(name)}' and '{parent_id}' in parents "
            "and mimeType='application/vnd.google-apps.folder' and trashed=false"
        )
        result = service.files().list(q=query, fields="files(id)", pageSize=1).execute()
        files = result.get("files", [])
        if files:
            folder_id = files[0]["id"]
        else:
            meta = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }
            folder = service.files().create(body=meta, fields="id").execute()
            folder_id = folder["id"]

        _folder_cache[cache_key] = folder_id
        return folder_id


def _upload_blocking(local_path: str, drive_subpath: str) -> None:
    """Заливает/обновляет файл в Drive по пути {ROOT_FOLDER}/{drive_subpath}."""
    service = _get_service()
    root_id = os.environ["GOOGLE_DRIVE_FOLDER_ID"]

    parts = drive_subpath.replace("\\", "/").split("/")
    *folders, filename = parts

    parent_id = root_id
    for folder_name in folders:
        parent_id = _find_or_create_folder(service, parent_id, folder_name)

    query = f"name='{_escape_query(filename)}' and '{parent_id}' in parents and trashed=false"
    result = service.files().list(q=query, fields="files(id)", pageSize=1).execute()
    existing = result.get("files", [])

    media = MediaFileUpload(local_path, resumable=False)
    if existing:
        service.files().update(fileId=existing[0]["id"], media_body=media).execute()
    else:
        meta = {"name": filename, "parents": [parent_id]}
        service.files().create(body=meta, media_body=media, fields="id").execute()


async def _upload_async(local_path: str, drive_subpath: str) -> None:
    try:
        await asyncio.to_thread(_upload_blocking, local_path, drive_subpath)
        logger.info("Drive uploaded: %s", drive_subpath)
    except HttpError as exc:
        logger.error("Drive HTTP error for %s: %s", drive_subpath, exc)
    except Exception:
        logger.exception("Drive upload failed: %s -> %s", local_path, drive_subpath)


def schedule_upload(local_path: str, drive_subpath: str) -> None:
    """Запускает заливку в фоне. Не блокирует, не падает."""
    if not is_configured():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("No event loop running, skipping upload of %s", drive_subpath)
        return
    loop.create_task(_upload_async(local_path, drive_subpath))


def upload_file_sync(local_path: str, drive_subpath: str) -> None:
    """Блокирующая заливка — для CLI-скриптов вне event loop."""
    if not is_configured():
        raise RuntimeError("Drive не настроен (нет GOOGLE_DRIVE_FOLDER_ID или token.json)")
    _upload_blocking(local_path, drive_subpath)
