import typing
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

if not hasattr(typing, "override"):
    typing.override = lambda func: func

from api.chat_completion import ChatCompletion
from api.deepseek import DeepSeek
from api.doubao import Doubao
import api.error_request_logger as error_request_logger
from api.kimi import Kimi
from api.minimax import MiniMax
from api.modelscope import ModelScope
from api.zhipu import Zhipu


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = "error") -> None:
        self.status_code = status_code
        self.payload = payload or {
            "choices": [
                {"message": {"content": "provider-answer"}}
            ]
        }
        self.text = text

    def json(self):
        return self.payload


class OpenAICompatibleProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.error_log_path = Path(self.temp_dir.name) / "llm_error_requests.jsonl"
        self.success_log_path = Path(self.temp_dir.name) / "llm_success_requests.jsonl"
        self.log_path_patcher = patch.object(error_request_logger, "LOG_PATH", self.error_log_path)
        self.success_log_path_patcher = patch.object(
            error_request_logger,
            "SUCCESS_LOG_PATH",
            self.success_log_path,
        )
        self.log_path_patcher.start()
        self.success_log_path_patcher.start()

    def tearDown(self) -> None:
        self.success_log_path_patcher.stop()
        self.log_path_patcher.stop()
        self.temp_dir.cleanup()

    def read_error_log(self):
        return [
            json.loads(line)
            for line in self.error_log_path.read_text(encoding="utf-8").splitlines()
        ]

    def read_success_log(self):
        return [
            json.loads(line)
            for line in self.success_log_path.read_text(encoding="utf-8").splitlines()
        ]

    def test_deepseek_posts_expected_request_and_returns_content(self) -> None:
        calls = []

        def post(url, headers, json):
            calls.append((url, headers, json))
            return FakeResponse(200)

        with patch("api.deepseek.requests.post", side_effect=post):
            result = DeepSeek("key", "deepseek-chat").reason([{"role": "user", "content": "hi"}])

        self.assertEqual(result, "provider-answer")
        self.assertEqual(calls[0][0], "https://api.deepseek.com/chat/completions")
        self.assertEqual(calls[0][1]["Authorization"], "Bearer key")
        self.assertEqual(calls[0][2]["model"], "deepseek-chat")

        records = self.read_success_log()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["provider"], "deepseek")
        self.assertEqual(records[0]["request_body"], {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "hi"}],
        })
        self.assertEqual(records[0]["response_status_code"], 200)
        self.assertEqual(records[0]["response_body"], "error")
        self.assertIsNone(records[0]["exception_type"])
        self.assertNotIn("key", json.dumps(records[0], ensure_ascii=False))

    def test_modelscope_posts_expected_request_and_returns_content(self) -> None:
        calls = []

        def post(url, headers, json):
            calls.append((url, headers, json))
            return FakeResponse(200)

        with patch("api.modelscope.requests.post", side_effect=post):
            result = ModelScope("token", "namespace/model").reason([{"role": "user", "content": "hi"}])

        self.assertEqual(result, "provider-answer")
        self.assertEqual(calls[0][0], "https://api-inference.modelscope.cn/v1/chat/completions")
        self.assertEqual(calls[0][1]["Authorization"], "Bearer token")
        self.assertEqual(calls[0][2]["model"], "namespace/model")

    def test_generic_chat_completion_posts_expected_request_and_returns_content(self) -> None:
        calls = []

        def post(url, headers, json):
            calls.append((url, headers, json))
            return FakeResponse(200)

        with patch("api.chat_completion.requests.post", side_effect=post):
            result = ChatCompletion(
                "https://example.test/v1/",
                "secret-key",
                "namespace/model",
                provider_name="chat_completion:custom",
            ).reason([{"role": "user", "content": "hi"}])

        self.assertEqual(result, "provider-answer")
        self.assertEqual(calls[0][0], "https://example.test/v1/chat/completions")
        self.assertEqual(calls[0][1]["Authorization"], "Bearer secret-key")
        self.assertEqual(calls[0][2], {
            "model": "namespace/model",
            "messages": [{"role": "user", "content": "hi"}],
        })

        records = self.read_success_log()
        self.assertEqual(records[0]["provider"], "chat_completion:custom")
        self.assertEqual(records[0]["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(records[0]["request_body"], {
            "model": "namespace/model",
            "messages": [{"role": "user", "content": "hi"}],
        })
        self.assertEqual(records[0]["response_status_code"], 200)
        self.assertNotIn("secret-key", json.dumps(records[0], ensure_ascii=False))

    def test_zhipu_uses_configured_endpoint_and_temperature(self) -> None:
        calls = []

        def post(url, headers, json):
            calls.append((url, headers, json))
            return FakeResponse(200)

        with patch("api.zhipu.requests.post", side_effect=post):
            result = Zhipu("key", "glm-4.7", use_coding_endpoint=True).reason([
                {"role": "user", "content": "hi"}
            ])

        self.assertEqual(result, "provider-answer")
        self.assertEqual(calls[0][0], "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions")
        self.assertEqual(calls[0][1]["Authorization"], "Bearer key")
        self.assertEqual(calls[0][2]["model"], "glm-4.7")
        self.assertEqual(calls[0][2]["temperature"], 1.0)

    def test_openai_compatible_providers_raise_on_non_200_response(self) -> None:
        with patch("api.deepseek.requests.post", return_value=FakeResponse(500, text="server error")):
            with self.assertRaisesRegex(Exception, "500"):
                DeepSeek("key", "model").reason([])

        records = self.read_error_log()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["provider"], "deepseek")
        self.assertEqual(records[0]["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(records[0]["request_body"], {"model": "model", "messages": []})
        self.assertEqual(records[0]["response_status_code"], 500)
        self.assertEqual(records[0]["response_body"], "server error")
        self.assertNotIn("key", json.dumps(records[0], ensure_ascii=False))
        self.assertFalse(self.success_log_path.exists())

    def test_deepseek_logs_request_exception(self) -> None:
        with patch("api.deepseek.requests.post", side_effect=requests.exceptions.ConnectionError("boom")):
            with self.assertRaisesRegex(requests.exceptions.ConnectionError, "boom"):
                DeepSeek("key", "model").reason([{"role": "user", "content": "hi"}])

        records = self.read_error_log()
        self.assertEqual(records[0]["provider"], "deepseek")
        self.assertEqual(records[0]["request_body"]["messages"][0]["content"], "hi")
        self.assertEqual(records[0]["exception_type"], "ConnectionError")
        self.assertEqual(records[0]["exception_message"], "boom")

    def test_generic_chat_completion_logs_non_200_response(self) -> None:
        with patch("api.chat_completion.requests.post", return_value=FakeResponse(500, text="server error")):
            with self.assertRaisesRegex(Exception, "500"):
                ChatCompletion(
                    "https://example.test/v1",
                    "secret-key",
                    "model",
                    provider_name="chat_completion:custom",
                ).reason([])

        records = self.read_error_log()
        self.assertEqual(records[0]["provider"], "chat_completion:custom")
        self.assertEqual(records[0]["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(records[0]["request_body"], {"model": "model", "messages": []})
        self.assertEqual(records[0]["response_status_code"], 500)
        self.assertEqual(records[0]["response_body"], "server error")
        self.assertNotIn("secret-key", json.dumps(records[0], ensure_ascii=False))

    def test_openai_compatible_providers_delegate_streaming_parameters(self) -> None:
        messages = [{"role": "user", "content": "hi"}]
        cases = [
            (
                "api.deepseek.stream_chat_completion",
                DeepSeek("key", "deepseek-chat"),
                {"provider": "deepseek", "model": "deepseek-chat"},
            ),
            (
                "api.modelscope.stream_chat_completion",
                ModelScope("key", "namespace/model"),
                {"provider": "modelscope", "model": "namespace/model"},
            ),
            (
                "api.zhipu.stream_chat_completion",
                Zhipu("key", "glm-4.7"),
                {"provider": "zhipu", "model": "glm-4.7"},
            ),
            (
                "api.chat_completion.stream_chat_completion",
                ChatCompletion(
                    "https://example.test/v1",
                    "key",
                    "custom-model",
                    provider_name="chat_completion:custom",
                ),
                {"provider": "chat_completion:custom", "model": "custom-model"},
            ),
            (
                "api.minimax.stream_chat_completion",
                MiniMax("key", "MiniMax-M2.5"),
                {"provider": "minimax", "model": "MiniMax-M2.5"},
            ),
        ]

        for patch_path, client, expected in cases:
            with self.subTest(provider=expected["provider"]):
                with patch(patch_path, return_value=iter(["chunk"])) as stream:
                    self.assertEqual(list(client.reason_stream(messages)), ["chunk"])

                kwargs = stream.call_args.kwargs
                self.assertEqual(kwargs["provider"], expected["provider"])
                self.assertEqual(kwargs["request_body"]["model"], expected["model"])
                self.assertEqual(kwargs["request_body"]["messages"], messages)

        with patch(
            "api.minimax.stream_chat_completion",
            return_value=iter(["chunk"]),
        ) as stream:
            list(MiniMax("key", "MiniMax-M2.5").reason_stream(messages))
        self.assertTrue(stream.call_args.kwargs["cumulative_content"])
        self.assertTrue(stream.call_args.kwargs["request_body"]["reasoning_split"])


class KimiProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.error_log_path = Path(self.temp_dir.name) / "llm_error_requests.jsonl"
        self.success_log_path = Path(self.temp_dir.name) / "llm_success_requests.jsonl"
        self.log_path_patcher = patch.object(error_request_logger, "LOG_PATH", self.error_log_path)
        self.success_log_path_patcher = patch.object(
            error_request_logger,
            "SUCCESS_LOG_PATH",
            self.success_log_path,
        )
        self.log_path_patcher.start()
        self.success_log_path_patcher.start()

    def tearDown(self) -> None:
        self.success_log_path_patcher.stop()
        self.log_path_patcher.stop()
        self.temp_dir.cleanup()

    def test_kimi_uses_anthropic_protocol_by_default(self) -> None:
        calls = []

        def post(url, headers, json):
            calls.append((url, headers, json))
            return FakeResponse(200, payload={
                "content": [
                    {"type": "text", "text": "kimi-answer"}
                ]
            })

        with patch("api.kimi.requests.post", side_effect=post):
            result = Kimi("key").reason([
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "hi"},
            ])

        self.assertEqual(result, "kimi-answer")
        self.assertEqual(calls[0][0], "https://api.kimi.com/coding/v1/messages")
        self.assertEqual(calls[0][1]["x-api-key"], "key")
        self.assertEqual(calls[0][1]["anthropic-version"], "2023-06-01")
        self.assertEqual(calls[0][1]["User-Agent"], "claude-code/0.1.0")
        self.assertEqual(calls[0][2]["model"], "kimi-k2.6")
        self.assertEqual(calls[0][2]["max_tokens"], 32768)
        self.assertEqual(calls[0][2]["system"], "system prompt")
        self.assertEqual(calls[0][2]["messages"], [
            {"role": "user", "content": "hi"},
        ])

    def test_kimi_openai_protocol_uses_openai_shape_and_user_agent(self) -> None:
        calls = []

        def post(url, headers, json):
            calls.append((url, headers, json))
            return FakeResponse(200)

        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hi"},
        ]

        with patch("api.kimi.requests.post", side_effect=post):
            result = Kimi("key", "kimi-k2.6", protocol="openai").reason(messages)

        self.assertEqual(result, "provider-answer")
        self.assertEqual(calls[0][0], "https://api.kimi.com/coding/v1/chat/completions")
        self.assertEqual(calls[0][1]["Authorization"], "Bearer key")
        self.assertEqual(calls[0][1]["User-Agent"], "claude-code/0.1.0")
        self.assertEqual(calls[0][2]["model"], "kimi-k2.6")
        self.assertEqual(calls[0][2]["messages"], messages)

    def test_kimi_openai_protocol_raises_when_reasoning_exhausts_max_tokens(self) -> None:
        response = FakeResponse(200, payload={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "thinking",
                    },
                    "finish_reason": "length",
                }
            ]
        })

        with patch("api.kimi.requests.post", return_value=response):
            with self.assertRaisesRegex(Exception, "max_tokens"):
                Kimi("key", protocol="openai", max_tokens=16).reason([
                    {"role": "user", "content": "hi"}
                ])

        records = [
            json.loads(line)
            for line in self.error_log_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(records[0]["provider"], "kimi")
        self.assertIn("max_tokens", records[0]["exception_message"])
        self.assertFalse(self.success_log_path.exists())

    def test_kimi_config_only_exposes_api_key_and_model(self) -> None:
        self.assertEqual(
            [param.to_config_key() for param in Kimi.get_params()],
            ["API_KEY", "MODEL"],
        )

    def test_kimi_rejects_unsupported_protocol_at_construction(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported Kimi protocol"):
            Kimi("key", protocol="bad")

    def test_kimi_streams_with_openai_and_anthropic_protocols(self) -> None:
        messages = [{"role": "user", "content": "hi"}]

        with patch(
            "api.kimi.stream_chat_completion",
            return_value=iter(["openai"]),
        ) as openai_stream:
            result = list(Kimi("key", protocol="openai").reason_stream(messages))

        self.assertEqual(result, ["openai"])
        self.assertEqual(openai_stream.call_args.kwargs["protocol"], "openai")
        self.assertEqual(
            openai_stream.call_args.kwargs["request_body"]["messages"],
            messages,
        )

        with patch(
            "api.kimi.stream_chat_completion",
            return_value=iter(["anthropic"]),
        ) as anthropic_stream:
            result = list(Kimi("key").reason_stream(messages))

        self.assertEqual(result, ["anthropic"])
        self.assertEqual(anthropic_stream.call_args.kwargs["protocol"], "anthropic")


class FakeArkCompletionMessage:
    content = "doubao-answer"


class FakeArkCompletionChoice:
    message = FakeArkCompletionMessage()


class FakeArkCompletion:
    choices = [FakeArkCompletionChoice()]


class FakeArkStreamDelta:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeArkStreamChoice:
    def __init__(self, content: str, finish_reason=None) -> None:
        self.delta = FakeArkStreamDelta(content)
        self.finish_reason = finish_reason


class FakeArkStreamChunk:
    def __init__(self, content: str, finish_reason=None) -> None:
        self.choices = [FakeArkStreamChoice(content, finish_reason)]


class FakeArkStream:
    def __init__(self) -> None:
        self.closed = False

    def __iter__(self):
        yield FakeArkStreamChunk("doubao-")
        yield FakeArkStreamChunk("stream", finish_reason="stop")

    def close(self) -> None:
        self.closed = True


class FakeArkCompletions:
    def __init__(self, calls) -> None:
        self.calls = calls

    def create(self, model, messages, stream=False):
        if stream:
            self.calls.append((model, messages, stream))
            return FakeArkStream()
        self.calls.append((model, messages))
        return FakeArkCompletion()


class FakeArkChat:
    def __init__(self, calls) -> None:
        self.completions = FakeArkCompletions(calls)


class FakeArk:
    calls = []
    init_keys = []

    def __init__(self, api_key: str) -> None:
        self.init_keys.append(api_key)
        self.chat = FakeArkChat(self.calls)


class DoubaoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.error_log_path = Path(self.temp_dir.name) / "llm_error_requests.jsonl"
        self.success_log_path = Path(self.temp_dir.name) / "llm_success_requests.jsonl"
        self.log_path_patcher = patch.object(error_request_logger, "LOG_PATH", self.error_log_path)
        self.success_log_path_patcher = patch.object(
            error_request_logger,
            "SUCCESS_LOG_PATH",
            self.success_log_path,
        )
        self.log_path_patcher.start()
        self.success_log_path_patcher.start()

    def tearDown(self) -> None:
        self.success_log_path_patcher.stop()
        self.log_path_patcher.stop()
        self.temp_dir.cleanup()

    def test_doubao_uses_access_point_as_model(self) -> None:
        FakeArk.calls = []
        FakeArk.init_keys = []
        messages = [{"role": "user", "content": "hi"}]

        with patch("api.doubao.Ark", FakeArk):
            result = Doubao("key", "ep-1").reason(messages)

        self.assertEqual(result, "doubao-answer")
        self.assertEqual(FakeArk.init_keys, ["key"])
        self.assertEqual(FakeArk.calls, [("ep-1", messages)])

        records = [
            json.loads(line)
            for line in self.success_log_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(records[0]["provider"], "doubao")
        self.assertEqual(records[0]["request_body"], {
            "model": "ep-1",
            "messages": messages,
        })
        self.assertIsNone(records[0]["response_status_code"])
        self.assertEqual(records[0]["response_body"], "doubao-answer")

    def test_doubao_logs_sdk_exception(self) -> None:
        class FailingArkCompletions:
            def create(self, model, messages):
                raise RuntimeError("ark failed")

        class FailingArkChat:
            completions = FailingArkCompletions()

        class FailingArk:
            def __init__(self, api_key: str) -> None:
                self.chat = FailingArkChat()

        messages = [{"role": "user", "content": "hi"}]

        with patch("api.doubao.Ark", FailingArk):
            with self.assertRaisesRegex(RuntimeError, "ark failed"):
                Doubao("key", "ep-1").reason(messages)

        records = [
            json.loads(line)
            for line in self.error_log_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(records[0]["provider"], "doubao")
        self.assertEqual(records[0]["url"], "ark://chat/completions")
        self.assertEqual(records[0]["request_body"], {
            "model": "ep-1",
            "messages": messages,
        })
        self.assertEqual(records[0]["exception_type"], "RuntimeError")
        self.assertFalse(self.success_log_path.exists())

    def test_doubao_streams_sdk_chunks(self) -> None:
        FakeArk.calls = []
        messages = [{"role": "user", "content": "hi"}]

        with patch("api.doubao.Ark", FakeArk):
            result = list(Doubao("key", "ep-1").reason_stream(messages))

        self.assertEqual(result, ["doubao-", "stream"])
        self.assertEqual(FakeArk.calls, [("ep-1", messages, True)])
        records = [
            json.loads(line)
            for line in self.success_log_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(records[0]["response_body"], "doubao-stream")
        self.assertTrue(records[0]["request_body"]["stream"])


if __name__ == "__main__":
    unittest.main()
