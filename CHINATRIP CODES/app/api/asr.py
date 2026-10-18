"""POST /api/v1/asr — H5 语音输入（multipart wav → 智谱 GLM-ASR → text）。

替代浏览器端 Web Speech API：Chrome 的识别走谷歌服务，大陆网络不可达。
API 层管校验（device id / 扩展名 / 大小）；上游错误映射 502/504（对齐 amap 代理）。
"""

import logging

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile

from app.config import Settings, get_settings
from app.services.asr_client import AsrClient, AsrError, AsrTimeoutError

router = APIRouter(prefix="/api/v1", tags=["asr"])
logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 智谱硬限 25MB（时长 ≤30s 由前端 25s 自动停兜底）
_ALLOWED_EXT = (".wav", ".mp3")

_client_singleton: AsrClient | None = None


def get_asr_client(settings: Settings = Depends(get_settings)) -> AsrClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = AsrClient(
            key=settings.glm_api_key,
            model=settings.asr_model,
            timeout_seconds=settings.glm_timeout_seconds,
        )
    return _client_singleton


@router.post("/asr")
async def asr_endpoint(
    file: UploadFile = File(...),
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    client: AsrClient = Depends(get_asr_client),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    if settings.glm_api_key == "":
        raise HTTPException(status_code=503, detail="asr_not_configured")
    name = (file.filename or "").lower()
    if not name.endswith(_ALLOWED_EXT):
        raise HTTPException(status_code=422, detail="unsupported_audio_format")
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=422, detail="empty_audio")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio_too_large")
    try:
        text = await client.transcribe(audio, filename=name)
    except AsrTimeoutError:
        raise HTTPException(status_code=504, detail="asr_timeout") from None
    except AsrError as exc:
        logger.warning("asr error: %s", exc)
        raise HTTPException(status_code=502, detail="asr_error") from exc
    # 诊断：静音流（OS 级麦克风封锁）与过短录音从日志即可分辨。
    # WARNING 而非 INFO：uvicorn 默认丢弃 app 级 INFO（root 无 handler）。
    is_wav = audio[:4] == b"RIFF" and len(audio) >= 28
    rate = int.from_bytes(audio[24:28], "little") if is_wav else 0
    dur = (len(audio) - 44) / 2 / rate if rate else 0.0
    if not text:
        logger.warning(
            "asr empty result: %d bytes, %d Hz, %.1fs", len(audio), rate, dur
        )
    return {"text": text}
