import typing
import unittest
from unittest.mock import patch

if not hasattr(typing, "override"):
    typing.override = lambda func: func

from api.deepseek import DeepSeek
from api.doubao import Doubao
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


class FakeArkCompletionMessage:
    content = "doubao-answer"


class FakeArkCompletionChoice:
    message = FakeArkCompletionMessage()


class FakeArkCompletion:
    choices = [FakeArkCompletionChoice()]


class FakeArkCompletions:
    def __init__(self, calls) -> None:
        self.calls = calls

    def create(self, model, messages):
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
    def test_doubao_uses_access_point_as_model(self) -> None:
        FakeArk.calls = []
        FakeArk.init_keys = []
        messages = [{"role": "user", "content": "hi"}]

        with patch("api.doubao.Ark", FakeArk):
            result = Doubao("key", "ep-1").reason(messages)

        self.assertEqual(result, "doubao-answer")
        self.assertEqual(FakeArk.init_keys, ["key"])
        self.assertEqual(FakeArk.calls, [("ep-1", messages)])


if __name__ == "__main__":
    unittest.main()
