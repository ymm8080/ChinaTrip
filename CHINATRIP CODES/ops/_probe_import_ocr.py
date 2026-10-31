"""行程导入 OCR 真链路探针（2026-10-31，用户要求验证 OCR）。

合成「扫描件」：PIL 把中文行程单文字渲染成图片 → 包成 PDF（无文字层，
模拟扫描版）→ 走真实 GLM 视觉 OCR（TripImportService.extract → pypdf 空
文本 → pypdfium2 渲染 → glm-4.6v-flash）→ LLM 结构化 → build_plan。
同时验证图片直读路径（.jpg）。运行：.venv/Scripts/python ops/_probe_import_ocr.py
"""

from __future__ import annotations

import asyncio
import io
import json
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.config import get_settings
from app.services.llm.zhipu import ZhipuGLMAdapter
from app.services.trip_import import TripImportService, build_plan

LINES = [
    "杭州二日行程单",
    "第一天 杭州",
    "09:00-11:30 西湖（断桥、苏堤）",
    "12:00 午餐：楼外楼（孤山路30号）",
    "14:00-16:30 灵隐寺·飞来峰",
    "第二天 杭州 → 苏州",
    "08:15 高铁 G7352 杭州东 → 苏州北",
    "10:30-12:00 拙政园",
    "14:00-17:00 平江路历史街区",
]

FONT = r"C:\Windows\Fonts\msyh.ttc"


def make_image() -> bytes:
    font = ImageFont.truetype(FONT, 30)
    img = Image.new("RGB", (860, 80 + 46 * len(LINES)), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(LINES):
        draw.text((40, 40 + 46 * i), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def make_scanned_pdf(img_jpeg: bytes) -> bytes:
    """单页图片型 PDF（无文字层）——PIL 直接把 JPEG 包成 PDF。"""
    img = Image.open(io.BytesIO(img_jpeg))
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


async def main() -> None:
    settings = get_settings()
    adapter = ZhipuGLMAdapter(
        api_key=settings.glm_api_key,
        base_url=settings.glm_base_url,
        model=settings.glm_model,
        timeout_seconds=settings.glm_timeout_seconds,
        vision_model=settings.glm_model_vision,
        vision_fallback_models=[
            m for m in settings.glm_vision_fallback_models.split(",") if m.strip()
        ],
    )
    svc = TripImportService(adapter)

    jpeg = make_image()
    pdf = make_scanned_pdf(jpeg)
    print(f"合成件：jpeg {len(jpeg)}B / scanned-pdf {len(pdf)}B\n")

    for name, data in (("行程扫描件.pdf", pdf), ("行程截图.jpg", jpeg)):
        t0 = time.time()
        text = await svc.extract(name, data, max_text_chars=30000)
        t1 = time.time()
        print(f"=== {name} OCR {t1 - t0:.1f}s，抽出 {len(text)} 字 ===")
        print(text[:400])
        draft, quarantined = await svc.structure(text)
        t2 = time.time()
        plan, warnings = build_plan(draft, "it_probe")
        print(f"--- 结构化+转换 {t2 - t1:.1f}s，quarantined={quarantined} ---")
        print(
            json.dumps(
                {
                    "cities": plan.cities,
                    "start_date": plan.start_date,
                    "days": [
                        {
                            "day": d.day,
                            "base_city": d.base_city,
                            "items": [
                                getattr(it, "name", None)
                                or f"{getattr(it, 'from_city', '')}→{getattr(it, 'to_city', '')}"
                                for it in d.items
                            ],
                        }
                        for d in plan.days
                    ],
                    "warnings": warnings,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        print()


if __name__ == "__main__":
    asyncio.run(main())
