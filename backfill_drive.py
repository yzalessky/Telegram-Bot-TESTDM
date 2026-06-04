"""Заливает все существующие файлы из users/ в Google Drive.

Использование: python backfill_drive.py

Файлы, уже существующие в Drive, обновляются (не дублируются).
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

import drive_sync
import user_manager


def main() -> None:
    if not drive_sync.is_configured():
        raise SystemExit(
            "Drive не настроен.\n"
            "Проверьте что в .env задан GOOGLE_DRIVE_FOLDER_ID "
            "и в папке проекта лежит token.json (запустите auth_drive.py)."
        )

    users_dir = user_manager.USERS_DIR
    if not os.path.isdir(users_dir):
        raise SystemExit(f"Папка {users_dir} не существует")

    files: list[tuple[str, str]] = []
    for root, _dirs, names in os.walk(users_dir):
        for name in names:
            local = os.path.join(root, name)
            rel = os.path.relpath(local, users_dir).replace(os.sep, "/")
            files.append((local, rel))

    if not files:
        print("В users/ ничего нет — заливать нечего.")
        return

    total = len(files)
    print(f"Найдено файлов: {total}\n")

    ok = 0
    fail = 0
    for i, (local, rel) in enumerate(files, 1):
        try:
            drive_sync.upload_file_sync(local, rel)
            print(f"  [{i}/{total}] OK   {rel}")
            ok += 1
        except Exception as exc:
            print(f"  [{i}/{total}] FAIL {rel}: {exc}")
            fail += 1

    print(f"\nГотово. Успешно: {ok}, ошибок: {fail}")


if __name__ == "__main__":
    main()
