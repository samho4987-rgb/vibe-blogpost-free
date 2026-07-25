from __future__ import annotations

import unittest
from unittest.mock import patch

from naver_blog_automation.credentials import (
    ESILJANG_CREDENTIAL_SERVICE,
    NAVER_CREDENTIAL_SERVICE,
    delete_esiljang_password,
    delete_naver_password,
    load_esiljang_password,
    load_naver_password,
    save_esiljang_password,
    save_naver_password,
)


class _FakeKeyringError(Exception):
    pass


class _FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


class CredentialStoreTests(unittest.TestCase):
    def test_password_round_trip_uses_os_keyring_service(self) -> None:
        fake = _FakeKeyring()
        with patch(
            "naver_blog_automation.credentials._keyring",
            return_value=(fake, _FakeKeyringError),
        ):
            save_naver_password(" sample-user ", "private-password")
            self.assertEqual(
                fake.values[(NAVER_CREDENTIAL_SERVICE, "sample-user")],
                "private-password",
            )
            self.assertEqual(
                load_naver_password("sample-user"),
                "private-password",
            )
            delete_naver_password("sample-user")
            self.assertEqual(load_naver_password("sample-user"), "")

    def test_esiljang_password_uses_separate_os_keyring_service(self) -> None:
        fake = _FakeKeyring()
        with patch(
            "naver_blog_automation.credentials._keyring",
            return_value=(fake, _FakeKeyringError),
        ):
            save_esiljang_password(" office-user ", "office-password")
            self.assertEqual(
                fake.values[(ESILJANG_CREDENTIAL_SERVICE, "office-user")],
                "office-password",
            )
            self.assertEqual(
                load_esiljang_password("office-user"),
                "office-password",
            )
            delete_esiljang_password("office-user")
            self.assertEqual(load_esiljang_password("office-user"), "")


if __name__ == "__main__":
    unittest.main()
