import typing
import unittest

if not hasattr(typing, "override"):
    typing.override = lambda func: func

from api.base_api import BaseApi
from api.fallback_api import FallbackApi, FallbackEntry
from api.provider_fallback_api import ProviderFallbackApi, ProviderFallbackEntry
from api.retrying_api import ProviderFallbackEvent


class FailingClient(BaseApi):
    def __init__(self, reason: str) -> None:
        self.reason_text = reason
        self.calls = 0

    def reason(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        raise Exception(self.reason_text)


class SuccessfulClient(BaseApi):
    def __init__(self, response: str = "ok") -> None:
        self.response = response
        self.calls = 0

    def reason(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        return self.response


class PartialStreamingClient(SuccessfulClient):
    def reason_stream(self, messages: list[dict[str, str]]):
        self.calls += 1
        yield "partial"
        raise RuntimeError("stream interrupted")


class ProviderFallbackApiTest(unittest.TestCase):
    def test_reports_success_after_multiple_provider_switches(self) -> None:
        events = []
        first_provider = FallbackApi(
            "p1",
            [
                FallbackEntry("api_key#1:model-a", FailingClient("p1-a"), ("secret-a",)),
                FallbackEntry("api_key#1:model-b", FailingClient("p1-b"), ("secret-a",)),
            ],
            failure_handlers=[],
        )
        third_provider = SuccessfulClient("from-p3")
        unused_provider = SuccessfulClient()
        chain = ProviderFallbackApi(
            [
                ProviderFallbackEntry("p1", first_provider),
                ProviderFallbackEntry("p2", FailingClient("p2-failed")),
                ProviderFallbackEntry("p3", third_provider),
                ProviderFallbackEntry("p4", unused_provider),
            ],
            failure_handlers=[events.append],
        )

        result = chain.reason([{"role": "user", "content": "hello"}])

        self.assertEqual(result, "from-p3")
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], ProviderFallbackEvent)
        self.assertEqual(events[0].providers, ["p1", "p2", "p3"])
        self.assertEqual(events[0].outcome, "success")
        self.assertEqual([str(exc) for exc in events[0].exceptions], ["p1-b", "p2-failed"])
        first_failure = events[0].exceptions[0].fallback_event
        self.assertEqual(first_failure.targets, ["api_key#1:model-a", "api_key#1:model-b"])
        self.assertEqual([str(exc) for exc in first_failure.exceptions], ["p1-a", "p1-b"])
        self.assertEqual(events[0].secret_values, ("secret-a", "secret-a"))
        self.assertEqual(third_provider.calls, 1)
        self.assertEqual(unused_provider.calls, 0)

    def test_all_providers_failed_reports_only_final_failure(self) -> None:
        events = []
        first_provider = FallbackApi(
            "p1",
            [
                FallbackEntry("model-a", FailingClient("p1-a")),
                FallbackEntry("model-b", FailingClient("p1-b")),
            ],
            failure_handlers=[],
        )
        second_provider = FailingClient("p2-failed")
        chain = ProviderFallbackApi(
            [
                ProviderFallbackEntry("p1", first_provider),
                ProviderFallbackEntry("p2", second_provider),
            ],
            failure_handlers=[events.append],
        )

        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                events.clear()
                with self.assertRaisesRegex(Exception, "p2-failed"):
                    if streaming:
                        list(chain.reason_stream([]))
                    else:
                        chain.reason([])

                self.assertEqual([type(event) for event in events], [ProviderFallbackEvent])
                self.assertEqual(events[0].providers, ["p1", "p2"])
                self.assertEqual(events[0].outcome, "failed")
                self.assertEqual([str(exc) for exc in events[0].exceptions], ["p1-b", "p2-failed"])

    def test_returns_without_notification_when_first_provider_succeeds(self) -> None:
        events = []
        first_provider = SuccessfulClient("from-p1")
        second_provider = SuccessfulClient("from-p2")
        chain = ProviderFallbackApi(
            [
                ProviderFallbackEntry("p1", first_provider),
                ProviderFallbackEntry("p2", second_provider),
            ],
            failure_handlers=[events.append],
        )

        result = chain.reason([])

        self.assertEqual(result, "from-p1")
        self.assertEqual(events, [])
        self.assertEqual(first_provider.calls, 1)
        self.assertEqual(second_provider.calls, 0)

    def test_model_fallback_stream_switches_before_visible_content(self) -> None:
        fallback = FallbackApi(
            "p1",
            [
                FallbackEntry("model-a", FailingClient("HTTP 500")),
                FallbackEntry("model-b", SuccessfulClient("from-model-b")),
            ],
            failure_handlers=[],
        )

        self.assertEqual(list(fallback.reason_stream([])), ["from-model-b"])

    def test_provider_stream_reports_success_only_after_completion(self) -> None:
        events = []
        first_provider = FailingClient("HTTP 500")
        second_provider = SuccessfulClient("from-p2")
        chain = ProviderFallbackApi(
            [
                ProviderFallbackEntry("p1", first_provider),
                ProviderFallbackEntry("p2", second_provider),
            ],
            failure_handlers=[events.append],
        )

        stream = chain.reason_stream([])
        self.assertEqual(next(stream), "from-p2")
        self.assertEqual(events, [])
        with self.assertRaises(StopIteration):
            next(stream)

        self.assertEqual([type(event) for event in events], [ProviderFallbackEvent])
        self.assertEqual(events[0].providers, ["p1", "p2"])
        self.assertEqual(events[0].outcome, "success")

    def test_provider_stream_does_not_switch_after_visible_content(self) -> None:
        events = []
        unused_provider = SuccessfulClient()
        chain = ProviderFallbackApi(
            [
                ProviderFallbackEntry("p1", FailingClient("HTTP 500")),
                ProviderFallbackEntry("p2", PartialStreamingClient()),
                ProviderFallbackEntry("p3", unused_provider),
            ],
            failure_handlers=[events.append],
        )

        stream = chain.reason_stream([])
        self.assertEqual(next(stream), "partial")
        self.assertEqual(events, [])
        with self.assertRaisesRegex(RuntimeError, "stream interrupted"):
            next(stream)

        self.assertEqual(unused_provider.calls, 0)
        self.assertEqual([type(event) for event in events], [ProviderFallbackEvent])
        self.assertEqual(events[0].providers, ["p1", "p2"])
        self.assertEqual(events[0].outcome, "interrupted")
        self.assertEqual([str(exc) for exc in events[0].exceptions], ["HTTP 500", "stream interrupted"])

    def test_provider_stream_reports_early_close_after_switch(self) -> None:
        events = []
        chain = ProviderFallbackApi(
            [
                ProviderFallbackEntry("p1", FailingClient("HTTP 500")),
                ProviderFallbackEntry("p2", SuccessfulClient("from-p2")),
            ],
            failure_handlers=[events.append],
        )

        stream = chain.reason_stream([])
        self.assertEqual(next(stream), "from-p2")
        self.assertEqual(events, [])
        stream.close()

        self.assertEqual([type(event) for event in events], [ProviderFallbackEvent])
        self.assertEqual(events[0].providers, ["p1", "p2"])
        self.assertEqual(events[0].outcome, "cancelled")


if __name__ == "__main__":
    unittest.main()
