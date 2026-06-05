"""ffmpeg-обёртки (через imageio_ffmpeg — бинарь зашит в пакет)."""
import subprocess

import imageio_ffmpeg

# Таймаут на извлечение аудио. При лимите Telegram 20 МБ этого с большим запасом хватает.
# ⚠️ Если поднимете локальный Bot API сервер (файлы до 2 ГБ) — фиксированного таймаута мало,
# сделайте его адаптивным от длительности/размера (см. PRODUCTION_SPEC §8/§9-B).
FFMPEG_TIMEOUT = 120


def extract_audio_to_oggopus(source_path: str, target_path: str) -> None:
    """Достаёт аудио из любого видео/аудио в OggOpus, моно, 32 кбит/с."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg, "-y",
        "-i", source_path,
        "-vn",                 # без видео-дорожки
        "-c:a", "libopus",
        "-b:a", "32k",
        "-ac", "1",            # моно
        target_path,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=FFMPEG_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"ffmpeg timed out after {FFMPEG_TIMEOUT}s (битый или слишком большой файл?)"
        )
    if result.returncode != 0:
        tail = (result.stderr or "")[-500:]
        raise RuntimeError(f"ffmpeg failed (rc={result.returncode}): {tail}")
