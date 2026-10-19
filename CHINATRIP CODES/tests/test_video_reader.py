"""Video link understanding (video_reader): douyin _ROUTER_DATA and
bilibili wbi-signed resolution, glm-4.6v vision payload, 429 backoff,
and caption-append wiring in HttpLinkReader. All offline via MockTransport;
the ffmpeg/ASR audio leg is covered by the live probe (tmp_t), not here.
"""

import asyncio
import json

import httpx

from app.services.video_reader import VideoReader, _MediaRef
from app.services.web_reader import HttpLinkReader


def run(coro):
    return asyncio.run(coro)


_LLM = "llm.test"
_DY_MEDIA = "https://v.douyin.com/play/abc.mp4"
_BILI_MEDIA = "https://upos.bilivideo.com/upgcxcode/x.mp4?e=ig8"

_DY_PAGE = (
    "<html><script>window._ROUTER_DATA = "
    '{"loaderData":{"video_(id)/page":{"videoInfoRes":{"item_list":'
    '[{"video":{"play_addr":{"uri":"v0300","url_list":'
    '["https://v.douyin.com/playwm/abc.mp4"]}}}]}}}}'
    "</script></html>"
)

_VISION_REPLY = json.dumps(
    {
        "choices": [
            {"message": {"role": "assistant", "content": "1) 外滩、东方明珠 2) 夜景"}}
        ],
        "model": "glm-4.6v-flash",
    },
    ensure_ascii=False,
)


def _vision_response(request: httpx.Request) -> httpx.Response:
    assert request.headers["Authorization"] == "Bearer k"
    body = json.loads(request.content)
    assert body["model"] == "glm-4.6v-flash"
    parts = body["messages"][0]["content"]
    kinds = [p["type"] for p in parts]
    assert "video_url" in kinds and "text" in kinds
    video_part = next(p for p in parts if p["type"] == "video_url")
    assert video_part["video_url"]["url"] in (_DY_MEDIA, _BILI_MEDIA)
    return httpx.Response(200, text=_VISION_REPLY)


def _small_media(_request: httpx.Request) -> httpx.Response:
    # the size probe before the video_url path: small file, keep video_url
    return httpx.Response(206, headers={"content-range": "bytes 0-1/1024000"})


def _dy_handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "www.iesdouyin.com":
        return httpx.Response(200, text=_DY_PAGE)
    if request.url.host == "v.douyin.com":
        return _small_media(request)
    if request.url.host == _LLM:
        return _vision_response(request)
    raise AssertionError(f"unexpected host {request.url.host}")


def _reader(transport) -> VideoReader:
    return VideoReader(
        api_key="k",
        base_url=f"https://{_LLM}/v4",
        transport=transport,
    )


def test_no_key_is_inert():
    reader = VideoReader()
    assert run(reader.enrich("https://www.douyin.com/video/123")) == ""


def test_douyin_router_data_flows_into_vision():
    reader = _reader(httpx.MockTransport(_dy_handler))
    out = run(reader.enrich("https://www.douyin.com/video/123456789"))
    assert out.startswith("[视频画面]")
    assert "外滩" in out
    assert "[视频语音]" not in out  # asr=None -> audio leg off


def test_douyin_without_router_data_degrades():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.iesdouyin.com":
            return httpx.Response(200, text="<html>empty</html>")
        raise AssertionError("vision should not be called")

    reader = _reader(httpx.MockTransport(handler))
    assert run(reader.enrich("https://www.douyin.com/video/123456789")) == ""


def test_vision_429_backoff_then_success(monkeypatch):
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.services.video_reader.asyncio.sleep", _no_sleep)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == _LLM:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(
                    429, json={"error": {"code": "1305", "message": "overloaded"}}
                )
            return _vision_response(request)
        if request.url.host == "v.douyin.com":
            return _small_media(request)
        return httpx.Response(200, text=_DY_PAGE)

    reader = _reader(httpx.MockTransport(handler))
    out = run(reader.enrich("https://www.douyin.com/video/123456789"))
    assert calls["n"] == 2
    assert "外滩" in out


def test_vision_429_falls_back_to_spare_model(monkeypatch):
    # 4.6v-flash's pool saturates at peak; glm-4v-flash answers instead
    # (probe 2026-10-19). One 429 on the primary must not burn a backoff.
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == _LLM:
            model = json.loads(request.content)["model"]
            seen.append(model)
            if model == "glm-4.6v-flash":
                return httpx.Response(
                    429, json={"error": {"code": "1305", "message": "overloaded"}}
                )
            assert model == "glm-4v-flash"
            return httpx.Response(200, text=_VISION_REPLY)
        if request.url.host == "v.douyin.com":
            return _small_media(request)
        return httpx.Response(200, text=_DY_PAGE)

    reader = VideoReader(
        api_key="k",
        base_url=f"https://{_LLM}/v4",
        transport=httpx.MockTransport(handler),
        fallback_models=["glm-4v-flash"],
    )
    out = run(reader.enrich("https://www.douyin.com/video/123456789"))
    assert seen == ["glm-4.6v-flash", "glm-4v-flash"]
    assert "外滩" in out


def test_bilibili_wbi_resolution():
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "www.bilibili.com":
            return httpx.Response(200)
        if host == "api.bilibili.com" and "/nav" in str(request.url.path):
            assert "wbi" not in str(request.url.path)
            return httpx.Response(
                200,
                json={
                    "data": {
                        "wbi_img": {
                            "img_url": (
                                "https://i0.hdslb.com/bfs/wbi/"
                                "7cd084941338484aae1ad9425b84077c.png"
                            ),
                            "sub_url": (
                                "https://i0.hdslb.com/bfs/wbi/"
                                "4932caff0ff746eab6f01bf08b70ac45.png"
                            ),
                        }
                    }
                },
            )
        if host == "api.bilibili.com" and str(request.url.path).endswith("/view"):
            assert "w_rid" in str(request.url.query)
            return httpx.Response(200, json={"data": {"cid": 42}})
        if host == "api.bilibili.com" and str(request.url.path).endswith("/playurl"):
            assert "w_rid" in str(request.url.query)
            return httpx.Response(
                200, json={"data": {"durl": [{"url": _BILI_MEDIA, "size": 1}]}}
            )
        if host == "upos.bilivideo.com":
            return _small_media(request)
        if host == _LLM:
            return _vision_response(request)
        raise AssertionError(f"unexpected {request.url}")

    reader = _reader(httpx.MockTransport(handler))
    out = run(reader.enrich("https://www.bilibili.com/video/BV1G5po6zECY"))
    assert "[视频画面]" in out


def test_transcribe_off_without_ffmpeg():
    reader = _reader(httpx.MockTransport(_dy_handler))
    reader._ffmpeg = None
    assert run(reader._transcribe(_MediaRef(_DY_MEDIA, {}))) == ""


def test_web_reader_appends_video_text():
    class StubVideo:
        async def enrich(self, url: str, page_html: str = "") -> str:
            return "[视频画面] 外滩、东方明珠"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text='<html><meta property="og:description" content="上海三日游">'
            "<title>上海</title></html>",
        )

    reader = HttpLinkReader(transport=httpx.MockTransport(handler), video=StubVideo())
    digest = run(reader.read("https://www.douyin.com/video/123456789"))
    assert digest.ok
    assert "上海三日游" in digest.text
    assert "[视频画面] 外滩" in digest.text


# --- xiaohongshu (mobile-UA SSR carries the note; probe 2026-10-19) -----

_XHS_MEDIA = "https://sns-video.xhscdn.com/stream/a/259.mp4?sign=s&t=1"

_XHS_VIDEO_PAGE = (
    "<html><script>"
    r'{"title":"重庆必去五个地方","desc":"#重庆旅游[话题]#",'
    r'"masterUrl":"http://sns-video.xhscdn.com/stream/a/'
    '259.mp4?sign=s&t=1"}'
    "</script></html>"
)

_XHS_IMAGE_PAGE = (
    "<html><script>"
    r'{"title":"重庆攻略","desc":"洪崖洞 乌江廊桥",'
    r'"imageList":[{"urlDefault":"http://sns-webpic.xhscdn.com/a.jpg"},'
    r'{"urlDefault":"http://sns-avatar.xhscdn.com/me.jpg"},'
    r'{"urlDefault":"http://sns-webpic.xhscdn.com/b.jpg"}]}'
    "</script></html>"
)


def _xhs_vision_response(request: httpx.Request) -> httpx.Response:
    assert request.headers["Authorization"] == "Bearer k"
    return httpx.Response(200, text=_VISION_REPLY)


def _xhs_handler(page: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.xiaohongshu.com":
            assert "iPhone" in request.headers["User-Agent"]
            return httpx.Response(200, text=page)
        if request.url.host == _LLM:
            return _xhs_vision_response(request)
        raise AssertionError(f"unexpected host {request.url.host}")

    return httpx.MockTransport(handler)


def test_xhs_video_note_flows_into_vision():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == _LLM:
            parts = json.loads(request.content)["messages"][0]["content"]
            seen["kinds"] = [p["type"] for p in parts]
            seen["url"] = parts[0]["video_url"]["url"]
            return httpx.Response(200, text=_VISION_REPLY)
        if request.url.host == "sns-video.xhscdn.com":
            return _small_media(request)
        return httpx.Response(200, text=_XHS_VIDEO_PAGE)

    reader = _reader(httpx.MockTransport(handler))
    out = run(
        reader.enrich("https://www.xiaohongshu.com/discovery/item/abc?xsec_token=tok")
    )
    assert seen["kinds"] == ["video_url", "text"]
    assert seen["url"] == _XHS_MEDIA  # http got upgraded to https
    assert out.startswith("[笔记文字] 重庆必去五个地方")
    assert "[视频画面]" in out and "外滩" in out
    assert "[视频语音]" not in out  # asr=None


def test_xhs_image_note_uses_image_parts():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == _LLM:
            parts = json.loads(request.content)["messages"][0]["content"]
            seen["kinds"] = [p["type"] for p in parts]
            seen["urls"] = [
                p["image_url"]["url"] for p in parts if p["type"] == "image_url"
            ]
            return httpx.Response(200, text=_VISION_REPLY)
        return httpx.Response(200, text=_XHS_IMAGE_PAGE)

    reader = _reader(httpx.MockTransport(handler))
    out = run(reader.enrich("https://www.xiaohongshu.com/explore/xyz"))
    # avatars filtered out; both https upgrades applied
    assert seen["urls"] == [
        "https://sns-webpic.xhscdn.com/a.jpg",
        "https://sns-webpic.xhscdn.com/b.jpg",
    ]
    assert "video_url" not in seen["kinds"]
    assert out.startswith("[笔记文字] 重庆攻略 洪崖洞 乌江廊桥")
    assert "[笔记图片]" in out


def test_xhs_shell_without_note_data_degrades():
    reader = _reader(httpx.MockTransport(_xhs_handler("<html>empty</html>")))
    assert run(reader.enrich("https://www.xiaohongshu.com/explore/none")) == ""


def test_big_video_switches_to_frame_images(monkeypatch):
    # a 28.8MB mp4 draws 400 code 1210 through video_url (probe 2026-10-19):
    # the size gate must reroute it to locally sampled frames, sent as raw
    # base64 image parts (no data-uri prefix).
    seen: dict = {}

    async def fake_sample(_self, _media):
        return ["QUJD"]

    monkeypatch.setattr(VideoReader, "_sample_frames", fake_sample)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "sns-video.xhscdn.com":
            cr = "bytes 0-1/28883835"
            return httpx.Response(206, headers={"content-range": cr})
        if request.url.host == _LLM:
            parts = json.loads(request.content)["messages"][0]["content"]
            seen["kinds"] = [p["type"] for p in parts]
            seen["url"] = parts[0]["image_url"]["url"]
            return httpx.Response(200, text=_VISION_REPLY)
        return httpx.Response(200, text=_XHS_VIDEO_PAGE)

    reader = _reader(httpx.MockTransport(handler))
    out = run(reader.enrich("https://www.xiaohongshu.com/explore/big"))
    assert seen["kinds"] == ["image_url", "text"]
    assert seen["url"] == "QUJD"  # raw base64, no data:image prefix
    assert "[视频画面]" in out


# --- instagram (crawler-UA pages carry og tags + post JSON) -------------

_IG_VIDEO_PAGE = (
    "<html><head>"
    '<meta property="og:image" '
    'content="https://s.cdninstagram.com/v/a.jpg?stp=1&amp;w=640">'
    '<meta property="og:description" '
    'content="695 likes - brock11johnson: &quot;BIG NEWS in Tokyo&quot;">'
    "</head><body>"
    r'"video_versions":[{"type":101,"url":"https:\/\/s.cdninstagram.com\/v\/t2\/x.mp4?efg=1"}'
    "</body></html>"
)

_IG_IMAGE_PAGE = (
    "<html><head>"
    '<meta property="og:image" content="https://s.cdninstagram.com/v/b.jpg">'
    '<meta property="og:description" content="Kyoto day trip guide &amp; spots">'
    "</head></html>"
)


def test_ig_video_post_flows_into_vision():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == _LLM:
            parts = json.loads(request.content)["messages"][0]["content"]
            seen["kinds"] = [p["type"] for p in parts]
            seen["url"] = parts[0]["video_url"]["url"]
            return httpx.Response(200, text=_VISION_REPLY)
        if request.url.host == "s.cdninstagram.com":
            return _small_media(request)
        assert request.url.host == "www.instagram.com"
        assert "facebookexternalhit" in request.headers["User-Agent"]
        return httpx.Response(200, text=_IG_VIDEO_PAGE)

    reader = _reader(httpx.MockTransport(handler))
    out = run(reader.enrich("https://www.instagram.com/p/DWmNnlKIK4l/"))
    assert seen["kinds"] == ["video_url", "text"]
    assert seen["url"] == "https://s.cdninstagram.com/v/t2/x.mp4?efg=1"
    assert out.startswith('[笔记文字] 695 likes - brock11johnson: "BIG NEWS')
    assert "[视频画面]" in out


def test_ig_image_post_uses_og_image_and_caption():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == _LLM:
            parts = json.loads(request.content)["messages"][0]["content"]
            seen["urls"] = [
                p["image_url"]["url"] for p in parts if p["type"] == "image_url"
            ]
            return httpx.Response(200, text=_VISION_REPLY)
        return httpx.Response(200, text=_IG_IMAGE_PAGE)

    reader = _reader(httpx.MockTransport(handler))
    out = run(reader.enrich("https://www.instagram.com/p/DcCGNEuG2Aa/"))
    assert seen["urls"] == ["https://s.cdninstagram.com/v/b.jpg"]
    assert out.startswith("[笔记文字] Kyoto day trip guide & spots")
    assert "[笔记图片]" in out


# --- tiktok (playAddr is header-gated: frames sampled locally) ----------

_TT_MEDIA = "https://v16-webapp-prime.tiktok.com/video/tos/useast2a/x.mp4"
_TT_COVER = "https://p16-sign-va.tiktokcdn.com/obj/tos-cover/x.jpeg"
_TT_PAGE = (
    '<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
    '{"__DEFAULT_SCOPE__":{"webapp.video-detail":{"itemInfo":{"itemStruct":'
    '{"desc":"Tokyo tower view #tokyo","video":{"playAddr":"' + _TT_MEDIA + '",'
    '"cover":"' + _TT_COVER + '"}}}}}}'
    "</script></html>"
)


def test_tiktok_marks_frames_and_keeps_download_headers():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.tiktok.com"
        return httpx.Response(
            200,
            text=_TT_PAGE,
            headers={"set-cookie": "tt_webid=42; Path=/; Domain=.tiktok.com"},
        )

    reader = _reader(httpx.MockTransport(handler))
    media = run(reader._resolve("https://www.tiktok.com/@u/video/123", ""))
    assert media is not None
    assert media.url == _TT_MEDIA
    assert media.headers["Referer"] == "https://www.tiktok.com/"
    assert "tt_webid=42" in media.headers["Cookie"]  # CDN needs session cookies
    assert media.text == "Tokyo tower view #tokyo"
    assert media.images == [_TT_COVER]
    assert media.frames is True


def test_tiktok_cover_fallback_without_ffmpeg():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == _LLM:
            parts = json.loads(request.content)["messages"][0]["content"]
            seen["kinds"] = [p["type"] for p in parts]
            seen["urls"] = [
                p["image_url"]["url"] for p in parts if p["type"] == "image_url"
            ]
            return httpx.Response(200, text=_VISION_REPLY)
        return httpx.Response(200, text=_TT_PAGE)

    reader = _reader(httpx.MockTransport(handler))
    reader._ffmpeg = None  # frame sampling unavailable
    out = run(reader.enrich("https://www.tiktok.com/@u/video/123"))
    assert seen["kinds"] == ["image_url", "text"]
    assert seen["urls"] == [_TT_COVER]  # never the Referer-gated playAddr
    assert out.startswith("[笔记文字] Tokyo tower view #tokyo")
    assert "[视频画面]" in out  # video post: label follows media.url


def test_tiktok_shell_without_universal_data_degrades():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>login wall</html>")

    reader = _reader(httpx.MockTransport(handler))
    assert run(reader.enrich("https://www.tiktok.com/@u/video/123")) == ""


def test_web_reader_gates_xiaohongshu_into_video_reader():
    class StubVideo:
        async def enrich(self, url: str, page_html: str = "") -> str:
            return "[笔记文字] 重庆必去五个地方"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text='<html><meta property="og:description" content="重庆旅游攻略">'
            "<title>重庆</title></html>",
        )

    reader = HttpLinkReader(transport=httpx.MockTransport(handler), video=StubVideo())
    digest = run(
        reader.read("https://www.xiaohongshu.com/discovery/item/abc?xsec_token=t")
    )
    assert digest.ok
    assert "[笔记文字] 重庆必去五个地方" in digest.text
