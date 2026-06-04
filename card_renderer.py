"""Генерация человекочитаемой карточки респондента (card.md) из JSON-данных.

card.md полностью перегенерируется из profile.json + feedback.jsonl при каждом обновлении.
Ссылки на медиа — относительные (работают при открытии card.md в папке пользователя).
"""
from typing import Optional

_TYPE_LABELS = {
    "text": "Текст",
    "voice": "Голосовое",
    "audio": "Аудиофайл",
    "video": "Видео",
    "video_note": "Кругляш",
    "photo": "Фото",
    "document": "Документ",
}


def _fmt_ts(ts: str) -> str:
    """ISO timestamp -> читаемый вид: '2026-05-26T15:05:00' -> '2026-05-26 15:05'."""
    if not ts:
        return ""
    return ts.replace("T", " ")[:16]


def _esc_cell(value) -> str:
    """Экранирует значение для ячейки Markdown-таблицы."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _oneline(value: str) -> str:
    """Убирает переносы строк (для блок-цитат и подписей)."""
    return " ".join(str(value).split())


def _render_profile(profile: Optional[dict]) -> list[str]:
    lines = ["## Анкета", ""]
    if not profile:
        lines += ["_Анкета ещё не заполнена._", ""]
        return lines

    tg_id = profile.get("telegram_id", "")
    username = profile.get("username")
    tg_cell = f"{username} (ID: {tg_id})" if username else f"ID: {tg_id}"

    lines += [
        "| Поле | Значение |",
        "|------|----------|",
        f"| ФИО | {_esc_cell(profile.get('name', '—'))} |",
        f"| Возраст | {_esc_cell(profile.get('age', '—'))} |",
        f"| Пол | {_esc_cell(profile.get('gender', '—'))} |",
        f"| Telegram | {_esc_cell(tg_cell)} |",
        f"| Зарегистрирован | {_fmt_ts(profile.get('registered_at', ''))} |",
        "",
    ]

    if profile.get("has_children"):
        children = profile.get("children", [])
        lines.append(f"**Дети:** да ({len(children)})")
        lines.append("")
        for ch in children:
            lines.append(f"- Ребёнок {ch.get('index', '?')}: {ch.get('info', '')}")
        lines.append("")
    else:
        lines += ["**Дети:** нет", ""]

    return lines


def _render_entry(n: int, entry: dict) -> list[str]:
    # Тип: если поля нет, но есть text — считаем текстом
    etype = entry.get("type") or ("text" if entry.get("text") else "unknown")
    label = _TYPE_LABELS.get(etype, "Сообщение")
    ts = _fmt_ts(entry.get("timestamp", ""))
    file = entry.get("file")

    dur = entry.get("duration_sec")
    dur_str = f" ({dur} сек)" if dur is not None else ""

    lines = [f"### {n}. {label}{dur_str} — {ts}", ""]

    if etype == "text":
        lines += [entry.get("text", ""), ""]
    elif etype == "photo":
        if file:
            lines += [f"![фото]({file})", ""]
        if entry.get("caption"):
            lines += [f"**Подпись:** {_oneline(entry['caption'])}", ""]
    elif etype == "document":
        name = entry.get("original_name") or (file.rsplit("/", 1)[-1] if file else "файл")
        if file:
            lines += [f"[{name}]({file})", ""]
    else:
        # voice / audio / video / video_note / unknown
        if file:
            lines += [f"[{file.rsplit('/', 1)[-1]}]({file})", ""]
        if entry.get("caption"):
            lines += [f"**Подпись:** {_oneline(entry['caption'])}", ""]
        clean = entry.get("transcript_clean")
        raw = entry.get("transcript")
        if clean:
            lines += [f"> **Расшифровка:** {_oneline(clean)}", ""]
            if raw and _oneline(raw) != _oneline(clean):
                lines += [f"> _STT-оригинал: {_oneline(raw)}_", ""]
        elif raw:
            lines += [f"> **Расшифровка:** {_oneline(raw)}", ""]
        elif entry.get("transcript_error"):
            lines += ["> _Расшифровка не удалась._", ""]

    return lines


def render_card(profile: Optional[dict], feedback: list) -> str:
    lines = ["# Карточка респондента", ""]
    lines += _render_profile(profile)
    lines += [f"## Фидбек ({len(feedback)})", ""]
    if not feedback:
        lines += ["_Пока нет сообщений._", ""]
    else:
        for i, entry in enumerate(feedback, 1):
            lines += _render_entry(i, entry)
    return "\n".join(lines).rstrip() + "\n"
