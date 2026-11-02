from __future__ import annotations

import base64

from agent2.executor.screen import is_valid_png, take_screenshot


class TestScreenshot:
    def test_returns_valid_png(self):
        shot = take_screenshot(timeout=5.0)
        assert shot["status"] == "ok"
        assert shot["mime"] == "image/png"
        raw = base64.b64decode(shot["screenshot_b64"])
        assert is_valid_png(raw)
        assert len(raw) > 100

    def test_sources_are_known(self):
        shot = take_screenshot(timeout=5.0)
        assert shot["source"] in {"scrot", "pillow", "synthetic"}