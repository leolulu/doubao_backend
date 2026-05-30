import os
import tempfile
import typing
import unittest

if not hasattr(typing, "override"):
    typing.override = lambda func: func

from api.api_factory import ApiFactory
from api.base_api import BaseApi
from api.fallback_api import FallbackApi
from api.param_schema import ParamType, ProviderParam
from api.provider_fallback_api import ProviderFallbackApi
from api.retrying_api import ProviderSwitchEvent, RetryingApi


class FakeProvider(BaseApi):
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    @classmethod
    def get_params(cls) -> list[ProviderParam]:
        return [
            ProviderParam("api_key", ParamType.STRING, required=True),
            ProviderParam("model", ParamType.STRING, required=True),
        ]

    def reason(self, messages: list[dict[str, str]]) -> str:
        return f"{self.api_key}:{self.model}"


class FailingProvider(FakeProvider):
    def reason(self, messages: list[dict[str, str]]) -> str:
        raise Exception(f"{self.api_key}:{self.model}")


class SuccessfulProvider(FakeProvider):
    def reason(self, messages: list[dict[str, str]]) -> str:
        return f"success:{self.api_key}:{self.model}"


class ApiFactoryProviderChainTest(unittest.TestCase):
    def make_factory(self, provider_classes: dict[str, type[BaseApi]] | None = None) -> ApiFactory:
        factory = object.__new__(ApiFactory)
        factory._clients = {}
        factory._default_client = None
        factory._designated_providers = ["p1"]
        factory._designated_provider = "p1"
        factory._credentials = {
            "designated_provider": "p1",
            "designated_providers": ["p1"],
        }
        factory._failure_handlers = []
        factory._provider_classes = provider_classes or {
            "p1": FakeProvider,
            "p2": FakeProvider,
            "p3": FakeProvider,
        }
        return factory

    def test_parse_designated_providers_normalizes_and_validates_list(self) -> None:
        factory = self.make_factory()

        self.assertEqual(factory._parse_designated_providers(' P1 , "p2" '), ["p1", "p2"])

        invalid_values = ["p1,,p2", "p1,p1", "p4"]
        for invalid_value in invalid_values:
            with self.subTest(invalid_value=invalid_value):
                with self.assertRaises(ValueError):
                    factory._parse_designated_providers(invalid_value)

    def test_load_config_validates_every_configured_provider_at_startup(self) -> None:
        factory = self.make_factory()

        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                with open("credentials.config", "w", encoding="utf-8") as config_file:
                    config_file.write(
                        "\n".join([
                            "[designated_provider]",
                            "PROVIDER = p1,p2",
                            "",
                            "[P1]",
                            "API_KEY = key-1",
                            "MODEL = model-1",
                            "",
                            "[P2]",
                            "API_KEY = key-2",
                            "MODEL = model-2",
                        ])
                    )

                factory._load_config()
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(factory.get_designated_providers(), ["p1", "p2"])
        self.assertEqual(factory.get_designated_provider(), "p1,p2")
        self.assertEqual(factory._credentials["p1"], {"api_key": "key-1", "model": "model-1"})
        self.assertEqual(factory._credentials["p2"], {"api_key": "key-2", "model": "model-2"})

    def test_load_config_fails_at_startup_when_later_provider_section_is_missing(self) -> None:
        factory = self.make_factory()

        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                with open("credentials.config", "w", encoding="utf-8") as config_file:
                    config_file.write(
                        "\n".join([
                            "[designated_provider]",
                            "PROVIDER = p1,p2",
                            "",
                            "[P1]",
                            "API_KEY = key-1",
                            "MODEL = model-1",
                        ])
                    )

                with self.assertRaises(UserWarning):
                    factory._load_config()

                with open("credentials.config", encoding="utf-8") as config_file:
                    self.assertIn("[P2]", config_file.read())
            finally:
                os.chdir(previous_cwd)

    def test_default_client_is_provider_chain_and_request_provider_overrides_it(self) -> None:
        factory = self.make_factory()
        factory._credentials.update({
            "p1": {"api_key": "key-1", "model": "model-1,model-2"},
            "p2": {"api_key": "key-2", "model": "model-3"},
        })
        factory._set_designated_providers(["p1", "p2"])

        factory._register_designated_provider()

        self.assertIsInstance(factory.get_client(), ProviderFallbackApi)
        self.assertIs(factory.get_client("p1"), factory._clients["p1"])
        self.assertIsInstance(factory.get_client("p1"), FallbackApi)
        self.assertIsInstance(factory.get_client("p2"), RetryingApi)
        self.assertEqual(factory.list_providers(), ["p1", "p2"])

    def test_provider_chain_sends_switch_notification_without_inner_fallback_notification(self) -> None:
        events = []
        factory = self.make_factory({
            "p1": FailingProvider,
            "p2": SuccessfulProvider,
        })
        factory._failure_handlers = [events.append]
        factory._credentials.update({
            "p1": {"api_key": "key-1", "model": "model-1,model-2"},
            "p2": {"api_key": "key-2", "model": "model-3"},
        })
        factory._set_designated_providers(["p1", "p2"])
        factory._register_designated_provider()

        result = factory.get_client().reason([])

        self.assertEqual(result, "success:key-2:model-3")
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], ProviderSwitchEvent)
        self.assertEqual(events[0].from_provider, "p1")
        self.assertEqual(events[0].to_provider, "p2")
        self.assertEqual(events[0].targets, ["model-1", "model-2"])


if __name__ == "__main__":
    unittest.main()
