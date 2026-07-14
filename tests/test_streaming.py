import json
import unittest
from unittest.mock import patch

from api.streaming import (
    iter_anthropic_content,
    iter_openai_content,
    iter_sse_data,
    stream_chat_completion,
)


class FakeStreamingResponse:
    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self.lines = lines
        self.status_code = status_code
        self.text = "error body"
        self.encoding = None
        self.closed = False

    def iter_lines(self, chunk_size=1, decode_unicode=False):
        self.chunk_size = chunk_size
        self.decode_unicode = decode_unicode
        yield from self.lines

    def close(self) -> None:
        self.closed = True


def sse_payload(payload: object) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}"


class StreamingParserTest(unittest.TestCase):
    def test_iter_sse_data_handles_comments_and_multiline_events(self) -> None:
        response = FakeStreamingResponse([
            ": ping",
            "data: first",
            "data: second",
            "",
            "event: ignored",
            "data: last",
        ])

        self.assertEqual(list(iter_sse_data(response)), ["first\nsecond", "last"])
        self.assertEqual(response.encoding, "utf-8")
        self.assertEqual(response.chunk_size, 1)
        self.assertTrue(response.decode_unicode)

    def test_openai_parser_ignores_reasoning_and_usage_chunks(self) -> None:
        response = FakeStreamingResponse([
            sse_payload({
                "choices": [{"delta": {"reasoning_content": "private"}}],
            }),
            "",
            sse_payload({"choices": [{"delta": {"content": "你"}}]}),
            "",
            sse_payload({"choices": []}),
            "",
            "data: [DONE]",
            "",
        ])

        self.assertEqual(list(iter_openai_content(response)), ["你"])

    def test_openai_parser_normalizes_cumulative_content(self) -> None:
        response = FakeStreamingResponse([
            sse_payload({"choices": [{"delta": {"content": "你"}}]}),
            "",
            sse_payload({"choices": [{"delta": {"content": "你好"}}]}),
            "",
            sse_payload({"choices": [{"delta": {"content": "！"}}]}),
            "",
            "data: [DONE]",
            "",
        ])

        self.assertEqual(
            list(iter_openai_content(response, cumulative_content=True)),
            ["你", "好", "！"],
        )

    def test_anthropic_parser_returns_only_text_deltas(self) -> None:
        response = FakeStreamingResponse([
            sse_payload({
                "type": "content_block_delta",
                "delta": {"type": "thinking_delta", "thinking": "private"},
            }),
            "",
            sse_payload({
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "hello"},
            }),
            "",
            sse_payload({"type": "message_stop"}),
            "",
        ])

        self.assertEqual(list(iter_anthropic_content(response)), ["hello"])

    def test_openai_parser_rejects_error_event_and_incomplete_stream(self) -> None:
        error_response = FakeStreamingResponse([
            sse_payload({"error": {"message": "failed"}}),
            "",
        ])
        with self.assertRaisesRegex(RuntimeError, "上游流式响应错误"):
            list(iter_openai_content(error_response))

        incomplete_response = FakeStreamingResponse([
            sse_payload({"choices": [{"delta": {"content": "partial"}}]}),
            "",
        ])
        stream = iter_openai_content(incomplete_response)
        self.assertEqual(next(stream), "partial")
        with self.assertRaisesRegex(RuntimeError, "完成标记前结束"):
            next(stream)

    def test_anthropic_parser_rejects_error_event_and_incomplete_stream(self) -> None:
        error_response = FakeStreamingResponse([
            sse_payload({"type": "error", "error": {"message": "failed"}}),
            "",
        ])
        with self.assertRaisesRegex(RuntimeError, "上游流式响应错误"):
            list(iter_anthropic_content(error_response))

        incomplete_response = FakeStreamingResponse([
            sse_payload({
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "partial"},
            }),
            "",
        ])
        stream = iter_anthropic_content(incomplete_response)
        self.assertEqual(next(stream), "partial")
        with self.assertRaisesRegex(RuntimeError, "message_stop 前结束"):
            next(stream)

    def test_stream_request_sets_stream_closes_and_logs_visible_answer(self) -> None:
        response = FakeStreamingResponse([
            sse_payload({"choices": [{"delta": {"content": "a"}}]}),
            "",
            sse_payload({"choices": [{"delta": {"content": "b"}}]}),
            "",
            "data: [DONE]",
            "",
        ])

        with (
            patch("api.streaming.requests.post", return_value=response) as post,
            patch("api.streaming.log_llm_success_request") as log_success,
        ):
            result = list(stream_chat_completion(
                provider="provider",
                url="https://example.test/chat/completions",
                headers={"Authorization": "Bearer key"},
                request_body={"model": "model", "messages": []},
                error_prefix="failed",
            ))

        self.assertEqual(result, ["a", "b"])
        self.assertTrue(response.closed)
        self.assertTrue(post.call_args.kwargs["stream"])
        self.assertTrue(post.call_args.kwargs["json"]["stream"])
        self.assertEqual(log_success.call_args.kwargs["response_body"], "ab")


if __name__ == "__main__":
    unittest.main()
