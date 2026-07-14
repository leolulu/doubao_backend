import typing
import unittest
from threading import Event, Lock, Thread

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


class StreamingClient(RecordingClient):
    def __init__(self, chunks: list[object]) -> None:
        super().__init__()
        self.chunks = chunks

    def reason_stream(self, messages: list[dict[str, str]]):
        self.calls.append(messages)
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield str(chunk)


class CoordinatedStreamingClient(RecordingClient):
    def __init__(self) -> None:
        super().__init__()
        self.call_lock = Lock()
        self.first_started = Event()
        self.release_first = Event()
        self.second_started = Event()
        self.call_count = 0

    def reason_stream(self, messages: list[dict[str, str]]):
        with self.call_lock:
            self.call_count += 1
            call_number = self.call_count
        if call_number == 1:
            self.first_started.set()
            self.release_first.wait(timeout=2)
        else:
            self.second_started.set()
        yield f"answer-{call_number}"


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

    def test_stream_preserves_only_after_complete_response(self) -> None:
        client = StreamingClient(["hel", "lo"])
        session = Session("s1", client, Message("system"))

        self.assertEqual(
            list(session.chat_stream("question", preserve=True)),
            ["hel", "lo"],
        )
        self.assertEqual(session.messages.messages, [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "hello"},
        ])

    def test_stream_failure_does_not_preserve_partial_response(self) -> None:
        client = StreamingClient(["partial", RuntimeError("interrupted")])
        session = Session("s1", client, Message())

        stream = session.chat_stream("question", preserve=True)
        self.assertEqual(next(stream), "partial")
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            next(stream)

        self.assertEqual(session.messages.messages, [])

    def test_closing_stream_does_not_preserve_partial_response(self) -> None:
        client = StreamingClient(["partial", "remaining"])
        session = Session("s1", client, Message())

        stream = session.chat_stream("question", preserve=True)
        self.assertEqual(next(stream), "partial")
        stream.close()

        self.assertEqual(session.messages.messages, [])

    def test_same_session_requests_are_serialized(self) -> None:
        client = CoordinatedStreamingClient()
        session = Session("s1", client, Message())
        results: list[list[str]] = []

        first = Thread(target=lambda: results.append(list(session.chat_stream("first"))))
        second = Thread(target=lambda: results.append(list(session.chat_stream("second"))))
        first.start()
        self.assertTrue(client.first_started.wait(timeout=1))
        second.start()

        self.assertFalse(client.second_started.wait(timeout=0.1))
        client.release_first.set()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertTrue(client.second_started.is_set())
        self.assertEqual(results, [["answer-1"], ["answer-2"]])


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
