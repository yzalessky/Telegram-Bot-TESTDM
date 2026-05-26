"""ffmpeg-обёртки (через imageio_ffmpeg — бинарь зашит в пакет)."""
import subprocess

import imageio_ffmpeg


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
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        tail = (result.stderr or "")[-500:]
        raise RuntimeError(f"ffmpeg failed (rc={result.returncode}): {tail}")
