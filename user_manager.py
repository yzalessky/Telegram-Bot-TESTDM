import json
import os
import uuid
from datetime import datetime

import card_renderer
import drive_sync

USERS_DIR = os.path.join(os.path.dirname(__file__), "users")


def _user_dir(user_id: int) -> str:
    return os.path.join(USERS_DIR, str(user_id))


def _drive_relpath(local_path: str) -> str:
    """Превращает локальный путь в путь относительно users/ (для Drive)."""
    return os.path.relpath(local_path, USERS_DIR).replace(os.sep, "/")


def _read_profile(user_id: int) -> dict | None:
    path = os.path.join(_user_dir(user_id), "profile.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_profile(user_id: int) -> dict | None:
    """Публичный доступ к профилю (для researcher_bridge и др.)."""
    return _read_profile(user_id)


def find_feedback(user_id: int, feedback_id: str) -> dict | None:
    """Возвращает запись фидбека по id (или None)."""
    for entry in _read_feedback(user_id):
        if entry.get("id") == feedback_id:
            return entry
    return None


def new_feedback_id() -> str:
    """Уникальный id записи фидбека: fb_<timestamp_мс>_<rand>."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    return f"fb_{ts}_{uuid.uuid4().hex[:4]}"


def _read_feedback(user_id: int) -> list:
    path = os.path.join(_user_dir(user_id), "feedback.jsonl")
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def regenerate_card(user_id: int) -> None:
    """Полностью пересобирает card.md из profile.json + feedback.jsonl и заливает в Drive."""
    md = card_renderer.render_card(_read_profile(user_id), _read_feedback(user_id))
    path = os.path.join(_user_dir(user_id), "card.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    drive_sync.schedule_upload(path, _drive_relpath(path))


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
    regenerate_card(user_id)


def media_dir(user_id: int, subfolder: str) -> str:
    create_user_folder(user_id)
    path = os.path.join(_user_dir(user_id), subfolder)
    os.makedirs(path, exist_ok=True)
    return path


def append_feedback_entry(user_id: int, entry: dict) -> str:
    """Дописывает запись в feedback.jsonl. Гарантирует поле id, возвращает его."""
    create_user_folder(user_id)
    path = os.path.join(_user_dir(user_id), "feedback.jsonl")
    fid = entry.get("id") or new_feedback_id()
    entry = {"id": fid, **entry, "timestamp": datetime.now().isoformat(timespec="seconds")}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    drive_sync.schedule_upload(path, _drive_relpath(path))
    regenerate_card(user_id)
    return fid


def save_text_feedback(user_id: int, text: str) -> str:
    return append_feedback_entry(user_id, {"type": "text", "text": text})


def upload_user_file(local_path: str) -> None:
    """Залить произвольный файл из users/ в Drive (для медиафайлов после скачивания)."""
    drive_sync.schedule_upload(local_path, _drive_relpath(local_path))
