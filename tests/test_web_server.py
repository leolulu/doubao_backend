import importlib
import json
import sys
import typing
import unittest
from unittest.mock import patch

if not hasattr(typing, "override"):
    typing.override = lambda func: func


class FakeMessageStore:
    def __init__(self) -> None:
        self.messages = [{"role": "user", "content": "stored"}]


class FakeSession:
    def __init__(
        self,
        session_id: str | None,
        provider: str | None,
        model: str | None,
    ) -> None:
        self.id = session_id
        self.provider = provider
        self.model = model
        self.messages = FakeMessageStore()
        self.adjusted_system_messages: list[str] = []
        self.chat_once_calls: list[str] = []
        self.chat_preserving_history_calls: list[str] = []
        self.chat_stream_calls: list[tuple[str, bool, str | None]] = []

    def adjust_system_message(self, system_message: str) -> None:
        self.adjusted_system_messages.append(system_message)

    def chat_once(self, question: str) -> str:
        self.chat_once_calls.append(question)
        return f"once:{question}:{self.provider}"

    def chat_preserving_history(self, message: str) -> str:
        self.chat_preserving_history_calls.append(message)
        return f"preserve:{message}:{self.provider}"

    def chat(
        self,
        question: str,
        *,
        preserve: bool = False,
        system_message: str | None = None,
    ) -> str:
        if system_message:
            self.adjust_system_message(system_message)
        if preserve:
            return self.chat_preserving_history(question)
        return self.chat_once(question)

    def chat_stream(
        self,
        question: str,
        *,
        preserve: bool = False,
        system_message: str | None = None,
    ):
        self.chat_stream_calls.append((question, preserve, system_message))
        if self.provider == "fail-before-chunk":
            raise RuntimeError("failed before chunk")
        yield "stream:"
        if self.provider == "fail-after-chunk":
            raise RuntimeError("failed after chunk")
        yield question

    def snapshot_messages(self):
        return list(self.messages.messages)


class FakeSessionManager:
    def __init__(self) -> None:
        self.pool: dict[str, FakeSession] = {}
        self.requests: list[tuple[str | None, str | None, str | None]] = []

    def get_or_create_session(self, id=None, provider=None, model=None):
        self.requests.append((id, provider, model))
        session_id = id or "generated"
        if session_id not in self.pool:
            self.pool[session_id] = FakeSession(session_id, provider, model)
        return self.pool[session_id]

    def list_sessions(self):
        return list(self.pool.values())


class WebServerTest(unittest.TestCase):
    def load_server_module(self):
        sys.modules.pop("server.web_server", None)
        with patch("models.session_manager.SessionManager", FakeSessionManager):
            module = importlib.import_module("server.web_server")
        self.addCleanup(lambda: sys.modules.pop("server.web_server", None))
        return module

    def parse_sse_events(self, response) -> list[dict]:
        return [
            json.loads(line.removeprefix("data: "))
            for line in response.get_data(as_text=True).splitlines()
            if line.startswith("data: ")
        ]

    def test_post_chat_preserves_history_and_passes_provider(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        response = client.post("/", json={
            "id": "s1",
            "system_message": "system",
            "user_message": "hello",
            "preserve": True,
            "provider": "p1",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "preserve:hello:p1")
        self.assertEqual(web_server.sm.requests, [("s1", "p1", None)])
        session = web_server.sm.pool["s1"]
        self.assertEqual(session.adjusted_system_messages, ["system"])
        self.assertEqual(session.chat_preserving_history_calls, ["hello"])
        self.assertEqual(session.chat_once_calls, [])

    def test_post_chat_passes_provider_and_model(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        response = client.post("/", json={
            "id": "manual",
            "user_message": "hello",
            "provider": "p1",
            "model": "model-1",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            web_server.sm.requests,
            [("manual", "p1", "model-1")],
        )
        session = web_server.sm.pool["manual"]
        self.assertEqual(session.provider, "p1")
        self.assertEqual(session.model, "model-1")

    def test_post_chat_boolean_false_uses_chat_once(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        response = client.post("/", json={
            "id": "s2",
            "user_message": "hello",
            "preserve": False,
            "provider": "p2",
        })

        self.assertEqual(response.status_code, 200)
        session = web_server.sm.pool["s2"]
        self.assertEqual(session.chat_once_calls, ["hello"])
        self.assertEqual(session.chat_preserving_history_calls, [])

    def test_get_chat_accepts_string_preserve(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        response = client.get("/?id=s3&user_message=hello&preserve=yes&provider=p1")

        self.assertEqual(response.status_code, 200)
        session = web_server.sm.pool["s3"]
        self.assertEqual(session.chat_preserving_history_calls, ["hello"])
        self.assertEqual(session.chat_once_calls, [])

    def test_get_chat_without_preserve_uses_chat_once(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        response = client.get("/?id=s2&user_message=hello&provider=p2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "once:hello:p2")
        session = web_server.sm.pool["s2"]
        self.assertEqual(session.chat_once_calls, ["hello"])
        self.assertEqual(session.chat_preserving_history_calls, [])

    def test_get_chat_and_stream_pass_provider_and_model(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        chat_response = client.get(
            "/?id=manual-get&user_message=hello&provider=p1&model=model-1"
        )
        stream_response = client.get(
            "/stream?id=manual-stream&user_message=hello&provider=p1&model=model-1"
        )

        self.assertEqual(chat_response.status_code, 200)
        self.assertEqual(stream_response.status_code, 200)
        self.assertEqual(web_server.sm.requests, [
            ("manual-get", "p1", "model-1"),
            ("manual-stream", "p1", "model-1"),
        ])

    def test_missing_user_message_returns_400(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        response = client.get("/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("user_message", response.get_data(as_text=True))

    def test_post_missing_user_message_returns_400(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        for path in ["/", "/stream"]:
            with self.subTest(path=path):
                response = client.post(path, json={})

                self.assertEqual(response.status_code, 400)
                self.assertIn("user_message", response.get_data(as_text=True))

        self.assertEqual(web_server.sm.requests, [])

    def test_manual_model_parameter_validation_returns_400(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        invalid_payloads = [
            {"user_message": "hello", "model": "model-1"},
            {"user_message": "hello", "provider": "p1", "model": ""},
            {"user_message": "hello", "provider": "p1", "model": "model-1,model-2"},
            {"user_message": "hello", "provider": "p1", "model": 1},
        ]
        for path in ["/", "/stream"]:
            for payload in invalid_payloads:
                with self.subTest(path=path, payload=payload):
                    response = client.post(path, json=payload)
                    self.assertEqual(response.status_code, 400)

        response = client.get("/?user_message=hello&model=model-1")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(web_server.sm.requests, [])

    def test_manual_selection_error_returns_400_before_chat(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        def fail_selection(id=None, provider=None, model=None):
            raise web_server.ManualModelSelectionError("model unavailable")

        web_server.sm.get_or_create_session = fail_selection

        for path in ["/", "/stream"]:
            with self.subTest(path=path):
                response = client.post(path, json={
                    "user_message": "hello",
                    "provider": "p1",
                    "model": "model-1",
                })
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_data(as_text=True), "model unavailable")

    def test_post_requires_json_object(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        for path in ["/", "/stream"]:
            for payload in [[], None, "text"]:
                with self.subTest(path=path, payload=payload):
                    response = client.post(
                        path,
                        data=json.dumps(payload),
                        content_type="application/json",
                    )

                    self.assertEqual(response.status_code, 400)
                    self.assertIn("JSON", response.get_data(as_text=True))

        self.assertEqual(web_server.sm.requests, [])

    def test_inspect_returns_all_session_ids_and_messages(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()
        web_server.sm.get_or_create_session("s1", provider="p1")

        response = client.get("/inspect")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [{
            "id": "s1",
            "messages": [{"role": "user", "content": "stored"}],
        }])

    def test_help_endpoint_lists_provider_and_model_parameters(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        response = client.get("/help")

        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        self.assertIn("provider", content)
        self.assertIn("model", content)

    def test_get_response_allows_cross_origin_access(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        response = client.get("/help", headers={
            "Origin": "http://intranet.example",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "http://intranet.example",
        )

    def test_post_preflight_allows_content_type_header(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        response = client.options("/", headers={
            "Origin": "http://intranet.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "http://intranet.example",
        )
        self.assertIn("POST", response.headers.get("Access-Control-Allow-Methods"))
        self.assertIn(
            "Content-Type",
            response.headers.get("Access-Control-Allow-Headers"),
        )

    def test_post_stream_uses_same_parameters_and_returns_sse(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        response = client.post("/stream", json={
            "id": "s-stream",
            "system_message": "system",
            "user_message": "hello",
            "preserve": True,
            "provider": "p1",
            "model": "model-1",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "text/event-stream; charset=utf-8")
        self.assertEqual(response.headers.get("Cache-Control"), "no-cache")
        self.assertEqual(response.headers.get("X-Accel-Buffering"), "no")
        self.assertEqual(self.parse_sse_events(response), [
            {"type": "session", "id": "s-stream"},
            {"type": "delta", "content": "stream:"},
            {"type": "delta", "content": "hello"},
            {"type": "done", "preserved": True},
        ])
        session = web_server.sm.pool["s-stream"]
        self.assertEqual(web_server.sm.requests, [("s-stream", "p1", "model-1")])
        self.assertEqual(session.chat_stream_calls, [("hello", True, "system")])

    def test_get_stream_returns_generated_session_id(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        response = client.get("/stream?user_message=hello")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.parse_sse_events(response)[0], {
            "type": "session",
            "id": "generated",
        })

    def test_stream_failure_before_first_chunk_returns_502(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        response = client.get(
            "/stream?user_message=hello&provider=fail-before-chunk"
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_data(as_text=True), "模型流式调用失败")

    def test_stream_failure_after_first_chunk_returns_error_event(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        response = client.get(
            "/stream?user_message=hello&provider=fail-after-chunk"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.parse_sse_events(response), [
            {"type": "session", "id": "generated"},
            {"type": "delta", "content": "stream:"},
            {
                "type": "error",
                "code": "upstream_interrupted",
                "message": "模型流式响应中断",
            },
        ])


if __name__ == "__main__":
    unittest.main()
