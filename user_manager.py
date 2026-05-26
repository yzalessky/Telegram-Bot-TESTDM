import json
import os
from datetime import datetime

import drive_sync

USERS_DIR = os.path.join(os.path.dirname(__file__), "users")


def _user_dir(user_id: int) -> str:
    return os.path.join(USERS_DIR, str(user_id))


def _drive_relpath(local_path: str) -> str:
    """Превращает локальный путь в путь относительно users/ (для Drive)."""
    return os.path.relpath(local_path, USERS_DIR).replace(os.sep, "/")


def create_user_folder(user_id: int) -> None:
    os.makedirs(_user_dir(user_id), exist_ok=True)


def user_exists(user_id: int) -> bool:
    return os.path.exists(os.path.join(_user_dir(user_id), "profile.json"))


def save_profile(user_id: int, data: dict) -> None:
    create_user_folder(user_id)
    path = os.path.join(_user_dir(user_id), "profile.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    drive_sync.schedule_upload(path, _drive_relpath(path))


def media_dir(user_id: int, subfolder: str) -> str:
    create_user_folder(user_id)
    path = os.path.join(_user_dir(user_id), subfolder)
    os.makedirs(path, exist_ok=True)
    return path


def append_feedback_entry(user_id: int, entry: dict) -> None:
    create_user_folder(user_id)
    path = os.path.join(_user_dir(user_id), "feedback.jsonl")
    entry = {**entry, "timestamp": datetime.now().isoformat(timespec="seconds")}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    drive_sync.schedule_upload(path, _drive_relpath(path))


def save_text_feedback(user_id: int, text: str) -> None:
    append_feedback_entry(user_id, {"type": "text", "text": text})


def upload_user_file(local_path: str) -> None:
    """Залить произвольный файл из users/ в Drive (для медиафайлов после скачивания)."""
    drive_sync.schedule_upload(local_path, _drive_relpath(local_path))
