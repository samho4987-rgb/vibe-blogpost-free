from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any


FrameCallback = Callable[[bytes, int, int], None]
MessageCallback = Callable[[str], None]


class EmbeddedMapRenderer:
    """Render and control a Kakao web map in a background Chromium page."""

    def __init__(
        self,
        *,
        on_frame: FrameCallback,
        on_error: MessageCallback,
        on_status: MessageCallback | None = None,
        browser_channel: str = "chrome",
    ) -> None:
        self.on_frame = on_frame
        self.on_error = on_error
        self.on_status = on_status or (lambda _message: None)
        self.browser_channel = browser_channel.strip() or "chrome"
        self._commands: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self._thread = threading.Thread(
            target=self._worker,
            name="embedded-kakao-map",
            daemon=True,
        )
        self._thread.start()

    def load(self, url: str, width: int, height: int) -> None:
        separator = "&" if "?" in url else "?"
        self._commands.put(
            (
                "load",
                {
                    "url": f"{url}{separator}embed=1",
                    "width": width,
                    "height": height,
                },
            )
        )

    def resize(self, width: int, height: int) -> None:
        self._commands.put(
            ("resize", {"width": width, "height": height})
        )

    def show_map(self) -> None:
        self._commands.put(("show_map", {}))

    def show_roadview(self) -> None:
        self._commands.put(("show_roadview", {}))

    def zoom(self, delta: int) -> None:
        self._commands.put(("zoom", {"delta": delta}))

    def pointer(self, kind: str, x: float, y: float) -> None:
        self._commands.put(
            ("pointer", {"kind": kind, "x": x, "y": y})
        )

    def wheel(self, delta_y: float) -> None:
        self._commands.put(("wheel", {"delta_y": delta_y}))

    def refresh(self) -> None:
        self._commands.put(("refresh", {}))

    def stop(self) -> None:
        try:
            while True:
                self._commands.get_nowait()
        except queue.Empty:
            pass
        self._commands.put(("stop", {}))
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    @staticmethod
    def _size(payload: dict[str, Any]) -> tuple[int, int]:
        width = max(360, min(int(payload.get("width") or 720), 1400))
        height = max(280, min(int(payload.get("height") or 420), 900))
        return width, height

    def _worker(self) -> None:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch(
                        channel=self.browser_channel,
                        headless=True,
                    )
                except Exception:
                    browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(
                    viewport={"width": 720, "height": 420}
                )
                loaded = False
                width, height = 720, 420

                def render(delay_ms: int = 250) -> None:
                    if not loaded:
                        return
                    if delay_ms:
                        page.wait_for_timeout(delay_ms)
                    image = page.screenshot(type="png")
                    self.on_frame(image, width, height)

                while True:
                    command, payload = self._commands.get()
                    try:
                        if command == "stop":
                            break
                        if command == "load":
                            width, height = self._size(payload)
                            page.set_viewport_size(
                                {"width": width, "height": height}
                            )
                            self.on_status(
                                "프로그램 안에서 카카오 지도를 불러오고 있습니다…"
                            )
                            page.goto(
                                str(payload["url"]),
                                wait_until="domcontentloaded",
                                timeout=20_000,
                            )
                            loaded = True
                            render(1_200)
                        elif command == "resize" and loaded:
                            width, height = self._size(payload)
                            page.set_viewport_size(
                                {"width": width, "height": height}
                            )
                            render(200)
                        elif command == "show_map" and loaded:
                            page.evaluate("window.showMap && window.showMap()")
                            render(350)
                        elif command == "show_roadview" and loaded:
                            page.evaluate(
                                "window.showRoadview && window.showRoadview()"
                            )
                            render(1_500)
                        elif command == "zoom" and loaded:
                            page.evaluate(
                                "(delta) => window.zoomMap && "
                                "window.zoomMap(delta)",
                                int(payload["delta"]),
                            )
                            render(350)
                        elif command == "pointer" and loaded:
                            x = float(payload["x"])
                            y = float(payload["y"])
                            kind = str(payload["kind"])
                            if kind == "down":
                                page.mouse.move(x, y)
                                page.mouse.down()
                            elif kind == "move":
                                page.mouse.move(x, y)
                            elif kind == "up":
                                page.mouse.move(x, y)
                                page.mouse.up()
                                render(400)
                        elif command == "wheel" and loaded:
                            page.mouse.wheel(0, float(payload["delta_y"]))
                            render(400)
                        elif command == "refresh" and loaded:
                            page.reload(
                                wait_until="domcontentloaded",
                                timeout=20_000,
                            )
                            render(1_200)
                    except Exception as exc:
                        self.on_error(str(exc))
                browser.close()
        except Exception as exc:
            self.on_error(
                "내장 지도용 Chromium을 시작하지 못했습니다. "
                f"설치 스크립트를 다시 실행해 주세요. ({exc})"
            )
