from __future__ import annotations

import unittest
from pathlib import Path

import yaml


class SelectorConfigTests(unittest.TestCase):
    def test_required_editor_and_draft_selectors_exist(self) -> None:
        path = Path(__file__).resolve().parents[1] / "config" / "blog_selectors.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertIn("#id", data["login"]["id"])
        self.assertIn("#pw", data["login"]["password"])
        self.assertIn("#loginBtn_column", data["login"]["submit"])
        self.assertIn(r"#log\.login", data["login"]["submit"])
        self.assertTrue(data["editor"]["draft_popup_cancel"])
        self.assertTrue(data["editor"]["title"])
        self.assertTrue(data["editor"]["body"])
        self.assertTrue(
            all("#SE-" not in selector for selector in data["editor"]["title"])
        )
        self.assertTrue(
            all(
                "data-a11y-title='본문'" in selector
                or ".se-component.se-text" in selector
                or ".se-section-text" in selector
                for selector in data["editor"]["body"]
            )
        )
        self.assertTrue(data["insert"]["image"]["file_input"])
        self.assertTrue(data["publish"]["draft"])


if __name__ == "__main__":
    unittest.main()
