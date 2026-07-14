import importlib
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
    def __init__(self, session_id: str | None, provider: str | None) -> None:
        self.id = session_id
        self.provider = provider
        self.messages = FakeMessageStore()
        self.adjusted_system_messages: list[str] = []
        self.chat_once_calls: list[str] = []
        self.chat_preserving_history_calls: list[str] = []

    def adjust_system_message(self, system_message: str) -> None:
        self.adjusted_system_messages.append(system_message)

    def chat_once(self, question: str) -> str:
        self.chat_once_calls.append(question)
        return f"once:{question}:{self.provider}"

    def chat_preserving_history(self, message: str) -> str:
        self.chat_preserving_history_calls.append(message)
        return f"preserve:{message}:{self.provider}"


class FakeSessionManager:
    def __init__(self) -> None:
        self.pool: dict[str, FakeSession] = {}
        self.requests: list[tuple[str | None, str | None]] = []

    def get_or_create_session(self, id=None, provider=None):
        self.requests.append((id, provider))
        session_id = id or "generated"
        if session_id not in self.pool:
            self.pool[session_id] = FakeSession(session_id, provider)
        return self.pool[session_id]


class WebServerTest(unittest.TestCase):
    def load_server_module(self):
        sys.modules.pop("server.web_server", None)
        with patch("models.session_manager.SessionManager", FakeSessionManager):
            module = importlib.import_module("server.web_server")
        self.addCleanup(lambda: sys.modules.pop("server.web_server", None))
        return module

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
        self.assertEqual(web_server.sm.requests, [("s1", "p1")])
        session = web_server.sm.pool["s1"]
        self.assertEqual(session.adjusted_system_messages, ["system"])
        self.assertEqual(session.chat_preserving_history_calls, ["hello"])
        self.assertEqual(session.chat_once_calls, [])

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

    def test_missing_user_message_returns_400(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        response = client.get("/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("user_message", response.get_data(as_text=True))

    def test_inspect_returns_all_session_messages(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()
        web_server.sm.get_or_create_session("s1", provider="p1")

        response = client.get("/inspect")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [[{"role": "user", "content": "stored"}]])

    def test_help_endpoint_lists_provider_parameter(self) -> None:
        web_server = self.load_server_module()
        client = web_server.app.test_client()

        response = client.get("/help")

        self.assertEqual(response.status_code, 200)
        self.assertIn("provider", response.get_data(as_text=True))

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


if __name__ == "__main__":
    unittest.main()
