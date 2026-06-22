import json
import os
import sys
import unittest
import urllib.error
from datetime import date, timezone, datetime
from unittest.mock import MagicMock, patch

# Allow importing from src/ without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lambda_function import (
    find_wordle_completions,
    get_wordle_number,
    lambda_handler,
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


if __name__ == "__main__":
    unittest.main()
