"""智谱 GLM-ASR 语音转文字客户端（open.bigmodel.cn /audio/transcriptions）。

H5 语音输入专用：浏览器端采集 PCM 合成 WAV → 本服务转发智谱（国内可达，
替代 Chrome Web Speech API 的谷歌后端——大陆网络下 onerror=network 必挂）。
约束：wav/mp3、≤25MB、≤30s（API 层校验大小，时长由前端 25s 自动停止兜底）。
"""

import httpx

__all__ = ["AsrClient", "AsrError", "AsrTimeoutError"]


class AsrError(Exception):
    """智谱 ASR 上游错误。message 不得包含 api key。"""

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code


class AsrTimeoutError(AsrError):
    pass


class AsrClient:
    def __init__(
        self,
        key: str,
        base_url: str = "https://open.bigmodel.cn/api/paas/v4",
        model: str = "glm-asr-2512",
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._key = key
        self._model = model
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=timeout_seconds, transport=transport
        )

    async def transcribe(self, audio: bytes, filename: str = "speech.wav") -> str:
        """返回识别文本（无语音内容时为空串，不视为错误）。"""
        try:
            resp = await self._client.post(
                "/audio/transcriptions",
                headers={"Authorization": f"Bearer {self._key}"},
                files={"file": (filename, audio, "audio/wav")},
                data={"model": self._model},
            )
        except httpx.TimeoutException as exc:
            raise AsrTimeoutError("asr upstream timeout") from exc
        except httpx.HTTPError as exc:
            raise AsrError(f"asr upstream error: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise AsrError(
                f"asr upstream status {resp.status_code}", code=str(resp.status_code)
            )
        text = resp.json().get("text")
        return text if isinstance(text, str) else ""
