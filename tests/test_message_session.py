import typing
import unittest

if not hasattr(typing, "override"):
    typing.override = lambda func: func

from api.base_api import BaseApi
from models.message import Message
from models.session_manager import Session, SessionManager


class RecordingClient(BaseApi):
    def __init__(self, response: str = "answer") -> None:
        self.response = response
        self.calls: list[list[dict[str, str]]] = []

    def reason(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.response


class FakeApiFactory:
    def __init__(self) -> None:
        self.clients = {
            None: RecordingClient("default"),
            "p1": RecordingClient("from-p1"),
            "p2": RecordingClient("from-p2"),
        }
        self.requested_providers: list[str | None] = []

    def get_client(self, provider=None):
        self.requested_providers.append(provider)
        return self.clients[provider]


class MessageTest(unittest.TestCase):
    def test_message_jar_combines_system_history_and_current_user_message(self) -> None:
        message = Message("system")
        message.preserve_history("q1", "a1")

        self.assertEqual(message.messages, [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ])
        self.assertEqual(message.generate_messages_jar("q2"), [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ])


class SessionTest(unittest.TestCase):
    def test_chat_once_does_not_preserve_history(self) -> None:
        client = RecordingClient("one-shot")
        session = Session("s1", client, Message("system"))

        result = session.chat_once("hello")

        self.assertEqual(result, "one-shot")
        self.assertEqual(session.messages.messages, [{"role": "system", "content": "system"}])
        self.assertEqual(client.calls[-1], [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
        ])

    def test_chat_preserving_history_clear_and_adjust_system_message(self) -> None:
        client = RecordingClient("preserved-answer")
        session = Session("s1", client, Message("old-system"))

        self.assertEqual(session.chat_preserving_history("hello"), "preserved-answer")
        self.assertEqual(session.messages.messages, [
            {"role": "system", "content": "old-system"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "preserved-answer"},
        ])

        session.adjust_system_message("new-system")
        session.clear_history()

        self.assertEqual(session.messages.messages, [
            {"role": "system", "content": "new-system"},
        ])


class SessionManagerTest(unittest.TestCase):
    def test_new_session_uses_requested_provider_and_stores_session(self) -> None:
        api_factory = FakeApiFactory()
        manager = SessionManager(api_factory=api_factory)

        session = manager.new_session("s1", system_message="system", provider="p1")

        self.assertIs(manager.pool["s1"], session)
        self.assertEqual(api_factory.requested_providers, ["p1"])
        self.assertEqual(session.client, api_factory.clients["p1"])
        self.assertEqual(session.messages.messages, [{"role": "system", "content": "system"}])

    def test_get_or_create_session_reuses_existing_session_and_ignores_later_provider(self) -> None:
        api_factory = FakeApiFactory()
        manager = SessionManager(api_factory=api_factory)

        first = manager.get_or_create_session("s1", provider="p1")
        second = manager.get_or_create_session("s1", provider="p2")

        self.assertIs(first, second)
        self.assertEqual(api_factory.requested_providers, ["p1"])


if __name__ == "__main__":
    unittest.main()
