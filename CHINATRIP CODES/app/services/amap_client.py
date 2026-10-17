import httpx


class AmapError(Exception):
    """Amap API error. Message must never contain the api key."""

    def __init__(self, message: str, infocode: str = "") -> None:
        super().__init__(message)
        self.infocode = infocode


class AmapTimeoutError(AmapError):
    pass


def _as_str(value: object) -> str | None:
    # Amap returns [] instead of "" for some empty string fields.
    return value if isinstance(value, str) else None


def _parse_location(value: str | None) -> dict | None:
    if not value:
        return None
    parts = value.split(",")
    if len(parts) != 2:
        return None
    try:
        return {"lon": float(parts[0]), "lat": float(parts[1])}
    except ValueError:
        return None


def _normalize_poi(poi: dict) -> dict:
    city = _as_str(poi.get("cityname")) or _as_str(poi.get("pname"))
    return {
        "source": "amap",
        "source_poi_id": _as_str(poi.get("id")),
        "name": _as_str(poi.get("name")),
        "city": city,
        "category": _as_str(poi.get("type")),
        "address": _as_str(poi.get("address")),
        "location": _parse_location(_as_str(poi.get("location"))),
    }


class AmapClient:
    def __init__(
        self,
        *,
        key: str,
        base_url: str = "https://restapi.amap.com/v3",
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._key = key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def search_poi(
        self, keywords: str, *, city: str | None = None, page: int = 1
    ) -> list[dict]:
        params: dict[str, str | int] = {
            "key": self._key,
            "keywords": keywords,
            "offset": 10,
            "page": page,
            "output": "JSON",
            "extensions": "base",
        }
        if city:
            params["city"] = city
            params["citylimit"] = "true"
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as http:
            try:
                response = await http.get("/place/text", params=params)
            except httpx.TimeoutException as exc:
                raise AmapTimeoutError("amap request timed out") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise AmapError("amap returned non-JSON body") from exc
        if not isinstance(data, dict):
            raise AmapError("amap returned unexpected JSON shape")
        if data.get("status") != "1":
            raise AmapError(
                _as_str(data.get("info")) or "amap request failed",
                _as_str(data.get("infocode")) or "",
            )
        pois = data.get("pois")
        if not isinstance(pois, list):
            return []
        return [_normalize_poi(p) for p in pois if isinstance(p, dict)]
