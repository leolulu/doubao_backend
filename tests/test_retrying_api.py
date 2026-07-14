import typing
import unittest

if not hasattr(typing, "override"):
    typing.override = lambda func: func

import requests

from api.base_api import BaseApi
from api.retrying_api import (
    FailureEvent,
    FeishuNotifier,
    FallbackEvent,
    RetryingApi,
    RetryEvent,
)
from api.streaming import IncompleteStreamError


class SequenceClient(BaseApi):
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def reason(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return str(outcome)


class StreamingSequenceClient(SequenceClient):
    def reason_stream(self, messages: list[dict[str, str]]):
        self.calls += 1
        outcomes = self.outcomes.pop(0)
        if isinstance(outcomes, Exception):
            raise outcomes
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                raise outcome
            yield str(outcome)


class FakeResponse:
    def __init__(self, payload: object = None, status_code: int = 200) -> None:
        self.payload = {"code": 0} if payload is None else payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.exceptions.HTTPError(response=response)

    def json(self) -> object:
        return self.payload


class RetryingApiTest(unittest.TestCase):
    def test_retries_retryable_exception_until_success(self) -> None:
        events = []
        sleeps = []
        client = SequenceClient([Exception("HTTP 500"), Exception("HTTP 502"), "ok"])
        retrying = RetryingApi(
            "provider",
            client,
            max_retries=2,
            retry_delay_seconds=0.25,
            failure_handlers=[events.append],
            sleeper=sleeps.append,
        )

        result = retrying.reason([])

        self.assertEqual(result, "ok")
        self.assertEqual(client.calls, 3)
        self.assertEqual(sleeps, [0.25, 0.25])
        self.assertEqual([event.will_retry for event in events], [True, True])
        self.assertEqual([event.attempt_number for event in events], [1, 2])

    def test_non_retryable_exception_fails_without_sleep(self) -> None:
        events = []
        sleeps = []
        client = SequenceClient([Exception("HTTP 401")])
        retrying = RetryingApi(
            "provider",
            client,
            max_retries=3,
            failure_handlers=[events.append],
            sleeper=sleeps.append,
        )

        with self.assertRaisesRegex(Exception, "HTTP 401"):
            retrying.reason([])

        self.assertEqual(client.calls, 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], RetryEvent)
        self.assertFalse(events[0].will_retry)

    def test_retryable_exception_reports_final_failure_after_retries(self) -> None:
        events = []
        client = SequenceClient([requests.exceptions.Timeout(), requests.exceptions.Timeout()])
        retrying = RetryingApi(
            "provider",
            client,
            max_retries=1,
            failure_handlers=[events.append],
            sleeper=lambda delay: None,
        )

        with self.assertRaises(requests.exceptions.Timeout):
            retrying.reason([])

        self.assertEqual([event.will_retry for event in events], [True, False])
        self.assertEqual([event.attempt_number for event in events], [1, 2])

    def test_stream_retries_before_first_visible_chunk(self) -> None:
        events = []
        client = StreamingSequenceClient([
            requests.exceptions.Timeout(),
            ["ok"],
        ])
        retrying = RetryingApi(
            "provider",
            client,
            max_retries=1,
            retry_delay_seconds=0,
            failure_handlers=[events.append],
        )

        self.assertEqual(list(retrying.reason_stream([])), ["ok"])
        self.assertEqual(client.calls, 2)
        self.assertEqual([event.will_retry for event in events], [True])

    def test_stream_retries_incomplete_response_before_content(self) -> None:
        client = StreamingSequenceClient([
            IncompleteStreamError("incomplete"),
            ["ok"],
        ])
        retrying = RetryingApi(
            "provider",
            client,
            max_retries=1,
            retry_delay_seconds=0,
        )

        self.assertEqual(list(retrying.reason_stream([])), ["ok"])
        self.assertEqual(client.calls, 2)

    def test_stream_does_not_retry_after_visible_chunk(self) -> None:
        events = []
        client = StreamingSequenceClient([
            ["partial", requests.exceptions.Timeout()],
            ["second-attempt"],
        ])
        retrying = RetryingApi(
            "provider",
            client,
            max_retries=1,
            retry_delay_seconds=0,
            failure_handlers=[events.append],
        )

        stream = retrying.reason_stream([])
        self.assertEqual(next(stream), "partial")
        with self.assertRaises(requests.exceptions.Timeout):
            next(stream)

        self.assertEqual(client.calls, 1)
        self.assertEqual([event.will_retry for event in events], [False])


class FeishuNotifierTest(unittest.TestCase):
    def test_notify_failure_ignores_retry_events_that_will_retry(self) -> None:
        calls = []
        notifier = FeishuNotifier(
            "https://open.feishu.cn/open-apis/bot/v2/hook/test",
            post_request=lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        event = RetryEvent(
            provider_name="provider",
            will_retry=True,
            attempt_number=1,
            max_retries=3,
            delay_seconds=1,
            exception=Exception("temporary"),
        )

        notifier.notify_failure(event)

        self.assertEqual(calls, [])

    def test_notify_failure_sends_redacted_fallback_message(self) -> None:
        calls = []

        def post_request(*args, **kwargs):
            calls.append((args, kwargs))
            return FakeResponse()

        notifier = FeishuNotifier(
            "https://open.feishu.cn/open-apis/bot/v2/hook/test",
            post_request=post_request,
        )
        event = FallbackEvent(
            provider_name="provider",
            will_retry=False,
            targets=["model-a"],
            exceptions=[Exception("failed with secret-token")],
            secret_values=("secret-token",),
        )

        notifier.notify_failure(event)

        self.assertEqual(len(calls), 1)
        message_text = calls[0][1]["json"]["content"]["text"]
        self.assertIn("[redacted]", message_text)
        self.assertNotIn("secret-token", message_text)

    def test_notify_failure_rejects_bad_webhook_and_unsupported_event(self) -> None:
        with self.assertRaises(ValueError):
            FeishuNotifier("https://example.com/hook/test")

        notifier = FeishuNotifier(
            "https://open.feishu.cn/open-apis/bot/v2/hook/test",
            post_request=lambda *args, **kwargs: FakeResponse({"code": 1, "msg": "bad"}),
        )
        event = FailureEvent(provider_name="provider", will_retry=False)

        with self.assertRaises(TypeError):
            notifier.notify_failure(event)

    def test_notify_failure_raises_when_feishu_returns_error_code(self) -> None:
        notifier = FeishuNotifier(
            "https://open.feishu.cn/open-apis/bot/v2/hook/test",
            post_request=lambda *args, **kwargs: FakeResponse({"code": 1, "msg": "bad"}),
        )
        event = RetryEvent(
            provider_name="provider",
            will_retry=False,
            attempt_number=1,
            max_retries=0,
            delay_seconds=0,
            exception=Exception("failed"),
        )

        with self.assertRaisesRegex(RuntimeError, "1"):
            notifier.notify_failure(event)


if __name__ == "__main__":
    unittest.main()
