"""Yandex SpeechKit STT v3 (async REST) с пунктуацией и капитализацией."""
import asyncio
import base64
import json
import os

import httpx

RECOGNIZE_URL = "https://stt.api.cloud.yandex.net/stt/v3/recognizeFileAsync"
OPERATION_URL = "https://operation.api.cloud.yandex.net/operations/{}"
GET_RECOGNITION_URL = "https://stt.api.cloud.yandex.net/stt/v3/getRecognition"


def is_configured() -> bool:
    return bool(os.environ.get("YANDEX_API_KEY") and os.environ.get("YANDEX_FOLDER_ID"))


def _extract_texts(ndjson: str) -> str:
    """Парсит NDJSON-ответ getRecognition.
    Предпочитает finalRefinement (нормализованный с пунктуацией) над final (сырой)."""
    normalized: list[str] = []
    raw: list[str] = []
    for line in ndjson.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        result = msg.get("result", {})
        if "finalRefinement" in result:
            for alt in result["finalRefinement"].get("normalizedText", {}).get("alternatives", []):
                text = alt.get("text", "").strip()
                if text:
                    normalized.append(text)
        elif "final" in result:
            for alt in result["final"].get("alternatives", []):
                text = alt.get("text", "").strip()
                if text:
                    raw.append(text)
    return " ".join(normalized) if normalized else " ".join(raw)


async def transcribe_file(audio_path: str) -> str:
    """Транскрибирует OggOpus-аудио через Yandex STT v3 async, возвращает текст с пунктуацией."""
    api_key = os.environ["YANDEX_API_KEY"]

    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    body = {
        "content": base64.b64encode(audio_bytes).decode("ascii"),
        "recognitionModel": {
            "audioFormat": {
                "containerAudio": {"containerAudioType": "OGG_OPUS"},
            },
            "textNormalization": {
                "textNormalization": "TEXT_NORMALIZATION_ENABLED",
                "profanityFilter": False,
                "literatureText": True,
            },
            "languageRestriction": {
                "restrictionType": "WHITELIST",
                "languageCode": ["ru-RU"],
            },
            "audioProcessingType": "FULL_DATA",
        },
    }
    headers = {"Authorization": f"Api-Key {api_key}"}

    async with httpx.AsyncClient(timeout=120.0) as client:
        # 1. Запускаем асинхронную операцию
        resp = await client.post(RECOGNIZE_URL, headers=headers, json=body)
        resp.raise_for_status()
        op_id = resp.json()["id"]

        # 2. Ждём пока операция завершится
        for _ in range(180):  # до ~3 минут
            await asyncio.sleep(1.0)
            op_resp = await client.get(OPERATION_URL.format(op_id), headers=headers)
            op_resp.raise_for_status()
            op_data = op_resp.json()
            if op_data.get("done"):
                if "error" in op_data:
                    raise RuntimeError(f"Yandex STT error: {op_data['error']}")
                break
        else:
            raise TimeoutError("Транскрибация заняла больше 3 минут")

        # 3. Забираем результаты отдельным запросом (NDJSON-поток)
        result_resp = await client.get(
            GET_RECOGNITION_URL, headers=headers, params={"operationId": op_id}
        )
        result_resp.raise_for_status()
        return _extract_texts(result_resp.text)
