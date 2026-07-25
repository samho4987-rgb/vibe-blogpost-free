from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from naver_blog_automation.naver_blog import (
    NaverBlogError,
    NaverBlogPoster,
    NaverLoginRequired,
)


class _Control:
    def __init__(self) -> None:
        self.filled: list[str] = []
        self.clicked = False

    def fill(self, value: str) -> None:
        self.filled.append(value)

    def click(self) -> None:
        self.clicked = True


class _Page:
    def __init__(self) -> None:
        self.waits: list[int] = []
        self.keyboard = _Keyboard()

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.waits.append(milliseconds)

    def is_closed(self) -> bool:
        return False


class _ClosingPage(_Page):
    def __init__(self) -> None:
        super().__init__()
        self.closed_checks = 0

    def is_closed(self) -> bool:
        self.closed_checks += 1
        return self.closed_checks >= 2


class _Context:
    def __init__(self, page: _Page) -> None:
        self.pages = [page]
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _PlaywrightManager:
    def __enter__(self):
        return object()

    def __exit__(self, *_args) -> None:
        return None


class _Keyboard:
    def __init__(self) -> None:
        self.pressed: list[str] = []

    def press(self, key: str) -> None:
        self.pressed.append(key)


class _InterceptedDraftButton:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def click(self, **kwargs) -> None:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise RuntimeError("subtree intercepts pointer events")


class NaverLoginTests(unittest.TestCase):
    def _poster(self, root: Path) -> NaverBlogPoster:
        selector_path = root / "selectors.yaml"
        selector_path.write_text(
            """
login:
  id: ["#id"]
  password: ["#pw"]
  submit: ["#loginBtn_column", "#loginBtn_row"]
editor: {}
""".strip()
            + "\n",
            encoding="utf-8",
        )
        return NaverBlogPoster(
            profile_dir=root / "profile",
            selector_path=selector_path,
        )

    def test_login_requires_both_id_and_password(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poster = self._poster(Path(temp_dir))
            with self.assertRaises(NaverBlogError):
                poster.open_login(naver_id="login_user", password="")

    def test_login_form_uses_configured_fields_and_submit_button(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poster = self._poster(Path(temp_dir))
            id_input = _Control()
            password_input = _Control()
            submit = _Control()
            config = poster.selectors["login"]

            with patch.object(
                poster,
                "_first_visible",
                side_effect=[id_input, password_input, submit],
            ) as find_visible:
                poster._submit_login_form(
                    object(),
                    config,
                    "login_user",
                    "private-password",
                )

            self.assertEqual(id_input.filled, ["login_user"])
            self.assertEqual(password_input.filled, ["private-password"])
            self.assertTrue(submit.clicked)
            self.assertEqual(find_visible.call_args_list[0].args[1], ["#id"])
            self.assertEqual(find_visible.call_args_list[1].args[1], ["#pw"])
            self.assertEqual(
                find_visible.call_args_list[2].args[1],
                ["#loginBtn_column", "#loginBtn_row"],
            )

    def test_draft_recovery_popup_is_cancelled_when_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poster = self._poster(Path(temp_dir))
            poster.selectors["editor"]["draft_popup_cancel"] = [
                ".se-popup-alert-confirm button.se-popup-button-cancel"
            ]
            button = _Control()
            page = _Page()
            with patch.object(
                poster,
                "_first_visible",
                return_value=button,
            ):
                dismissed = poster._dismiss_draft_popup(page, object())

            self.assertTrue(dismissed)
            self.assertTrue(button.clicked)
            self.assertEqual(page.waits, [350])

    def test_help_overlay_is_closed_before_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poster = self._poster(Path(temp_dir))
            poster.selectors["popup"] = {
                "blocking_help": ["h1.se-help-title"],
                "close": ["button.se-help-panel-close-button"],
            }
            help_panel = object()
            close_button = _Control()
            page = _Page()
            with patch.object(
                poster,
                "_first_visible",
                side_effect=[help_panel, close_button],
            ):
                dismissed = poster._dismiss_blocking_overlays(page, object())

            self.assertTrue(dismissed)
            self.assertTrue(close_button.clicked)
            self.assertEqual(page.waits, [250])

    def test_draft_click_retries_with_force_after_overlay_interception(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poster = self._poster(Path(temp_dir))
            poster.selectors["publish"] = {"draft": [".save_btn__bzc5B"]}
            button = _InterceptedDraftButton()
            page = _Page()
            with (
                patch.object(
                    poster,
                    "_dismiss_blocking_overlays",
                    return_value=True,
                ) as dismiss,
                patch.object(
                    poster,
                    "_first_visible",
                    return_value=button,
                ),
            ):
                poster._click_draft(page, object())

            self.assertEqual(dismiss.call_count, 2)
            self.assertEqual(button.calls[0], {"timeout": 4_000})
            self.assertEqual(
                button.calls[1],
                {"force": True, "timeout": 4_000},
            )
            self.assertEqual(page.waits, [2500])

    def test_draft_closed_browser_has_friendly_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poster = self._poster(Path(temp_dir))
            page = _Page()
            page.is_closed = lambda: True  # type: ignore[method-assign]
            with self.assertRaisesRegex(
                NaverBlogError,
                "브라우저 창이 닫혔습니다",
            ):
                poster._click_draft(page, object())

    def test_draft_retries_editor_in_same_page_after_automatic_login(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poster = self._poster(Path(temp_dir))
            page = object()
            scope = object()
            with (
                patch.object(
                    poster,
                    "_open_editor",
                    side_effect=[NaverLoginRequired("login"), scope],
                ) as open_editor,
                patch.object(poster, "_login_page") as login_page,
            ):
                result = poster._open_editor_with_login(
                    page,
                    blog_id="personal-blog",
                    naver_id="personal-user",
                    password="private-password",
                )

            self.assertIs(result, scope)
            self.assertEqual(open_editor.call_count, 2)
            login_page.assert_called_once_with(
                page,
                "personal-user",
                "private-password",
            )

    def test_draft_reauthenticates_when_wrong_account_cannot_open_editor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poster = self._poster(Path(temp_dir))
            scope = object()
            with (
                patch.object(
                    poster,
                    "_open_editor",
                    side_effect=[NaverBlogError("editor unavailable"), scope],
                ),
                patch.object(poster, "_login_page") as login_page,
            ):
                result = poster._open_editor_with_login(
                    object(),
                    blog_id="personal-blog",
                    naver_id="personal-user",
                    password="private-password",
                )

            self.assertIs(result, scope)
            self.assertEqual(login_page.call_count, 1)

    def test_draft_login_recovery_requires_saved_or_entered_password(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poster = self._poster(Path(temp_dir))
            with patch.object(
                poster,
                "_open_editor",
                side_effect=NaverLoginRequired("login"),
            ):
                with self.assertRaisesRegex(
                    NaverLoginRequired,
                    "저장된 비밀번호",
                ):
                    poster._open_editor_with_login(
                        object(),
                        blog_id="personal-blog",
                    )

    def test_saved_draft_keeps_browser_open_until_user_closes_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            poster = self._poster(Path(temp_dir))
            page = _ClosingPage()
            context = _Context(page)
            saved: list[bool] = []
            with (
                patch.object(
                    poster,
                    "_playwright",
                    return_value=(lambda: _PlaywrightManager(), Exception),
                ),
                patch.object(
                    poster,
                    "_launch_context",
                    return_value=context,
                ),
                patch.object(
                    poster,
                    "_open_editor_with_login",
                    return_value=object(),
                ),
                patch.object(poster, "_dismiss_draft_popup"),
                patch.object(poster, "_fill_title"),
                patch.object(poster, "_fill_body"),
                patch.object(poster, "_click_draft"),
            ):
                poster.save_draft(
                    blog_id="personal-blog",
                    content=type(
                        "_Content",
                        (),
                        {
                            "title": "제목",
                            "body": "본문",
                            "hashtags": [],
                        },
                    )(),
                    keep_browser_open=True,
                    on_saved=lambda published=False: saved.append(True),
                )

            self.assertEqual(saved, [True])
            self.assertIn(1_000, page.waits)
            self.assertTrue(context.closed)


if __name__ == "__main__":
    unittest.main()
