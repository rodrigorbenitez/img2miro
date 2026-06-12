"""Unit tests for the CLI startup gate — no network, no Claude Code CLI.

`_logged_in` and `_check_claude_code` are the only branching logic in cli.py
worth covering on their own; `shutil.which`, `subprocess.run`, and the tty
check are faked so nothing real runs and no browser opens.
"""

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from img2miro.cli import _check_claude_code, _logged_in


def _proc(stdout: str) -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, returncode=0)


class LoggedInHelperTests(unittest.TestCase):
    def test_true_when_status_reports_logged_in(self):
        with patch(
            "img2miro.cli.subprocess.run", return_value=_proc('{"loggedIn": true}')
        ):
            self.assertTrue(_logged_in("claude"))

    def test_false_when_status_reports_logged_out(self):
        with patch(
            "img2miro.cli.subprocess.run", return_value=_proc('{"loggedIn": false}')
        ):
            self.assertFalse(_logged_in("claude"))

    def test_false_on_unparseable_status(self):
        with patch("img2miro.cli.subprocess.run", return_value=_proc("not json")):
            self.assertFalse(_logged_in("claude"))

    def test_false_on_subprocess_failure(self):
        with patch(
            "img2miro.cli.subprocess.run",
            side_effect=subprocess.TimeoutExpired("claude", 30),
        ):
            self.assertFalse(_logged_in("claude"))


class CheckClaudeCodeTests(unittest.TestCase):
    def test_missing_cli_exits_with_setup_help(self):
        with patch("img2miro.cli.shutil.which", return_value=None):
            with self.assertRaises(SystemExit) as ctx:
                _check_claude_code()
        self.assertIn("not found", str(ctx.exception))

    def test_oauth_token_skips_auth_check(self):
        # With a token set, auth status must not be checked at all.
        with patch("img2miro.cli.shutil.which", return_value="claude"), patch.dict(
            "os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}, clear=False
        ), patch("img2miro.cli._logged_in") as logged_in:
            _check_claude_code()
        logged_in.assert_not_called()

    def test_already_signed_in_passes(self):
        with patch("img2miro.cli.shutil.which", return_value="claude"), patch.dict(
            "os.environ", {}, clear=True
        ), patch("img2miro.cli._logged_in", return_value=True):
            _check_claude_code()  # no SystemExit, no browser launch

    def test_not_signed_in_noninteractive_exits(self):
        with patch("img2miro.cli.shutil.which", return_value="claude"), patch.dict(
            "os.environ", {}, clear=True
        ), patch("img2miro.cli._logged_in", return_value=False), patch(
            "img2miro.cli.sys.stdin.isatty", return_value=False
        ), patch("img2miro.cli.subprocess.run") as run:
            with self.assertRaises(SystemExit) as ctx:
                _check_claude_code()
        self.assertIn("sign-in required", str(ctx.exception))
        run.assert_not_called()  # never tries to open a browser when headless

    def test_interactive_launches_browser_login_then_continues(self):
        # Logged out, then logged in after the browser sign-in completes.
        with patch("img2miro.cli.shutil.which", return_value="claude"), patch.dict(
            "os.environ", {}, clear=True
        ), patch(
            "img2miro.cli._logged_in", side_effect=[False, True]
        ), patch("img2miro.cli.sys.stdin.isatty", return_value=True), patch(
            "img2miro.cli.subprocess.run"
        ) as run:
            _check_claude_code()  # no SystemExit
        run.assert_called_once_with(["claude", "auth", "login", "--claudeai"])

    def test_interactive_login_that_fails_still_exits(self):
        with patch("img2miro.cli.shutil.which", return_value="claude"), patch.dict(
            "os.environ", {}, clear=True
        ), patch("img2miro.cli._logged_in", return_value=False), patch(
            "img2miro.cli.sys.stdin.isatty", return_value=True
        ), patch("img2miro.cli.subprocess.run") as run:
            with self.assertRaises(SystemExit) as ctx:
                _check_claude_code()
        self.assertIn("sign-in required", str(ctx.exception))
        run.assert_called_once()  # the browser login was attempted


if __name__ == "__main__":
    unittest.main()
