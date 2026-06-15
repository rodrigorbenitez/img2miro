"""Unit tests for the CLI startup gate — no network, no Claude Code CLI.

`_logged_in`, `_check_claude_code`, and `_choose_model` are the branching
logic in cli.py worth covering on their own; `shutil.which`, `subprocess.run`,
`input`, and the tty check are faked so nothing real runs and no browser opens.
"""

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from img2miro.cli import (
    _check_claude_code,
    _choose_backend,
    _choose_model,
    _logged_in,
)
from img2miro.extractor import BACKENDS, DEFAULT_BACKEND, DEFAULT_MODEL, SUPPORTED_MODELS


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

    def test_oauth_token_skips_browser_login(self):
        # A headless token bypasses the browser sign-in entirely.
        with patch("img2miro.cli.shutil.which", return_value="claude"), patch.dict(
            "os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}, clear=False
        ), patch("img2miro.cli.subprocess.run") as run:
            _check_claude_code()
        run.assert_not_called()

    def test_forces_browser_login_every_run_then_continues(self):
        # Even with no token, the browser login is launched unconditionally;
        # once it reports signed in, the run proceeds.
        with patch("img2miro.cli.shutil.which", return_value="claude"), patch.dict(
            "os.environ", {}, clear=True
        ), patch("img2miro.cli.subprocess.run") as run, patch(
            "img2miro.cli._logged_in", return_value=True
        ):
            _check_claude_code()  # no SystemExit
        run.assert_called_once_with(["claude", "auth", "login", "--claudeai"])

    def test_exits_when_login_does_not_authenticate(self):
        with patch("img2miro.cli.shutil.which", return_value="claude"), patch.dict(
            "os.environ", {}, clear=True
        ), patch("img2miro.cli.subprocess.run") as run, patch(
            "img2miro.cli._logged_in", return_value=False
        ):
            with self.assertRaises(SystemExit) as ctx:
                _check_claude_code()
        self.assertIn("sign-in required", str(ctx.exception))
        run.assert_called_once()  # the browser login was attempted


class ChooseBackendTests(unittest.TestCase):
    def test_non_tty_returns_default_without_prompting(self):
        with patch("img2miro.cli.sys.stdin.isatty", return_value=False), patch(
            "builtins.input"
        ) as prompt:
            self.assertEqual(_choose_backend(), DEFAULT_BACKEND)
        prompt.assert_not_called()

    def test_empty_input_returns_default(self):
        with patch("img2miro.cli.sys.stdin.isatty", return_value=True), patch(
            "builtins.input", return_value=""
        ):
            self.assertEqual(_choose_backend(), DEFAULT_BACKEND)

    def test_numeric_choice_selects_that_backend(self):
        with patch("img2miro.cli.sys.stdin.isatty", return_value=True), patch(
            "builtins.input", return_value="2"
        ):
            self.assertEqual(_choose_backend(), BACKENDS[1])

    def test_out_of_range_choice_falls_back_to_default(self):
        with patch("img2miro.cli.sys.stdin.isatty", return_value=True), patch(
            "builtins.input", return_value="99"
        ):
            self.assertEqual(_choose_backend(), DEFAULT_BACKEND)


class ChooseModelTests(unittest.TestCase):
    def test_non_tty_returns_default_without_prompting(self):
        with patch("img2miro.cli.sys.stdin.isatty", return_value=False), patch(
            "builtins.input"
        ) as prompt:
            self.assertEqual(_choose_model(), DEFAULT_MODEL)
        prompt.assert_not_called()

    def test_empty_input_returns_default(self):
        with patch("img2miro.cli.sys.stdin.isatty", return_value=True), patch(
            "builtins.input", return_value=""
        ):
            self.assertEqual(_choose_model(), DEFAULT_MODEL)

    def test_numeric_choice_selects_that_model(self):
        with patch("img2miro.cli.sys.stdin.isatty", return_value=True), patch(
            "builtins.input", return_value="2"
        ):
            self.assertEqual(_choose_model(), SUPPORTED_MODELS[1])

    def test_model_name_choice_is_accepted(self):
        with patch("img2miro.cli.sys.stdin.isatty", return_value=True), patch(
            "builtins.input", return_value=SUPPORTED_MODELS[2]
        ):
            self.assertEqual(_choose_model(), SUPPORTED_MODELS[2])

    def test_out_of_range_choice_falls_back_to_default(self):
        with patch("img2miro.cli.sys.stdin.isatty", return_value=True), patch(
            "builtins.input", return_value="99"
        ):
            self.assertEqual(_choose_model(), DEFAULT_MODEL)


if __name__ == "__main__":
    unittest.main()
