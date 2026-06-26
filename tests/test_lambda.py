import json
import os
import sys
import unittest
import urllib.error
from datetime import date, timezone, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

# Allow importing from src/ without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lambda_function import (
    find_wordle_completions,
    get_wordle_number,
    lambda_handler,
    log_recent_messages,
    send_reminder,
)


def _make_message(user_id: str, content: str, date_str: str) -> dict:
    """Helper to build a fake Discord message dict."""
    return {
        "id": f"msg_{user_id}",
        "content": content,
        "timestamp": f"{date_str}T12:00:00.000000+00:00",
        "author": {"id": user_id, "username": f"user_{user_id}"},
    }


class TestGetWordleNumber(unittest.TestCase):
    def test_epoch_date(self):
        """Puzzle #0 was on 2021-06-19."""
        self.assertEqual(get_wordle_number(date(2021, 6, 19)), 0)

    def test_known_date(self):
        """Puzzle numbers advance by 1 each day."""
        self.assertEqual(get_wordle_number(date(2021, 6, 20)), 1)
        self.assertEqual(get_wordle_number(date(2021, 6, 26)), 7)

    def test_future_date(self):
        """A date well in the future should return a large puzzle number."""
        result = get_wordle_number(date(2024, 1, 15))
        self.assertGreater(result, 900)


class TestFindWordleCompletions(unittest.TestCase):
    TODAY = "2024-01-15"

    def test_detects_completion_today(self):
        messages = [_make_message("111", "Wordle 934 3/6\n⬜🟨🟩⬜⬜", self.TODAY)]
        completed = find_wordle_completions(messages, date(2024, 1, 15))
        self.assertIn("111", completed)

    def test_ignores_message_from_yesterday(self):
        messages = [_make_message("222", "Wordle 933 4/6\n⬜🟨🟩⬜⬜", "2024-01-14")]
        completed = find_wordle_completions(messages, date(2024, 1, 15))
        self.assertNotIn("222", completed)

    def test_ignores_non_wordle_message(self):
        messages = [_make_message("333", "Hello everyone!", self.TODAY)]
        completed = find_wordle_completions(messages, date(2024, 1, 15))
        self.assertNotIn("333", completed)

    def test_detects_failed_wordle(self):
        """X/6 counts as a Wordle completion (player failed)."""
        messages = [_make_message("444", "Wordle 934 X/6\n⬜🟨🟩⬜⬜", self.TODAY)]
        completed = find_wordle_completions(messages, date(2024, 1, 15))
        self.assertIn("444", completed)

    def test_multiple_users(self):
        messages = [
            _make_message("111", "Wordle 934 3/6", self.TODAY),
            _make_message("222", "Wordle 934 5/6", self.TODAY),
        ]
        completed = find_wordle_completions(messages, date(2024, 1, 15))
        self.assertEqual(completed, {"111", "222"})

    def test_detects_app_share_single_game(self):
        """Discord Wordle app messages like '1 finished game of Wordle' should be detected."""
        messages = [_make_message("555", "JoeTheLandWiltshire was playing\n1 finished game of Wordle", self.TODAY)]
        completed = find_wordle_completions(messages, date(2024, 1, 15))
        self.assertIn("555", completed)

    def test_detects_app_share_multiple_games(self):
        """App messages with 'finished games of Wordle' (plural) should also be detected."""
        messages = [_make_message("666", "SomeUser was playing\n2 finished games of Wordle", self.TODAY)]
        completed = find_wordle_completions(messages, date(2024, 1, 15))
        self.assertIn("666", completed)

    def test_detects_playing_without_finish(self):
        """A 'was playing' message alone (e.g. in-progress share) should suppress the reminder."""
        messages = [_make_message("888", "timbo was playing", self.TODAY)]
        completed = find_wordle_completions(messages, date(2024, 1, 15))
        self.assertIn("888", completed)

    def test_detects_were_playing_group_share(self):
        """'were playing' (plural) group activity shares should suppress the reminder."""
        messages = [_make_message("890", "JoeTheLandWiltshire and SillieA were playing\n2 finished games of Wordle", self.TODAY)]
        completed = find_wordle_completions(messages, date(2024, 1, 15))
        self.assertTrue(len(completed) > 0)

    def test_detects_completion_in_embed(self):
        """Wordle completions hidden inside embed fields should be detected."""
        msg = {
            "id": "embed_msg",
            "content": "",
            "timestamp": f"{self.TODAY}T10:00:00.000000+00:00",
            "author": {},  # no id — simulates app/webhook without author id
            "embeds": [{"description": "timbo was playing\n1 finished game of Wordle"}],
        }
        completed = find_wordle_completions([msg], date(2024, 1, 15))
        self.assertTrue(len(completed) > 0)

    def test_detects_completion_no_author_id(self):
        """When author ID is missing the sentinel is used and reminder is still suppressed."""
        msg = {
            "id": "no_author_msg",
            "content": "SomeUser was playing\n1 finished game of Wordle",
            "timestamp": f"{self.TODAY}T10:00:00.000000+00:00",
            "author": {},  # no id field
            "embeds": [],
        }
        completed = find_wordle_completions([msg], date(2024, 1, 15))
        self.assertTrue(len(completed) > 0)

    def test_ignores_app_share_from_yesterday(self):
        """App-format messages from yesterday should not count."""
        messages = [_make_message("777", "OldUser was playing\n1 finished game of Wordle", "2024-01-14")]
        completed = find_wordle_completions(messages, date(2024, 1, 15))
        self.assertNotIn("777", completed)

    def test_ignores_playing_from_yesterday(self):
        """A 'was playing' message from yesterday should not suppress today's reminder."""
        messages = [_make_message("889", "timbo was playing", "2024-01-14")]
        completed = find_wordle_completions(messages, date(2024, 1, 15))
        self.assertNotIn("889", completed)

    def test_empty_messages(self):
        self.assertEqual(find_wordle_completions([], date(2024, 1, 15)), set())


class TestLambdaHandler(unittest.TestCase):
    ENV = {
        "DISCORD_TOKEN": "test-token",
        "CHANNEL_ID": "99999",
        "USER_IDS": "111,222,333",
    }
    TODAY = date(2024, 1, 15)

    def _make_messages(self, posted_ids):
        date_str = self.TODAY.isoformat()
        return [
            _make_message(uid, "Wordle 934 3/6\n⬜🟨🟩⬜⬜", date_str)
            for uid in posted_ids
        ]

    @patch("lambda_function.datetime")
    @patch("lambda_function.send_reminder")
    @patch("lambda_function.get_recent_messages")
    def test_no_reminder_when_any_user_completed(self, mock_get_msgs, mock_send, mock_dt):
        mock_dt.now.return_value.date.return_value = self.TODAY
        # Any completion means no reminder is sent.
        mock_get_msgs.return_value = self._make_messages(["111"])

        with patch.dict(os.environ, self.ENV):
            result = lambda_handler({}, None)

        mock_send.assert_not_called()
        self.assertEqual(result["statusCode"], 200)
        self.assertIn("No reminder needed", result["body"])

    @patch("lambda_function.datetime")
    @patch("lambda_function.send_reminder")
    @patch("lambda_function.get_recent_messages")
    def test_no_reminder_when_untracked_user_completed(self, mock_get_msgs, mock_send, mock_dt):
        """A completion by a user not in USER_IDS should still suppress the reminder."""
        mock_dt.now.return_value.date.return_value = self.TODAY
        # "999" is not in USER_IDS ("111,222,333")
        mock_get_msgs.return_value = self._make_messages(["999"])

        with patch.dict(os.environ, self.ENV):
            result = lambda_handler({}, None)

        mock_send.assert_not_called()
        self.assertEqual(result["statusCode"], 200)
        self.assertIn("No reminder needed", result["body"])

    @patch("lambda_function.datetime")
    @patch("lambda_function.send_reminder")
    @patch("lambda_function.get_recent_messages")
    def test_no_reminder_when_all_completed(self, mock_get_msgs, mock_send, mock_dt):
        mock_dt.now.return_value.date.return_value = self.TODAY
        mock_get_msgs.return_value = self._make_messages(["111", "222", "333"])

        with patch.dict(os.environ, self.ENV):
            result = lambda_handler({}, None)

        mock_send.assert_not_called()
        self.assertEqual(result["statusCode"], 200)
        self.assertIn("No reminder needed", result["body"])

    @patch("lambda_function.datetime")
    @patch("lambda_function.send_reminder")
    @patch("lambda_function.get_recent_messages")
    def test_all_users_reminded_when_none_posted(self, mock_get_msgs, mock_send, mock_dt):
        mock_dt.now.return_value.date.return_value = self.TODAY
        mock_get_msgs.return_value = []  # no messages at all
        mock_send.return_value = {"id": "msg_new"}

        with patch.dict(os.environ, self.ENV):
            result = lambda_handler({}, None)

        mock_send.assert_called_once()
        reminded_users = mock_send.call_args.args[2]
        self.assertCountEqual(reminded_users, ["111", "222", "333"])
        self.assertEqual(result["statusCode"], 200)

    @patch("lambda_function.datetime")
    @patch("lambda_function.get_recent_messages")
    def test_discord_api_error_propagates(self, mock_get_msgs, mock_dt):
        """Discord API failures should propagate so Lambda marks the invocation as failed."""
        mock_dt.now.return_value.date.return_value = self.TODAY
        mock_get_msgs.side_effect = urllib.error.URLError("Connection refused")

        with patch.dict(os.environ, self.ENV):
            with self.assertRaises(urllib.error.URLError):
                lambda_handler({}, None)


class TestSendReminder(unittest.TestCase):
    @patch("lambda_function.discord_request")
    @patch("lambda_function.random.choice")
    def test_message_format(self, mock_choice, mock_req):
        mock_choice.return_value = "Ping {mentions} for Wordle #{wordle_number}"
        mock_req.return_value = {"id": "new_msg"}
        send_reminder("channel123", "token456", ["111", "222"], 934)

        mock_req.assert_called_once()
        mock_choice.assert_called_once()
        _method, _path, _token, body = mock_req.call_args.args
        self.assertIn("Ping", body["content"])
        self.assertIn("#934", body["content"])
        self.assertIn("<@111>", body["content"])
        self.assertIn("<@222>", body["content"])
        self.assertEqual(body["allowed_mentions"]["users"], ["111", "222"])

    @patch("lambda_function.discord_request")
    def test_allowed_mentions_uses_parse_empty(self, mock_req):
        """parse must be empty so only listed users are pinged."""
        mock_req.return_value = {"id": "new_msg"}
        send_reminder("channel123", "token456", ["999"], 1)
        _method, _path, _token, body = mock_req.call_args.args
        self.assertEqual(body["allowed_mentions"]["parse"], [])


class TestLogRecentMessages(unittest.TestCase):
    def test_logs_up_to_ten_messages(self):
        """log_recent_messages should print one line per message, capped at 10."""
        messages = [_make_message(str(i), f"msg {i}", "2024-01-15") for i in range(15)]
        with patch("builtins.print") as mock_print:
            log_recent_messages(messages)
        # One header line + 10 message lines = 11 print calls
        self.assertEqual(mock_print.call_count, 11)

    def test_logs_fewer_than_ten_when_short(self):
        """When fewer than 10 messages exist, all are logged."""
        messages = [_make_message("1", "hello", "2024-01-15")]
        with patch("builtins.print") as mock_print:
            log_recent_messages(messages)
        self.assertEqual(mock_print.call_count, 2)

    def test_output_contains_valid_json(self):
        """Each message line must contain valid JSON of the original dict."""
        msg = _make_message("42", "Wordle 934 3/6", "2024-01-15")
        with patch("builtins.print") as mock_print:
            log_recent_messages([msg])
        # Second call (index 1) is the message line
        message_line = mock_print.call_args_list[1].args[0]
        # Extract the JSON object starting at the first '{'
        json_str = message_line[message_line.index("{"):]
        parsed = json.loads(json_str)
        self.assertEqual(parsed["author"]["id"], "42")

    def test_logs_empty_list(self):
        """An empty message list should only produce the header line."""
        with patch("builtins.print") as mock_print:
            log_recent_messages([])
        self.assertEqual(mock_print.call_count, 1)


class TestLambdaHandlerDebugFlag(unittest.TestCase):
    ENV = {
        "DISCORD_TOKEN": "test-token",
        "CHANNEL_ID": "99999",
        "USER_IDS": "111,222",
    }
    TODAY = date(2024, 1, 15)

    @patch("lambda_function.datetime")
    @patch("lambda_function.send_reminder")
    @patch("lambda_function.get_recent_messages")
    @patch("lambda_function.log_recent_messages")
    def test_debug_flag_true_calls_log(self, mock_log, mock_get_msgs, mock_send, mock_dt):
        """When DEBUG_MESSAGES=true, log_recent_messages is called."""
        mock_dt.now.return_value.date.return_value = self.TODAY
        mock_get_msgs.return_value = []
        mock_send.return_value = {"id": "msg"}

        with patch.dict(os.environ, {**self.ENV, "DEBUG_MESSAGES": "true"}):
            lambda_handler({}, None)

        mock_log.assert_called_once()

    @patch("lambda_function.datetime")
    @patch("lambda_function.send_reminder")
    @patch("lambda_function.get_recent_messages")
    @patch("lambda_function.log_recent_messages")
    def test_debug_flag_false_skips_log(self, mock_log, mock_get_msgs, mock_send, mock_dt):
        """When DEBUG_MESSAGES is absent or false, log_recent_messages is not called."""
        mock_dt.now.return_value.date.return_value = self.TODAY
        mock_get_msgs.return_value = []
        mock_send.return_value = {"id": "msg"}

        with patch.dict(os.environ, {**self.ENV, "DEBUG_MESSAGES": "false"}):
            lambda_handler({}, None)

        mock_log.assert_not_called()

    @patch("lambda_function.datetime")
    @patch("lambda_function.send_reminder")
    @patch("lambda_function.get_recent_messages")
    @patch("lambda_function.log_recent_messages")
    def test_debug_flag_absent_skips_log(self, mock_log, mock_get_msgs, mock_send, mock_dt):
        """When DEBUG_MESSAGES env var is not set, log_recent_messages is not called."""
        mock_dt.now.return_value.date.return_value = self.TODAY
        mock_get_msgs.return_value = []
        mock_send.return_value = {"id": "msg"}

        env = {k: v for k, v in self.ENV.items()}
        env.pop("DEBUG_MESSAGES", None)
        with patch.dict(os.environ, env, clear=False):
            # Ensure the key isn't present from the outer environment
            os.environ.pop("DEBUG_MESSAGES", None)
            lambda_handler({}, None)

        mock_log.assert_not_called()


class TestLambdaHandlerDebugOnly(unittest.TestCase):
    ENV = {
        "DISCORD_TOKEN": "test-token",
        "CHANNEL_ID": "99999",
        "USER_IDS": "111,222",
    }
    TODAY = date(2024, 1, 15)

    @patch("lambda_function.datetime")
    @patch("lambda_function.send_reminder")
    @patch("lambda_function.get_recent_messages")
    @patch("lambda_function.log_recent_messages")
    def test_debug_only_logs_and_returns_early(self, mock_log, mock_get_msgs, mock_send, mock_dt):
        """debug_only=True should log messages and return without sending a reminder."""
        mock_dt.now.return_value.date.return_value = self.TODAY
        mock_get_msgs.return_value = []

        with patch.dict(os.environ, self.ENV):
            result = lambda_handler({"debug_only": True}, None)

        mock_log.assert_called_once()
        mock_send.assert_not_called()
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["body"], "Debug log complete")

    @patch("lambda_function.datetime")
    @patch("lambda_function.send_reminder")
    @patch("lambda_function.get_recent_messages")
    @patch("lambda_function.log_recent_messages")
    def test_debug_only_false_continues_normally(self, mock_log, mock_get_msgs, mock_send, mock_dt):
        """debug_only=False (or absent) should not skip reminder logic."""
        mock_dt.now.return_value.date.return_value = self.TODAY
        mock_get_msgs.return_value = []
        mock_send.return_value = {"id": "msg"}

        with patch.dict(os.environ, self.ENV):
            result = lambda_handler({"debug_only": False}, None)

        mock_send.assert_called_once()
        self.assertNotEqual(result["body"], "Debug log complete")


if __name__ == "__main__":
    unittest.main()
