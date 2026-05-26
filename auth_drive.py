"""Одноразовый OAuth-вход в Google Drive.

Запуск: python auth_drive.py
Что делает:
  - Читает credentials.json (OAuth Client ID из Google Cloud Console)
  - Открывает браузер для логина в Google
  - Сохраняет token.json — рефреш-токен, который дальше использует бот
После этого можно запускать bot.py — он будет автоматически заливать файлы в Drive.
"""
import os

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
HERE = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(HERE, "credentials.json")
TOKEN_PATH = os.path.join(HERE, "token.json")


def main() -> None:
    if not os.path.exists(CREDENTIALS_PATH):
        raise SystemExit(
            f"Не найден {CREDENTIALS_PATH}\n"
            "Скачайте credentials.json из Google Cloud Console "
            "(OAuth Client ID, Desktop application) и положите рядом с этим скриптом."
        )

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    print(f"\n✅ Token сохранён в {TOKEN_PATH}")
    print("Теперь можно запускать bot.py — файлы будут автоматически заливаться в Google Drive.")


if __name__ == "__main__":
    main()
