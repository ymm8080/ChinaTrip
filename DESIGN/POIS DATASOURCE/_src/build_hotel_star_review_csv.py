# -*- coding: utf-8 -*-
"""构建「旅游星级饭店」官方名单审阅包（track ①，pois §3.2 第 12 条）。

数据源（官方可溯源）：文旅部政务服务平台「我要查询 > 五星级旅游饭店」
    https://zwfw.mct.gov.cn/wycx/wxjlyfd/
页面 JS 实测（2026-11-03）：列表 = POST /portal/hotel，请求体 data =
SM4-ECB(PKCS7) + base64( +→@, \\r→#, \\n→! ) 的明文
{"pageSize":..,"pageNum":..,"hotelName":"","province":""}；响应 res.data
同法加密，解密后 JSON {list:[{uuid,hotelName,province}], pagination:{...}}。
smKey 每次会话从 POST /portal/getsm4key 取（res.data[0].smKey，16 字节），
顺带返回的 Set-Cookie（zwfwToken）一并回传（站点会话态，非必需但稳妥）。
pageSize 服务端上限 100（传 200 也只回 100）。

SM4 实现为自包含纯 Python，**刻意复刻站点 sm4.js 的位运算怪癖**：
它的 ROTL(x,n) = SHL(x,n) | x >> (32-n) 用的是 JS 有符号右移（符号扩展），
与 GB/T 32907 的无符号循环左移不同。用标准实现产出的密文服务端不认，
一律 500「系统内部异常」。自检用站点真实向量：
    encrypt_ecb("1234", "1234567890123456") == "ry8R7YUhZ6ZJiUuwmfWnYQ=="
    encrypt_ecb(首页明文, smKey)              == 页面抓包的密文（逐字节）

用法：
    python build_hotel_star_review_csv.py --probe          # 只抓第 1 页打印
    python build_hotel_star_review_csv.py                 # 抓到 _src 原始快照
    python build_hotel_star_review_csv.py --csv out.csv   # 另出审阅 CSV

产物：
    _src/hotel_star_mct_raw_<YYYYMMDD>.json   原始响应归档（含 uuid/省/名称）
    ../14_旅游星级饭店_五星官方名录.csv        审阅包（name_zh,province,grade,...）
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

_BASE = "https://zwfw.mct.gov.cn/portal"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# ---------------- SM4 (GB/T 32907), ECB + PKCS7 ----------------

_SBOX = bytes.fromhex(
    "d690e9fecce13db716b614c228fb2c05"
    "2b679a762abe04c3aa44132649860699"
    "9c4250f491ef987a33540b43edcfac62"
    "e4b31ca9c908e89580df94fa758f3fa6"
    "4707a7fcf37317ba83593c19e6854fa8"
    "686b81b27164da8bf8eb0f4b70569d35"
    "1e240e5e6358d1a225227c3b01217887"
    "d40046579fd327524c3602e7a0c4c89e"
    "eabf8ad240c738b5a3f7f2cef96115a1"
    "e0ae5da49b341a55ad933230f58cb1e3"
    "1df6e22e8266ca60c02923ab0d534e6f"
    "d5db3745defd8e2f03ff6a726d6c5b51"
    "8d1baf92bbddbc7f11d95c411f105ad8"
    "0ac13188a5cd7bbd2d74d012b8e5b4b0"
    "8969974a0c96777e65b9f109c56ec684"
    "18f07dec3adc4d2079ee5f3ed7cb3948"
)
_FK = (0xA3B1BAC6, 0x56AA3350, 0x677D9197, 0xB27022DC)
_CK = tuple(
    int.from_bytes(bytes.fromhex(h), "big")
    for h in (
        "00070e15", "1c232a31", "383f464d", "545b6269",
        "70777e85", "8c939aa1", "a8afb6bd", "c4cbd2d9",
        "e0e7eef5", "fc030a11", "181f262d", "343b4249",
        "50575e65", "6c737a81", "888f969d", "a4abb2b9",
        "c0c7ced5", "dce3eaf1", "f8ff060d", "141b2229",
        "30373e45", "4c535a61", "686f767d", "848b9299",
        "a0a7aeb5", "bcc3cad1", "d8dfe6ed", "f4fb0209",
        "10171e25", "2c333a41", "484f565d", "646b7279",
    )
)


_MASK = 0xFFFFFFFF


def _s32(x: int) -> int:
    """JS 位运算的 32 位有符号截断（>>> 0 的逆向）。"""
    x &= _MASK
    return x - 0x100000000 if x >= 0x80000000 else x


def _rotl(x: int, n: int) -> int:
    """站点 sm4.js 的 ROTL：SHL(x,n) | x >> (32-n)，右移是**有符号**右移。

    这是与 GB/T 32907 的唯一致命差异：符号扩展会把高位置 1，
    标准（无符号）实现产出的密文服务端直接 500。
    """
    n &= 31
    return _s32(_s32(x << n) | (_s32(x) >> (32 - n)))


def _tau(a: int) -> int:
    """S 盒置换，返回无符号 32 位（等价 sm4.js GET_ULONG_BE 的位拼装）。"""
    return (
        _SBOX[(a >> 24) & 0xFF] << 24
        | _SBOX[(a >> 16) & 0xFF] << 16
        | _SBOX[(a >> 8) & 0xFF] << 8
        | _SBOX[a & 0xFF]
    )


def _t_round(x: int) -> int:
    b = _s32(_tau(x & _MASK))
    return _s32(b ^ _rotl(b, 2) ^ _rotl(b, 10) ^ _rotl(b, 18) ^ _rotl(b, 24))


def _t_key(x: int) -> int:
    b = _s32(_tau(x & _MASK))
    return _s32(b ^ _rotl(b, 13) ^ _rotl(b, 23))


def _round_keys(key: bytes) -> list[int]:
    mk = [int.from_bytes(key[i * 4 : i * 4 + 4], "big") for i in range(4)]
    k = [0] * 36
    for i in range(4):
        k[i] = _s32(mk[i] ^ _FK[i])
    rk = []
    for i in range(32):
        k[i + 4] = _s32(
            k[i] ^ _t_key(_s32(k[i + 1] ^ k[i + 2] ^ k[i + 3] ^ _CK[i]))
        )
        rk.append(k[i + 4])
    return rk


def _crypt_block(block: bytes, rk: list[int]) -> bytes:
    x = [_s32(int.from_bytes(block[i * 4 : i * 4 + 4], "big")) for i in range(4)]
    x += [0] * 32
    for i in range(32):
        x[i + 4] = _s32(
            x[i] ^ _t_round(_s32(x[i + 1] ^ x[i + 2] ^ x[i + 3] ^ rk[i]))
        )
    return b"".join(
        (v & _MASK).to_bytes(4, "big") for v in (x[35], x[34], x[33], x[32])
    )


def sm4_encrypt_ecb(plaintext: bytes, key: bytes) -> bytes:
    pad = 16 - len(plaintext) % 16
    data = plaintext + bytes([pad]) * pad
    rk = _round_keys(key)
    return b"".join(_crypt_block(data[i : i + 16], rk) for i in range(0, len(data), 16))


def sm4_decrypt_ecb(ciphertext: bytes, key: bytes) -> bytes:
    rk = _round_keys(key)[::-1]
    data = b"".join(
        _crypt_block(ciphertext[i : i + 16], rk) for i in range(0, len(ciphertext), 16)
    )
    pad = data[-1]
    if not 1 <= pad <= 16 or data[-pad:] != bytes([pad]) * pad:
        raise ValueError("bad PKCS7 padding")
    return data[:-pad]


def _js_b64(s: str) -> str:
    """sm4.js 的 base64 变体：+ → @（另 \\r → #、\\n → !，base64 不会出现）。"""
    return s.replace("+", "@")


def _py_b64(s: str) -> str:
    return s.replace("@", "+").replace("#", "\r").replace("!", "\n")


def encrypt_field(plain: str, key_hex: bytes) -> str:
    import base64

    ct = sm4_encrypt_ecb(plain.encode("utf-8"), key_hex)
    return _js_b64(base64.b64encode(ct).decode("ascii"))


def decrypt_field(cipher: str, key_hex: bytes) -> str:
    import base64

    ct = base64.b64decode(_py_b64(cipher))
    return sm4_decrypt_ecb(ct, key_hex).decode("utf-8")


def _self_test() -> None:
    import base64

    key = b"1234567890123456"
    ct = sm4_encrypt_ecb(b"1234", key)
    got = base64.b64encode(ct).decode()
    # 站点 sm4.js 真实向量（有符号 ROTL 变体；标准实现会得 woPrxebr8Xvyo1qG8QxAUA==）
    assert got == "ry8R7YUhZ6ZJiUuwmfWnYQ==", (b"1234", got)
    assert sm4_decrypt_ecb(ct, key) == b"1234"

    # 页面抓包 payload 逐字节一致（2026-11-03 实测）
    sm_key = b"3fd1cf46fd40949d"
    plain = '{"pageSize":"15","pageNum":"1","hotelName":"","province":""}'
    page_cipher = (
        "4GYLe9rQHBPOIHi@0k1BQH@48iX5YHgccerrA/CH@aqlVZ/4eh@CUHSfg1ckDJtSlzPs5Ci"
        "Ma@w5Vdy3HQjV1w=="
    )
    assert encrypt_field(plain, sm_key) == page_cipher, encrypt_field(plain, sm_key)


# ---------------- HTTP ----------------


def _post(
    path: str, form: dict, referer: str, cookie: str | None = None
) -> tuple[dict, str | None]:
    """POST 表单，返回 (JSON, 首个 Set-Cookie 的 key=value)。"""
    data = urllib.parse.urlencode(form).encode()
    headers = {
        "User-Agent": _UA,
        "Referer": referer,
        "Origin": "https://zwfw.mct.gov.cn",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(
        _BASE + path, data=data, headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        set_cookies = resp.headers.get_all("Set-Cookie") or []
    new_cookie = set_cookies[0].split(";")[0] if set_cookies else None
    return body, new_cookie


def fetch_page(
    key_hex: bytes,
    page_num: int,
    page_size: int,
    referer: str,
    cookie: str | None = None,
) -> dict:
    plain = json.dumps(
        {"pageSize": str(page_size), "pageNum": str(page_num),
         "hotelName": "", "province": ""},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    res, _ = _post("/hotel", {"data": encrypt_field(plain, key_hex)}, referer, cookie)
    if not isinstance(res.get("data"), str):
        raise RuntimeError(f"unexpected response: {res}")
    inner = decrypt_field(res["data"], key_hex)
    return json.loads(inner)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true", help="only page 1, print JSON")
    parser.add_argument(
        "--page-size", type=int, default=100, help="服务端上限 100（传更大也只回 100）"
    )
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument("--csv", default=None, help="also write review CSV")
    args = parser.parse_args(argv)

    _self_test()
    referer = "https://zwfw.mct.gov.cn/wycx/wxjlyfd/"
    key_res, cookie = _post("/getsm4key", {}, referer)
    key_hex = key_res["data"][0]["smKey"].encode("utf-8")
    if len(key_hex) != 16:
        raise RuntimeError(f"bad smKey length: {len(key_hex)}")

    first = fetch_page(key_hex, 1, args.page_size, referer, cookie)
    if args.probe:
        print(json.dumps(first, ensure_ascii=True)[:4000])
        return 0

    pagination = first.get("pagination") or {}
    total = int(pagination.get("total") or 0)
    total_pages = int(pagination.get("totalPage") or 1)
    rows = list(first.get("list") or [])
    pages = min(total_pages, args.max_pages)
    for p in range(2, pages + 1):
        page = fetch_page(key_hex, p, args.page_size, referer, cookie)
        rows.extend(page.get("list") or [])
    print(f"fetched rows={len(rows)} total={total} pages={pages}")

    out_dir = Path(__file__).resolve().parent
    stamp = date.today().strftime("%Y%m%d")
    raw_path = out_dir / f"hotel_star_mct_raw_{stamp}.json"
    raw_path.write_text(
        json.dumps({"total": total, "pages": pages, "list": rows},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"raw snapshot -> {raw_path}")

    csv_path = (
        Path(args.csv) if args.csv
        else out_dir.parent / f"14_旅游星级饭店_五星官方名录.csv"
    )
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["name_zh", "province", "grade", "batch", "alias_zh", "source_url"])
        for r in rows:
            name = (r.get("hotelName") or "").strip()
            prov = (r.get("province") or "").strip()
            if not name:
                continue
            w.writerow([name, prov, "五星级饭店", "全国星级饭店名录（动态）", "",
                        referer])
    print(f"review csv -> {csv_path} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
