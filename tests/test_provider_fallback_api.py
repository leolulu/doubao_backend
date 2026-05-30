import typing
import unittest

if not hasattr(typing, "override"):
    typing.override = lambda func: func

from api.base_api import BaseApi
from api.fallback_api import FallbackApi, FallbackEntry
from api.provider_fallback_api import ProviderFallbackApi, ProviderFallbackEntry
from api.retrying_api import ProviderFallbackEvent, ProviderSwitchEvent


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


class ProviderFallbackApiTest(unittest.TestCase):
    def test_switches_provider_and_reports_failed_inner_targets(self) -> None:
        events = []
        first_provider = FallbackApi(
            "p1",
            [
                FallbackEntry("api_key#1:model-a", FailingClient("p1-a"), ("secret-a",)),
                FallbackEntry("api_key#1:model-b", FailingClient("p1-b"), ("secret-a",)),
            ],
            failure_handlers=[],
        )
        second_provider = SuccessfulClient("from-p2")
        chain = ProviderFallbackApi(
            [
                ProviderFallbackEntry("p1", first_provider),
                ProviderFallbackEntry("p2", second_provider),
            ],
            failure_handlers=[events.append],
        )

        result = chain.reason([{"role": "user", "content": "hello"}])

        self.assertEqual(result, "from-p2")
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], ProviderSwitchEvent)
        self.assertEqual(events[0].from_provider, "p1")
        self.assertEqual(events[0].to_provider, "p2")
        self.assertEqual(events[0].targets, ["api_key#1:model-a", "api_key#1:model-b"])
        self.assertEqual([str(exc) for exc in events[0].exceptions], ["p1-a", "p1-b"])
        self.assertEqual(events[0].secret_values, ("secret-a", "secret-a"))
        self.assertEqual(second_provider.calls, 1)

    def test_all_providers_failed_reports_switches_and_final_failure(self) -> None:
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

        with self.assertRaisesRegex(Exception, "p2-failed"):
            chain.reason([])

        self.assertEqual([type(event) for event in events], [ProviderSwitchEvent, ProviderFallbackEvent])
        self.assertEqual(events[0].from_provider, "p1")
        self.assertEqual(events[0].to_provider, "p2")
        self.assertEqual(events[1].providers, ["p1", "p2"])
        self.assertEqual([str(exc) for exc in events[1].exceptions], ["p1-b", "p2-failed"])

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


if __name__ == "__main__":
    unittest.main()
