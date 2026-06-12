import typing
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

if not hasattr(typing, "override"):
    typing.override = lambda func: func

import api.error_request_logger as error_request_logger
from api.minimax import MiniMax


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = "error") -> None:
        self.status_code = status_code
        self.payload = payload or {"ok": True}
        self.text = text

    def json(self):
        return self.payload


class MiniMaxTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temp_dir.name) / "llm_error_requests.jsonl"
        self.log_path_patcher = patch.object(error_request_logger, "LOG_PATH", self.log_path)
        self.log_path_patcher.start()

    def tearDown(self) -> None:
        self.log_path_patcher.stop()
        self.temp_dir.cleanup()

    def test_strip_think_tags_removes_reasoning_blocks(self) -> None:
        content = "before <think>hidden reasoning</think> after"

        self.assertEqual(MiniMax._strip_think_tags(content), "before  after")

    def test_reason_returns_cleaned_content_and_preserves_last_raw_content(self) -> None:
        client = MiniMax("key", "model")
        client._call_api = lambda messages, reasoning_split=True: {
            "choices": [
                {"message": {"content": "<think>private</think>visible"}}
            ]
        }

        result = client.reason([{"role": "user", "content": "hello"}])

        self.assertEqual(result, "visible")
        self.assertEqual(client._last_raw_content, "<think>private</think>visible")

    def test_reason_with_raw_response_returns_raw_and_cleaned_content(self) -> None:
        client = MiniMax("key", "model")
        client._call_api = lambda messages, reasoning_split=True: {
            "choices": [
                {"message": {"content": "answer <think>private</think> done"}}
            ]
        }

        raw, cleaned = client.reason_with_raw_response([])

        self.assertEqual(raw, "answer <think>private</think> done")
        self.assertEqual(cleaned, "answer  done")

    def test_call_api_posts_expected_request(self) -> None:
        calls = []

        def post(url, headers, json):
            calls.append((url, headers, json))
            return FakeResponse(200, {"choices": []})

        client = MiniMax("key", "MiniMax-M2.5")

        with patch("api.minimax.requests.post", side_effect=post):
            result = client._call_api([{"role": "user", "content": "hello"}], reasoning_split=False)

        self.assertEqual(result, {"choices": []})
        self.assertEqual(calls[0][0], "https://api.minimaxi.com/v1/chat/completions")
        self.assertEqual(calls[0][1]["Authorization"], "Bearer key")
        self.assertEqual(calls[0][2]["model"], "MiniMax-M2.5")
        self.assertEqual(calls[0][2]["reasoning_split"], False)

    def test_call_api_raises_on_non_200_response(self) -> None:
        client = MiniMax("key", "model")

        with patch("api.minimax.requests.post", return_value=FakeResponse(500, text="server error")):
            with self.assertRaisesRegex(Exception, "500"):
                client._call_api([])

        records = [
            json.loads(line)
            for line in self.log_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(records[0]["provider"], "minimax")
        self.assertEqual(records[0]["request_body"], {
            "model": "model",
            "messages": [],
            "reasoning_split": True,
        })
        self.assertEqual(records[0]["response_body"], "server error")
        self.assertNotIn("key", json.dumps(records[0], ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
