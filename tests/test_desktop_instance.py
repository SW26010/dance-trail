from http.client import IncompleteRead
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from urllib.error import URLError
import uuid
import webbrowser
from unittest.mock import MagicMock, patch

from dance_trail.desktop_instance import (
    ERROR_ALREADY_EXISTS,
    WAIT_ABANDONED,
    WindowsDesktopInstanceLease,
    open_existing_webui,
    publish_desktop_port,
    read_desktop_port,
)
from dance_trail.webui_server import WebUiServer


class DesktopInstanceTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows named mapping test")
    def test_actual_port_is_visible_to_other_processes_only_while_published(self):
        name = f"Local\\DanceTrail.DesktopTray.Test.{uuid.uuid4()}"
        self.assertIsNone(read_desktop_port(name=name))
        with publish_desktop_port(54321, name=name):
            probe = subprocess.run(
                [sys.executable, "-c", (
                    "import sys; "
                    "from dance_trail.desktop_instance import read_desktop_port; "
                    "print(read_desktop_port(name=sys.argv[1]))"
                ), name],
                capture_output=True, text=True, check=True,
            )
            self.assertEqual(probe.stdout.strip(), "54321")
        self.assertIsNone(read_desktop_port(name=name))

    @staticmethod
    def _webui_response(body: bytes = b"<title>DanceTrail</title>") -> MagicMock:
        response = MagicMock()
        response.status = 200
        response.read.return_value = body
        response.__enter__.return_value = response
        return response

    @unittest.skipUnless(sys.platform == "win32", "Windows named mutex test")
    def test_named_mutex_allows_only_one_desktop_owner(self):
        name = f"Local\\DanceTrail.DesktopTray.Test.{uuid.uuid4()}"
        first = WindowsDesktopInstanceLease.acquire(name)
        self.assertIsNotNone(first)
        try:
            self.assertIsNone(WindowsDesktopInstanceLease.acquire(name))
            probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; "
                        "from dance_trail.desktop_instance import "
                        "WindowsDesktopInstanceLease; "
                        "lease = WindowsDesktopInstanceLease.acquire(sys.argv[1]); "
                        "raise SystemExit(0 if lease is None else 1)"
                    ),
                    name,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(probe.returncode, 0, probe.stderr)
        finally:
            first.close()

        replacement = WindowsDesktopInstanceLease.acquire(name)
        self.assertIsNotNone(replacement)
        replacement.close()

    def test_named_mutex_takes_ownership_when_previous_owner_is_abandoned(self):
        kernel32 = MagicMock()
        kernel32.CreateMutexW.return_value = 123
        kernel32.WaitForSingleObject.return_value = WAIT_ABANDONED
        kernel32.ReleaseMutex.return_value = True
        kernel32.CloseHandle.return_value = True

        with (
            patch("dance_trail.desktop_instance._load_kernel32", return_value=kernel32),
            patch("dance_trail.desktop_instance.ctypes.set_last_error"),
            patch(
                "dance_trail.desktop_instance.ctypes.get_last_error",
                return_value=ERROR_ALREADY_EXISTS,
            ),
        ):
            lease = WindowsDesktopInstanceLease.acquire("Local\\abandoned-test")

        self.assertIsNotNone(lease)
        kernel32.WaitForSingleObject.assert_called_once_with(123, 0)
        kernel32.CloseHandle.assert_not_called()
        lease.close()
        kernel32.ReleaseMutex.assert_called_once_with(123)
        kernel32.CloseHandle.assert_called_once_with(123)

    def test_existing_webui_is_verified_before_browser_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            try:
                with patch("dance_trail.desktop_instance.webbrowser.open") as open_browser:
                    opened = open_existing_webui(server.home_url, wait_seconds=1.0)
            finally:
                server.stop()

        self.assertTrue(opened)
        open_browser.assert_called_once_with(server.home_url)

    def test_existing_webui_reports_browser_open_failure(self):
        response = self._webui_response()
        home_url = "http://127.0.0.1:8787/home"

        with (
            patch(
                "dance_trail.desktop_instance._DIRECT_HTTP_OPENER.open",
                return_value=response,
            ),
            patch(
                "dance_trail.desktop_instance.webbrowser.open",
                return_value=False,
            ) as open_browser,
        ):
            opened = open_existing_webui(home_url, wait_seconds=1.0)

        self.assertFalse(opened)
        open_browser.assert_called_once_with(home_url)

    def test_existing_webui_browser_error_becomes_false(self):
        response = self._webui_response()
        home_url = "http://127.0.0.1:8787/home"

        with (
            patch(
                "dance_trail.desktop_instance._DIRECT_HTTP_OPENER.open",
                return_value=response,
            ),
            patch(
                "dance_trail.desktop_instance.webbrowser.open",
                side_effect=webbrowser.Error("no runnable browser"),
            ) as open_browser,
        ):
            opened = open_existing_webui(home_url, wait_seconds=1.0)

        self.assertFalse(opened)
        open_browser.assert_called_once_with(home_url)

    def test_existing_webui_probe_ignores_environment_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            try:
                with (
                    patch.dict(
                        os.environ,
                        {
                            "HTTP_PROXY": "http://127.0.0.1:1",
                            "http_proxy": "http://127.0.0.1:1",
                            "NO_PROXY": "",
                            "no_proxy": "",
                        },
                    ),
                    patch.object(urllib.request, "_opener", None),
                    patch(
                        "dance_trail.desktop_instance.webbrowser.open",
                        return_value=True,
                    ),
                ):
                    opened = open_existing_webui(server.home_url, wait_seconds=1.0)
            finally:
                server.stop()

        self.assertTrue(opened)

    def test_existing_webui_http_exception_becomes_false(self):
        response = self._webui_response()
        response.read.side_effect = IncompleteRead(b"", 1)

        with patch(
            "dance_trail.desktop_instance._DIRECT_HTTP_OPENER.open",
            return_value=response,
        ):
            opened = open_existing_webui(
                "http://127.0.0.1:8787/home",
                wait_seconds=0.0,
            )

        self.assertFalse(opened)

    def test_existing_webui_identity_mismatch_does_not_open_browser(self):
        response = self._webui_response(b"<title>unrelated service</title>")

        with (
            patch(
                "dance_trail.desktop_instance._DIRECT_HTTP_OPENER.open",
                return_value=response,
            ),
            patch("dance_trail.desktop_instance.webbrowser.open") as open_browser,
        ):
            opened = open_existing_webui(
                "http://127.0.0.1:8787/home",
                wait_seconds=0.0,
            )

        self.assertFalse(opened)
        open_browser.assert_not_called()

    def test_existing_webui_retries_after_expected_network_failure(self):
        response = self._webui_response()

        with (
            patch(
                "dance_trail.desktop_instance._DIRECT_HTTP_OPENER.open",
                side_effect=[URLError("not ready"), response],
            ) as open_url,
            patch(
                "dance_trail.desktop_instance.webbrowser.open",
                return_value=True,
            ),
            patch("dance_trail.desktop_instance.time.sleep"),
        ):
            opened = open_existing_webui(
                "http://127.0.0.1:8787/home",
                wait_seconds=1.0,
            )

        self.assertTrue(opened)
        self.assertEqual(open_url.call_count, 2)
