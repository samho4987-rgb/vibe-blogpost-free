from __future__ import annotations

import html
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
from uuid import uuid4


DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765


class KakaoMapServer:
    """Serve a Kakao dynamic map locally without writing the JS key to disk."""

    def __init__(
        self,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> None:
        self.host = host
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._pages: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    @property
    def origin(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        if self._server is not None:
            return

        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib protocol name
                parsed = urlparse(self.path)
                token = parsed.path.removeprefix("/map/").strip("/")
                if not parsed.path.startswith("/map/") or not token:
                    self.send_error(404)
                    return
                with owner._lock:
                    page = owner._pages.get(token)
                if page is None:
                    self.send_error(404)
                    return
                embedded = parse_qs(parsed.query).get("embed") == ["1"]
                payload = _render_page(
                    page,
                    embedded=embedded,
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args: Any) -> None:
                return

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="kakao-map-local-server",
            daemon=True,
        )
        self._thread.start()

    def register(
        self,
        *,
        javascript_key: str,
        title: str,
        address: str,
        latitude: str,
        longitude: str,
        nearby_places: dict[str, list[dict[str, Any]]],
    ) -> str:
        if not javascript_key.strip():
            raise ValueError("Kakao JavaScript 키가 필요합니다.")
        try:
            lat = float(latitude)
            lng = float(longitude)
        except (TypeError, ValueError) as exc:
            raise ValueError("동적 지도를 열 수 있는 좌표가 없습니다.") from exc
        self.start()
        token = uuid4().hex
        with self._lock:
            self._pages[token] = {
                "javascript_key": javascript_key.strip(),
                "title": title.strip() or "매물 위치",
                "address": address.strip(),
                "latitude": lat,
                "longitude": lng,
                "nearby_places": nearby_places,
            }
            if len(self._pages) > 20:
                oldest = next(iter(self._pages))
                self._pages.pop(oldest, None)
        return f"{self.origin}/map/{token}"

    def stop(self) -> None:
        server = self._server
        if server is None:
            return
        server.shutdown()
        server.server_close()
        self._server = None
        self._thread = None
        with self._lock:
            self._pages.clear()


def _render_page(
    page: dict[str, Any],
    *,
    embedded: bool = False,
) -> str:
    key = quote(str(page["javascript_key"]), safe="")
    title = html.escape(str(page["title"]))
    address = html.escape(str(page["address"]))
    payload = {
        "title": page["title"],
        "latitude": page["latitude"],
        "longitude": page["longitude"],
        "nearby": page["nearby_places"],
    }
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    body_class = ' class="embedded"' if embedded else ""
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title} · 동적 지도/로드뷰</title>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ height: 100%; margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif; color: #183247; }}
    body {{ display: grid; grid-template-rows: auto 1fr; background: #eef3f6; }}
    header {{ display: flex; gap: 12px; align-items: center; padding: 12px 16px; background: #16344c; color: white; }}
    header .meta {{ flex: 1; min-width: 0; }}
    header strong, header small {{ display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    header small {{ margin-top: 3px; color: #dce8ef; }}
    button {{ border: 1px solid #8ca2b1; border-radius: 8px; padding: 9px 14px; cursor: pointer; background: white; color: #16344c; font-weight: 700; }}
    button.active {{ background: #d6a546; border-color: #d6a546; color: #172c3c; }}
    main {{ min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) 310px; gap: 10px; padding: 10px; }}
    #viewer {{ min-height: 420px; position: relative; border-radius: 10px; overflow: hidden; background: white; }}
    #map, #roadview {{ width: 100%; height: 100%; min-height: 420px; }}
    #roadview {{ display: none; }}
    #roadviewMessage {{ display: none; position: absolute; inset: 0; place-items: center; padding: 30px; text-align: center; background: white; z-index: 2; }}
    aside {{ overflow: auto; background: white; border-radius: 10px; padding: 14px; }}
    aside h2 {{ margin: 0 0 8px; font-size: 17px; }}
    aside p {{ margin: 0 0 12px; color: #607384; font-size: 13px; line-height: 1.5; }}
    .place {{ padding: 9px 0; border-top: 1px solid #e3e9ed; }}
    .place b, .place span {{ display: block; }}
    .place span {{ margin-top: 3px; color: #607384; font-size: 12px; }}
    .error {{ padding: 24px; color: #9b302b; white-space: pre-wrap; }}
    body.embedded {{ display: block; }}
    body.embedded header, body.embedded aside {{ display: none; }}
    body.embedded main {{ display: block; height: 100%; padding: 0; }}
    body.embedded #viewer, body.embedded #map, body.embedded #roadview {{
      width: 100%; height: 100%; min-height: 100%;
      border-radius: 0;
    }}
    @media (max-width: 760px) {{
      header {{ flex-wrap: wrap; }}
      header .meta {{ flex-basis: 100%; }}
      main {{ grid-template-columns: 1fr; grid-template-rows: minmax(440px, 65vh) auto; }}
    }}
  </style>
  <script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={key}"></script>
</head>
<body{body_class}>
  <header>
    <div class="meta"><strong>{title}</strong><small>{address}</small></div>
    <button id="mapButton" class="active" type="button">지도 보기</button>
    <button id="roadviewButton" type="button">로드뷰 보기</button>
  </header>
  <main>
    <section id="viewer">
      <div id="map"></div>
      <div id="roadview"></div>
      <div id="roadviewMessage">이 위치 주변에 제공되는 로드뷰가 없습니다.</div>
    </section>
    <aside>
      <h2>주변 시설</h2>
      <p>카카오 로컬 API 기준 직선거리입니다. 실제 이동 경로와 다를 수 있습니다.</p>
      <div id="places"></div>
    </aside>
  </main>
  <script>
    if (!window.kakao || !window.kakao.maps) {{
      const target = document.getElementById("map");
      target.className = "error";
      target.textContent =
        "Kakao 지도를 불러오지 못했습니다. JavaScript 키, 지도 API 사용 설정, " +
        "JavaScript SDK 도메인(http://localhost:8765)을 확인해 주세요.";
      throw new Error("Kakao Maps SDK was not loaded");
    }}
    const data = {data_json};
    const center = new kakao.maps.LatLng(data.latitude, data.longitude);
    const map = new kakao.maps.Map(document.getElementById("map"), {{ center, level: 4 }});
    new kakao.maps.Marker({{ map, position: center, title: data.title }});
    const placesNode = document.getElementById("places");
    Object.entries(data.nearby || {{}}).forEach(([category, places]) => {{
      (places || []).forEach((place) => {{
        const lat = Number(place.latitude);
        const lng = Number(place.longitude);
        if (Number.isFinite(lat) && Number.isFinite(lng)) {{
          new kakao.maps.Marker({{
            map,
            position: new kakao.maps.LatLng(lat, lng),
            title: `${{category}} · ${{place.name || "이름 미확인"}}`
          }});
        }}
        const row = document.createElement("div");
        row.className = "place";
        const name = document.createElement("b");
        name.textContent = `${{category}} · ${{place.name || "이름 미확인"}}`;
        const detail = document.createElement("span");
        const distance = Number(place.distance_m);
        detail.textContent = `${{Number.isFinite(distance) ? distance.toLocaleString() + "m" : "거리 미확인"}} · ${{place.road_address || ""}}`;
        row.append(name, detail);
        placesNode.appendChild(row);
      }});
    }});
    if (!placesNode.children.length) placesNode.textContent = "확인된 주변 시설이 없습니다.";

    const roadview = new kakao.maps.Roadview(document.getElementById("roadview"));
    const roadviewClient = new kakao.maps.RoadviewClient();
    let roadviewReady = false;
    const mapNode = document.getElementById("map");
    const roadviewNode = document.getElementById("roadview");
    const messageNode = document.getElementById("roadviewMessage");
    const mapButton = document.getElementById("mapButton");
    const roadviewButton = document.getElementById("roadviewButton");

    function showMap() {{
      mapNode.style.display = "block";
      roadviewNode.style.display = "none";
      messageNode.style.display = "none";
      mapButton.classList.add("active");
      roadviewButton.classList.remove("active");
      setTimeout(() => {{ map.relayout(); map.setCenter(center); }}, 0);
    }}
    function showRoadview() {{
      mapNode.style.display = "none";
      roadviewNode.style.display = "block";
      messageNode.style.display = "none";
      mapButton.classList.remove("active");
      roadviewButton.classList.add("active");
      if (roadviewReady) return;
      roadviewClient.getNearestPanoId(center, 100, (panoId) => {{
        if (panoId === null) {{
          roadviewNode.style.display = "none";
          messageNode.style.display = "grid";
          return;
        }}
        roadview.setPanoId(panoId, center);
        roadviewReady = true;
      }});
    }}
    mapButton.addEventListener("click", showMap);
    roadviewButton.addEventListener("click", showRoadview);
    window.showMap = showMap;
    window.showRoadview = showRoadview;
    window.zoomMap = (delta) => {{
      if (mapNode.style.display !== "none") {{
        const level = Math.max(1, Math.min(14, map.getLevel() + Number(delta)));
        map.setLevel(level, {{ anchor: map.getCenter() }});
      }}
    }};
  </script>
</body>
</html>"""
