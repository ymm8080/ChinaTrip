"""Fetch URL to local file via urllib (stdlib).

Why not curl in .cmd jobs: schtasks/cmd context uses Windows schannel +
system proxy where curl.exe can hang until timeout on CN network; the
venv python urllib path is proven on this machine (planet OSM fetches).
Usage: python fetch_url.py <url> <dest> [timeout_seconds]
"""

from __future__ import annotations

import sys
import urllib.request

_UA = "ChinaTrip-POI-library/0.1 (contact: dev@chinatrip.local)"


def main() -> int:
    url, dest = sys.argv[1], sys.argv[2]
    timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 300
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as fh:
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
    return 0


if __name__ == "__main__":
    sys.exit(main())
