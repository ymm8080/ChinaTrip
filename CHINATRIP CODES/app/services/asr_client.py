"""智谱 GLM-ASR 语音转文字客户端（open.bigmodel.cn /audio/transcriptions）。

H5 语音输入专用：浏览器端采集 PCM 合成 WAV → 本服务转发智谱（国内可达，
替代 Chrome Web Speech API 的谷歌后端——大陆网络下 onerror=network 必挂）。
约束：wav/mp3、≤25MB、≤30s（API 层校验大小，时长由前端 25s 自动停止兜底）。
"""

import asyncio
import base64
import time

import httpx

__all__ = ["AsrClient", "AsrError", "AsrTimeoutError", "BaiduVoiceTranslateClient"]


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
        self.configured = bool(key)
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

    async def transcribe_full(self, audio: bytes, filename: str = "speech.wav") -> dict:
        return {
            "text": await self.transcribe(audio, filename=filename),
            "translated": None,
        }


def _as_text(value):
    if isinstance(value, list):
        value = "".join(str(x) for x in value)
    return value if isinstance(value, str) else ""


def _to_pcm16k(data: bytes) -> bytes:
    """任意输入 → 16k 单声道 16bit 原始 PCM（百度语音翻译推荐格式）。

    ffmpeg 缺失时：WAV 原样透传（format=wav），其余原样透传。
    """
    if data[:4] != b"RIFF":
        return data
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return data
    import os
    import subprocess
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "in.wav")
            dst = os.path.join(td, "out.pcm")
            with open(src, "wb") as f:
                f.write(data)
            subprocess.run(
                [
                    exe,
                    "-y",
                    "-i",
                    src,
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-f",
                    "s16le",
                    "-acodec",
                    "pcm_s16le",
                    dst,
                ],
                check=True,
                timeout=30,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with open(dst, "rb") as f:
                out = f.read()
    except Exception:
        return data
    return out if out else data


class BaiduVoiceTranslateClient:
    """百度智能云 语音翻译API（rpc/2.0/mt/v2/speech-translation）：音频 → 原文 + 译文。

    translation_pipeline_design_2026-10-30 P0。免费额度：每月 1000 次。
    官方规范（MT.pdf 语音翻译章节）：
    - 鉴权：URL 参数 access_token（API Key + Secret Key 经 oauth/2.0/token 换取，
      进程内缓存，过期前 60s 主动刷新）
    - POST JSON：{from, to, voice(音频base64，编码后≤4MB), format(pcm|wav)}
      Content-Type: application/json；音频 ≤60s、16k/16bit/单声道
    - 正常返回：{log_id, result:{source(原文), target(译文), target_tts(译文mp3 b64)}}
    - 异常返回：{error_code, error_msg}（BCE 风格）
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        endpoint: str = "https://aip.baidubce.com/rpc/2.0/mt/v2/speech-translation",
        oauth_url: str = "https://aip.baidubce.com/oauth/2.0/token",
        from_lang: str = "zh",
        to_lang: str = "en",
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._endpoint = endpoint
        self._oauth_url = oauth_url
        self._from = from_lang or "zh"
        self._to = to_lang or "en"
        self.configured = bool(api_key) and bool(secret_key)
        self._client = httpx.AsyncClient(timeout=timeout_seconds, transport=transport)
        self._token: str | None = None
        self._token_expire = 0.0

    async def _get_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expire - 60:
            return self._token
        resp = await self._client.post(
            self._oauth_url,
            params={
                "grant_type": "client_credentials",
                "client_id": self._api_key,
                "client_secret": self._secret_key,
            },
        )
        if resp.status_code != 200:
            raise AsrError(
                f"baidu oauth status {resp.status_code}", code=str(resp.status_code)
            )
        body = resp.json()
        token = body.get("access_token")
        if not token:
            desc = body.get("error_description") or body.get("error") or body
            raise AsrError(f"baidu oauth failed: {desc}")
        self._token = token
        self._token_expire = now + float(body.get("expires_in", 2592000))
        return token

    async def transcribe(self, audio: bytes, filename: str = "speech.wav") -> str:
        return (await self.transcribe_full(audio, filename=filename))["text"]

    async def transcribe_full(self, audio: bytes, filename: str = "speech.wav") -> dict:
        token = await self._get_token()
        pcm = await asyncio.to_thread(_to_pcm16k, audio)
        voice = base64.b64encode(pcm).decode("ascii")
        fmt = "wav" if pcm[:4] == b"RIFF" else "pcm"
        try:
            resp = await self._client.post(
                self._endpoint,
                params={"access_token": token},
                json={
                    "from": self._from,
                    "to": self._to,
                    "voice": voice,
                    "format": fmt,
                },
            )
        except httpx.TimeoutException as exc:
            raise AsrTimeoutError("baidu speech-translation timeout") from exc
        except httpx.HTTPError as exc:
            raise AsrError(
                f"baidu speech-translation error: {type(exc).__name__}"
            ) from exc
        if resp.status_code != 200:
            raise AsrError(
                f"baidu speech-translation status {resp.status_code}",
                code=str(resp.status_code),
            )
        body = resp.json()
        err = body.get("error_code") or body.get("err_no")
        if err:
            raise AsrError(
                "baidu speech-translation error {}: {}".format(
                    err, body.get("error_msg") or body.get("errmsg") or ""
                ),
                code=str(err),
            )
        result = body.get("result") if isinstance(body.get("result"), dict) else body
        return {
            "text": _as_text(result.get("source")),
            "translated": _as_text(result.get("target")),
        }
