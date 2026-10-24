"""PWA 静态资产：manifest / service worker / 图标可被 /h5 正常服务。

只挂 StaticFiles（与 app/main.py 同款 mount），不拉起全量路由，
避免测试依赖后端配置。
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient


def _client() -> TestClient:
    app = FastAPI()
    static_dir = Path(__file__).resolve().parents[1] / "app" / "static"
    app.mount("/h5", StaticFiles(directory=static_dir, html=True), name="h5")
    return TestClient(app)


def test_manifest_served_and_valid():
    res = _client().get("/h5/manifest.webmanifest")
    assert res.status_code == 200
    data = res.json()
    assert data["start_url"] == "./"
    assert data["display"] == "standalone"
    icons = {i["sizes"] for i in data["icons"]}
    assert {"192x192", "512x512"} <= icons
    purposes = {i.get("purpose") for i in data["icons"]}
    assert "maskable" in purposes


def test_service_worker_served():
    res = _client().get("/h5/sw.js")
    assert res.status_code == 200
    assert "chinatrip-h5" in res.text
    assert "addEventListener('fetch'" in res.text


def test_index_references_pwa_assets():
    res = _client().get("/h5/")
    assert res.status_code == 200
    assert 'rel="manifest"' in res.text
    assert "serviceWorker" in res.text
    assert "theme-color" in res.text


def test_icons_are_valid_png():
    client = _client()
    for name in ("icon-192.png", "icon-512.png", "maskable-icon-512.png"):
        res = client.get(f"/h5/icons/{name}")
        assert res.status_code == 200
        assert res.content[:8] == b"\x89PNG\r\n\x1a\n"
