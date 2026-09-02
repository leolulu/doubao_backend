import configparser
import os
import tempfile
import threading
import typing
import unittest
from pathlib import Path
from unittest.mock import patch

if not hasattr(typing, "override"):
    typing.override = lambda func: func

from api.api_factory import ApiFactory, ManualModelSelectionError
from api.base_api import BaseApi
from api.chat_completion import ChatCompletion
from api.doubao import Doubao
from api.fallback_api import FallbackApi
from api.kimi import Kimi
from api.param_schema import ParamType, ProviderParam
from api.provider_fallback_api import ProviderFallbackApi
from api.retrying_api import ProviderSwitchEvent, RetryingApi
from models.session_manager import SessionManager


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


class FakeAccessPointProvider(BaseApi):
    @classmethod
    def get_params(cls) -> list[ProviderParam]:
        return [
            ProviderParam("api_key", ParamType.STRING, required=True),
            ProviderParam("access_point", ParamType.STRING, required=True),
        ]

    def reason(self, messages: list[dict[str, str]]) -> str:
        return "ok"


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
        factory._config = configparser.ConfigParser()
        factory._failure_handlers = []
        factory._provider_classes = provider_classes or {
            "p1": FakeProvider,
            "p2": FakeProvider,
            "p3": FakeProvider,
        }
        factory._credentials_path = "credentials.config"
        factory._reload_lock = threading.RLock()
        factory._last_config_hash = None
        return factory

    def test_parse_designated_providers_normalizes_and_validates_list(self) -> None:
        factory = self.make_factory()

        self.assertEqual(factory._parse_designated_providers(' P1 , "p2" '), ["p1", "p2"])
        self.assertEqual(
            factory._parse_designated_providers(" chat_completion:provider_name "),
            ["chat_completion:provider_name"],
        )

        invalid_values = ["p1,,p2", "p1,p1", "p4"]
        for invalid_value in invalid_values:
            with self.subTest(invalid_value=invalid_value):
                with self.assertRaises(ValueError):
                    factory._parse_designated_providers(invalid_value)

    def test_register_provider_classes_includes_kimi(self) -> None:
        factory = self.make_factory()
        factory._provider_classes = {}

        factory._register_provider_classes()

        self.assertIs(factory._provider_classes["kimi"], Kimi)

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

    def test_load_config_supports_named_chat_completion_provider(self) -> None:
        factory = self.make_factory()

        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                with open("credentials.config", "w", encoding="utf-8") as config_file:
                    config_file.write(
                        "\n".join([
                            "[designated_provider]",
                            "PROVIDER = chat_completion:provider_name,p1",
                            "",
                            "[CHAT_COMPLETION:PROVIDER_NAME]",
                            "BASE_URL = https://example.com/v1",
                            "API_KEY = key-1,key-2",
                            "MODEL = model-1,model-2",
                            "",
                            "[P1]",
                            "API_KEY = key-3",
                            "MODEL = model-3",
                        ])
                    )

                factory._load_config()
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(factory.get_designated_providers(), ["chat_completion:provider_name", "p1"])
        self.assertEqual(factory._credentials["chat_completion:provider_name"], {
            "base_url": "https://example.com/v1",
            "api_key": "key-1,key-2",
            "model": "model-1,model-2",
            "provider_name": "chat_completion:provider_name",
        })

    def test_create_minimal_config_documents_fallback_syntax(self) -> None:
        factory = self.make_factory({"p1": FakeProvider, "p2": FakeAccessPointProvider})

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "credentials.config")

            factory._create_minimal_config(config_path)

            with open(config_path, encoding="utf-8") as config_file:
                content = config_file.read()

        self.assertIn("# Generic Chat Completion example: PROVIDER = chat_completion:provider_name", content)
        self.assertIn("[CHAT_COMPLETION:PROVIDER_NAME]", content)
        self.assertIn("# Use the OpenAI-compatible base URL, usually ending with /v1.", content)
        self.assertIn("BASE_URL =", content)

        self.assertIn("# 供应商回退链示例: PROVIDER = doubao,zhipu,kimi", content)
        self.assertIn("# 回退语法: API_KEY = key-a,key-b", content)
        self.assertIn("# 回退语法: MODEL = model-a,model-b", content)
        self.assertIn("# 回退语法: ACCESS_POINT = ep-a,ep-b", content)

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
                    content = config_file.read()
                    self.assertIn("[P2]", content)
                    self.assertIn("# 回退语法: API_KEY = key-a,key-b", content)
                    self.assertIn("# 回退语法: MODEL = model-a,model-b", content)
            finally:
                os.chdir(previous_cwd)

    def test_load_config_adds_missing_chat_completion_section(self) -> None:
        factory = self.make_factory()

        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                with open("credentials.config", "w", encoding="utf-8") as config_file:
                    config_file.write(
                        "\n".join([
                            "[designated_provider]",
                            "PROVIDER = chat_completion:provider_name",
                        ])
                    )

                with self.assertRaises(UserWarning):
                    factory._load_config()

                with open("credentials.config", encoding="utf-8") as config_file:
                    content = config_file.read()
                    self.assertIn("[CHAT_COMPLETION:PROVIDER_NAME]", content)
                    self.assertIn("BASE_URL =", content)
                    self.assertIn("API_KEY =", content)
                    self.assertIn("MODEL =", content)
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

    def test_manual_model_selection_uses_only_requested_model_and_keeps_api_key_fallback(self) -> None:
        factory = self.make_factory()
        factory._config.read_string(
            "\n".join([
                "[P3]",
                "API_KEY = key-1,key-2",
                "MODEL = model-1,model-2",
            ])
        )

        client = factory.get_client("P3", "model-2")

        self.assertIsInstance(client, FallbackApi)
        self.assertEqual(
            [entry.target for entry in client.entries],
            ["api_key#1:model-2", "api_key#2:model-2"],
        )
        concrete_clients = [entry.client.client for entry in client.entries]
        self.assertEqual(
            [(item.api_key, item.model) for item in concrete_clients],
            [("key-1", "model-2"), ("key-2", "model-2")],
        )
        self.assertNotIn("p3", factory._clients)

    def test_manual_model_selection_does_not_replace_automatic_clients(self) -> None:
        factory = self.make_factory()
        factory._credentials["p1"] = {
            "api_key": "key-1",
            "model": "model-1,model-2",
        }
        factory._config.read_string(
            "\n".join([
                "[P1]",
                "API_KEY = key-1",
                "MODEL = model-1,model-2",
            ])
        )
        factory._set_designated_providers(["p1"])
        factory._register_designated_provider()
        automatic_default = factory.get_client()
        automatic_provider = factory.get_client("p1")

        manual = factory.get_client("p1", "model-2")

        self.assertIs(factory.get_client(), automatic_default)
        self.assertIs(factory.get_client("p1"), automatic_provider)
        self.assertIsNot(manual, automatic_provider)
        self.assertEqual(
            [entry.target for entry in automatic_provider.entries],
            ["model-1", "model-2"],
        )
        self.assertIsInstance(manual, RetryingApi)
        self.assertEqual(manual.client.model, "model-2")

    def test_manual_model_selection_rejects_invalid_parameter_combinations(self) -> None:
        factory = self.make_factory()
        factory._config.read_string(
            "\n".join([
                "[P1]",
                "API_KEY = key-1",
                "MODEL = Model-A",
            ])
        )

        invalid_selections = [
            (None, "Model-A"),
            ("p1", ""),
            ("p1", "Model-A,Model-B"),
            ("p1", "model-a"),
            ("p2", "Model-A"),
        ]
        for provider, model in invalid_selections:
            with self.subTest(provider=provider, model=model):
                with self.assertRaises(ManualModelSelectionError):
                    factory.get_client(provider, model)

    def test_manual_doubao_model_matches_configured_access_point(self) -> None:
        factory = self.make_factory({"doubao": Doubao})
        factory._config.read_string(
            "\n".join([
                "[DOUBAO]",
                "API_KEY = key-1",
                "ACCESS_POINT = ep-1,ep-2",
            ])
        )

        client = factory.get_client("doubao", "ep-2")

        self.assertIsInstance(client, RetryingApi)
        self.assertIsInstance(client.client, Doubao)
        self.assertEqual(client.client.access_point, "ep-2")

    def test_manual_chat_completion_alias_uses_its_own_config_section(self) -> None:
        factory = self.make_factory()
        factory._config.read_string(
            "\n".join([
                "[CHAT_COMPLETION:EXAMPLE]",
                "BASE_URL = https://example.test/v1",
                "API_KEY = key-1",
                "MODEL = model-a,model-b",
            ])
        )

        client = factory.get_client("chat_completion:example", "model-b")

        self.assertIsInstance(client, RetryingApi)
        self.assertIsInstance(client.client, ChatCompletion)
        self.assertEqual(client.client.model, "model-b")
        self.assertEqual(client.client.provider_name, "chat_completion:example")

    def test_list_available_provider_models_includes_valid_configured_sections(self) -> None:
        factory = self.make_factory({"p1": FakeProvider, "doubao": Doubao})
        factory._config.read_string(
            "\n".join([
                "[P1]",
                "API_KEY = key-1",
                "MODEL = Model-A, model-b, Model-A",
                "",
                "[DOUBAO]",
                "API_KEY = key-2",
                "ACCESS_POINT = ep-1,ep-2",
                "",
                "[CHAT_COMPLETION:EXAMPLE]",
                "BASE_URL = https://example.test/v1",
                "API_KEY = key-3",
                "MODEL = model-c",
            ])
        )

        self.assertEqual(factory.list_available_provider_models(), [
            {"id": "p1", "models": ["Model-A", "model-b"]},
            {"id": "doubao", "models": ["ep-1", "ep-2"]},
            {"id": "chat_completion:example", "models": ["model-c"]},
        ])

    def test_list_available_provider_models_omits_unavailable_sections(self) -> None:
        factory = self.make_factory()
        factory._config.read_string(
            "\n".join([
                "[P1]",
                "API_KEY =",
                "MODEL = model-a",
                "",
                "[P2]",
                "API_KEY = key-2",
                "MODEL = model-b,",
                "",
                "[UNKNOWN]",
                "API_KEY = key-3",
                "MODEL = model-c",
                "",
                "[P3]",
                "API_KEY = key-4",
            ])
        )

        self.assertEqual(factory.list_available_provider_models(), [])

    def test_default_client_registers_chat_completion_provider_with_model_fallback(self) -> None:
        factory = self.make_factory()
        factory._credentials.update({
            "chat_completion:provider_name": {
                "base_url": "https://example.com/v1",
                "api_key": "key-1,key-2",
                "model": "model-1,model-2",
                "provider_name": "chat_completion:provider_name",
            },
        })
        factory._set_designated_providers(["chat_completion:provider_name"])

        factory._register_designated_provider()

        client = factory.get_client("chat_completion:provider_name")
        self.assertIsInstance(client, FallbackApi)
        self.assertEqual(factory.list_providers(), ["chat_completion:provider_name"])
        self.assertEqual(
            [entry.target for entry in client.entries],
            [
                "api_key#1:model-1",
                "api_key#1:model-2",
                "api_key#2:model-1",
                "api_key#2:model-2",
            ],
        )
        first_client = client.entries[0].client.client
        self.assertIsInstance(first_client, ChatCompletion)
        self.assertEqual(first_client.provider_name, "chat_completion:provider_name")
        self.assertEqual(first_client.base_url, "https://example.com/v1")

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

    def _write_credentials(self, content: str) -> None:
        with open("credentials.config", "w", encoding="utf-8") as config_file:
            config_file.write(content)

    def test_reload_credentials_updates_providers_models_and_default_chain(self) -> None:
        factory = self.make_factory()

        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                self._write_credentials(
                    "\n".join([
                        "[designated_provider]",
                        "PROVIDER = p1",
                        "",
                        "[P1]",
                        "API_KEY = key-1",
                        "MODEL = model-1",
                    ])
                )
                factory._load_config()
                factory._register_designated_provider()
                factory._last_config_hash = factory._hash_file("credentials.config")

                self.assertEqual(factory.get_designated_providers(), ["p1"])
                self.assertEqual(
                    factory.list_available_provider_models(),
                    [{"id": "p1", "models": ["model-1"]}],
                )

                self._write_credentials(
                    "\n".join([
                        "[designated_provider]",
                        "PROVIDER = p1,p2",
                        "",
                        "[P1]",
                        "API_KEY = key-1",
                        "MODEL = model-1,model-extra",
                        "",
                        "[P2]",
                        "API_KEY = key-2",
                        "MODEL = model-2",
                    ])
                )

                reloaded = factory.reload_credentials()
            finally:
                os.chdir(previous_cwd)

        self.assertTrue(reloaded)
        self.assertEqual(factory.get_designated_providers(), ["p1", "p2"])
        self.assertIsInstance(factory.get_client(), ProviderFallbackApi)
        self.assertEqual(
            factory.list_available_provider_models(),
            [
                {"id": "p1", "models": ["model-1", "model-extra"]},
                {"id": "p2", "models": ["model-2"]},
            ],
        )
        manual_client = factory.get_client("p1", "model-extra")
        self.assertIsInstance(manual_client, RetryingApi)
        self.assertEqual(manual_client.client.model, "model-extra")

    def test_reload_credentials_keeps_previous_config_when_invalid(self) -> None:
        factory = self.make_factory()

        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                self._write_credentials(
                    "\n".join([
                        "[designated_provider]",
                        "PROVIDER = p1",
                        "",
                        "[P1]",
                        "API_KEY = key-1",
                        "MODEL = model-1",
                    ])
                )
                factory._load_config()
                factory._register_designated_provider()
                factory._last_config_hash = factory._hash_file("credentials.config")
                previous_client = factory.get_client("p1")
                previous_models = factory.list_available_provider_models()
                previous_hash = factory._last_config_hash

                self._write_credentials(
                    "\n".join([
                        "[designated_provider]",
                        "PROVIDER = p1",
                        "",
                        "[P1]",
                        "API_KEY =",
                        "MODEL = model-1",
                    ])
                )

                reloaded = factory.reload_credentials()
            finally:
                os.chdir(previous_cwd)

        self.assertFalse(reloaded)
        self.assertEqual(factory.get_designated_providers(), ["p1"])
        self.assertIs(factory.get_client("p1"), previous_client)
        self.assertEqual(factory.list_available_provider_models(), previous_models)
        self.assertEqual(factory._last_config_hash, previous_hash)

    def test_reload_credentials_skips_when_content_unchanged(self) -> None:
        factory = self.make_factory()

        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                self._write_credentials(
                    "\n".join([
                        "[designated_provider]",
                        "PROVIDER = p1",
                        "",
                        "[P1]",
                        "API_KEY = key-1",
                        "MODEL = model-1",
                    ])
                )
                factory._load_config()
                factory._register_designated_provider()
                factory._last_config_hash = factory._hash_file("credentials.config")
                previous_client = factory.get_client("p1")

                reloaded = factory.reload_credentials()
            finally:
                os.chdir(previous_cwd)

        self.assertFalse(reloaded)
        self.assertIs(factory.get_client("p1"), previous_client)

    def test_existing_session_keeps_old_client_after_reload(self) -> None:
        factory = self.make_factory()

        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                self._write_credentials(
                    "\n".join([
                        "[designated_provider]",
                        "PROVIDER = p1",
                        "",
                        "[P1]",
                        "API_KEY = key-1",
                        "MODEL = model-1",
                    ])
                )
                factory._load_config()
                factory._register_designated_provider()
                factory._last_config_hash = factory._hash_file("credentials.config")

                manager = SessionManager(api_factory=factory)
                session = manager.get_or_create_session("conversation-1", provider="p1")
                bound_client = session.client

                self._write_credentials(
                    "\n".join([
                        "[designated_provider]",
                        "PROVIDER = p2",
                        "",
                        "[P1]",
                        "API_KEY = key-1-new",
                        "MODEL = model-1",
                        "",
                        "[P2]",
                        "API_KEY = key-2",
                        "MODEL = model-2",
                    ])
                )
                self.assertTrue(factory.reload_credentials())

                same_session = manager.get_or_create_session("conversation-1", provider="p2")
                new_session = manager.get_or_create_session("conversation-2")
            finally:
                os.chdir(previous_cwd)

        self.assertIs(same_session, session)
        self.assertIs(same_session.client, bound_client)
        self.assertIsNot(new_session.client, bound_client)
        self.assertEqual(factory.get_designated_providers(), ["p2"])
        self.assertEqual(
            factory.list_available_provider_models(),
            [
                {"id": "p1", "models": ["model-1"]},
                {"id": "p2", "models": ["model-2"]},
            ],
        )

    def test_runtime_summary_redacts_api_keys(self) -> None:
        factory = self.make_factory()
        config = configparser.ConfigParser()
        config.read_dict({
            "designated_provider": {"PROVIDER": "p1"},
            "P1": {"API_KEY": "secret-a,secret-b", "MODEL": "model-1"},
        })
        factory._config = config
        factory._set_designated_providers(["p1"])
        factory._clients = {"p1": FakeProvider("secret-a", "model-1")}
        factory._last_config_hash = "abc"

        summary = factory._build_runtime_summary()

        self.assertEqual(summary["designated_providers"], ["p1"])
        self.assertEqual(summary["sections"][0]["API_KEY"], "<2 value(s) redacted>")
        self.assertEqual(summary["sections"][0]["MODEL"], "model-1")
        self.assertNotIn("secret-a", str(summary))
        self.assertNotIn("secret-b", str(summary))

    def test_reload_with_broken_nondesignated_section_keeps_new_config(self) -> None:
        factory = self.make_factory()

        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                self._write_credentials(
                    "\n".join([
                        "[designated_provider]",
                        "PROVIDER = p1",
                        "",
                        "[P1]",
                        "API_KEY = key-1",
                        "MODEL = model-1",
                    ])
                )
                factory._load_config()
                factory._register_designated_provider()
                factory._last_config_hash = factory._hash_file("credentials.config")

                self._write_credentials(
                    "\n".join([
                        "[designated_provider]",
                        "PROVIDER = p2",
                        "",
                        "[P2]",
                        "API_KEY = key-2",
                        "MODEL = model-2",
                        "",
                        # Non-default section with interpolation that breaks items()
                        "[EXTRA]",
                        "NOTE = broken %(missing)s value",
                    ])
                )

                reloaded = factory.reload_credentials()
            finally:
                os.chdir(previous_cwd)

        self.assertTrue(reloaded)
        self.assertEqual(factory.get_designated_providers(), ["p2"])
        self.assertEqual(factory.list_providers(), ["p2"])
        self.assertEqual(
            factory.list_available_provider_models(),
            [{"id": "p2", "models": ["model-2"]}],
        )

    def test_reload_success_logging_failure_still_returns_true_and_keeps_new_config(self) -> None:
        factory = self.make_factory()

        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                self._write_credentials(
                    "\n".join([
                        "[designated_provider]",
                        "PROVIDER = p1",
                        "",
                        "[P1]",
                        "API_KEY = key-1",
                        "MODEL = model-1",
                    ])
                )
                factory._load_config()
                factory._register_designated_provider()
                factory._last_config_hash = factory._hash_file("credentials.config")

                self._write_credentials(
                    "\n".join([
                        "[designated_provider]",
                        "PROVIDER = p2",
                        "",
                        "[P2]",
                        "API_KEY = key-2",
                        "MODEL = model-2",
                    ])
                )

                with patch.object(
                    factory,
                    "list_available_provider_models",
                    side_effect=RuntimeError("synthetic logging failure"),
                ):
                    reloaded = factory.reload_credentials()
            finally:
                os.chdir(previous_cwd)

        self.assertTrue(reloaded)
        self.assertEqual(factory.get_designated_providers(), ["p2"])
        self.assertEqual(factory.list_providers(), ["p2"])
        self.assertEqual(
            factory.list_available_provider_models(),
            [{"id": "p2", "models": ["model-2"]}],
        )

    def test_runtime_summary_survives_broken_interpolation_sections(self) -> None:
        factory = self.make_factory()
        config = configparser.ConfigParser()
        config.read_dict({
            "designated_provider": {"PROVIDER": "p1"},
            "P1": {"API_KEY": "secret", "MODEL": "model-1"},
            "P2": {
                "API_KEY": "broken-secret-%(missing)s",
                "MODEL": "model-2",
            },
        })
        factory._config = config
        factory._set_designated_providers(["p1"])
        factory._clients = {"p1": FakeProvider("secret", "model-1")}

        summary = factory._build_runtime_summary()
        safe_summary = factory._safe_runtime_summary()

        self.assertEqual(summary["designated_providers"], ["p1"])
        p2_summary = next(item for item in summary["sections"] if item["section"] == "P2")
        self.assertEqual(p2_summary["error"], "InterpolationMissingOptionError")
        self.assertIsInstance(safe_summary, dict)
        self.assertNotIn("secret", str(summary))

        with patch.object(
            factory,
            "_build_runtime_summary",
            side_effect=RuntimeError("broken-secret"),
        ):
            unavailable_summary = factory._safe_runtime_summary()

        self.assertEqual(unavailable_summary, "<summary unavailable: RuntimeError>")
        self.assertNotIn("secret", unavailable_summary)



class AutoModelDiscoveryTest(unittest.TestCase):
    """Tests for auto model discovery in ApiFactory."""

    def make_factory(self, provider_classes=None):
        factory = object.__new__(ApiFactory)
        factory._clients = {}
        factory._default_client = None
        factory._designated_providers = ["chat_completion:test"]
        factory._designated_provider = "chat_completion:test"
        factory._credentials = {
            "designated_provider": "chat_completion:test",
            "designated_providers": ["chat_completion:test"],
        }
        factory._config = configparser.ConfigParser()
        factory._failure_handlers = []
        factory._provider_classes = provider_classes or {}
        factory._credentials_path = "credentials.config"
        factory._reload_lock = threading.RLock()
        factory._last_config_hash = None
        factory._auto_discovered_models = {}
        return factory

    def _make_chat_completion_config(self, model_value):
        factory = self.make_factory()
        factory._config.read_string(
            "\n".join([
                "[CHAT_COMPLETION:TEST]",
                "BASE_URL = https://example.test/v1",
                "API_KEY = test-key",
                f"MODEL = {model_value}",
            ])
        )
        factory._credentials["chat_completion:test"] = {
            "base_url": "https://example.test/v1",
            "api_key": "test-key",
            "model": model_value,
            "provider_name": "chat_completion:test",
        }
        return factory

    def _make_partial_start_factory(self):
        factory = self._make_chat_completion_config("auto")
        factory._provider_classes.update({
            "p1": FakeProvider,
            "p2": FakeProvider,
        })
        factory._credentials.update({
            "p1": {"api_key": "key-1", "model": "model-1"},
            "p2": {"api_key": "key-2", "model": "model-2"},
        })
        factory._set_designated_providers([
            "p1",
            "p2",
            "chat_completion:test",
        ])
        return factory

    def test_startup_skips_failed_auto_provider_and_keeps_available_chain(self):
        factory = self._make_partial_start_factory()

        with self.assertLogs("api.api_factory", level="ERROR") as captured_logs:
            with patch.object(
                ChatCompletion,
                "discover_models",
                side_effect=Exception("network error"),
            ) as discover_models:
                factory._register_designated_provider()

        discover_models.assert_called_once_with()
        self.assertEqual(factory.list_providers(), ["p1", "p2"])
        self.assertNotIn("chat_completion:test", factory._clients)
        self.assertIsInstance(factory.get_client(), ProviderFallbackApi)
        self.assertEqual(
            [entry.provider_name for entry in factory.get_client().entries],
            ["p1", "p2"],
        )
        self.assertTrue(any(
            "skipping unavailable provider: provider=chat_completion:test" in message
            for message in captured_logs.output
        ))

    def test_startup_fails_when_no_provider_can_initialize(self):
        factory = self._make_chat_completion_config("auto")

        with self.assertLogs("api.api_factory", level="ERROR"):
            with patch.object(
                ChatCompletion,
                "discover_models",
                side_effect=Exception("network error"),
            ):
                with self.assertRaisesRegex(ValueError, "没有可用的默认服务商客户端"):
                    factory._register_designated_provider()

    def test_startup_reuses_discovered_models_when_building_default_chain(self):
        factory = self._make_chat_completion_config("auto")
        factory._provider_classes["p1"] = FakeProvider
        factory._credentials["p1"] = {
            "api_key": "key-1",
            "model": "model-1",
        }
        factory._set_designated_providers(["p1", "chat_completion:test"])

        with patch.object(
            ChatCompletion,
            "discover_models",
            return_value=["m1", "m2"],
        ) as discover_models:
            factory._register_designated_provider()

        discover_models.assert_called_once_with()
        default_client = factory.get_client()
        self.assertIsInstance(default_client, ProviderFallbackApi)
        auto_entry = default_client.entries[1]
        self.assertEqual(auto_entry.provider_name, "chat_completion:test")
        self.assertIsInstance(auto_entry.client, FallbackApi)
        self.assertEqual(
            [entry.target for entry in auto_entry.client.entries],
            ["m1", "m2"],
        )

    def test_refresh_adds_provider_that_failed_during_startup(self):
        factory = self._make_partial_start_factory()

        with self.assertLogs("api.api_factory", level="ERROR"):
            with patch.object(
                ChatCompletion,
                "discover_models",
                side_effect=Exception("network error"),
            ):
                factory._register_designated_provider()

        with patch.object(
            ChatCompletion,
            "discover_models",
            return_value=["m1", "m2"],
        ) as discover_models:
            results = factory.reload_auto_providers()

        discover_models.assert_called_once_with()
        self.assertEqual(results, [{
            "provider": "chat_completion:test",
            "status": "ok",
            "models_count": 2,
            "rebuilt": True,
        }])
        self.assertEqual(
            factory.list_providers(),
            ["p1", "p2", "chat_completion:test"],
        )
        self.assertIsInstance(factory.get_client(), ProviderFallbackApi)
        self.assertEqual(
            [entry.provider_name for entry in factory.get_client().entries],
            ["p1", "p2", "chat_completion:test"],
        )

    def test_auto_model_discovery_builds_fallback_chain(self):
        factory = self._make_chat_completion_config("auto")
        discovered = ["m1", "m2", "m3"]

        with patch.object(
            ChatCompletion, "discover_models", return_value=discovered
        ):
            client = factory._build_configured_provider_client(
                "chat_completion:test", ChatCompletion
            )

        self.assertIsInstance(client, FallbackApi)
        self.assertEqual(
            [e.target for e in client.entries],
            ["m1", "m2", "m3"],
        )
        self.assertEqual(
            factory._auto_discovered_models["chat_completion:test"],
            ["m1", "m2", "m3"],
        )

    def test_auto_model_discovery_caps_at_limit(self):
        factory = self._make_chat_completion_config("auto")
        discovered = [f"m{i}" for i in range(65)]

        with patch.object(
            ChatCompletion, "discover_models", return_value=discovered
        ):
            client = factory._build_configured_provider_client(
                "chat_completion:test", ChatCompletion
            )

        self.assertIsInstance(client, FallbackApi)
        self.assertEqual(len(client.entries), 60)
        self.assertEqual(
            [e.target for e in client.entries],
            [f"m{i}" for i in range(60)],
        )

    def test_auto_pattern_filters_and_caps(self):
        factory = self._make_chat_completion_config("auto:gpt-")
        discovered = [f"gpt-{i}" for i in range(65)] + ["claude-3", "o1"]
        expected = [f"gpt-{i}" for i in range(60)]

        with patch.object(
            ChatCompletion, "discover_models", return_value=discovered
        ):
            client = factory._build_configured_provider_client(
                "chat_completion:test", ChatCompletion
            )

        self.assertIsInstance(client, FallbackApi)
        self.assertEqual(
            [e.target for e in client.entries],
            expected,
        )

    def test_auto_pattern_no_match_raises(self):
        factory = self._make_chat_completion_config("auto:nonexistent")
        discovered = ["m1", "m2"]

        with patch.object(
            ChatCompletion, "discover_models", return_value=discovered
        ):
            with self.assertRaises(ValueError) as ctx:
                factory._build_configured_provider_client(
                    "chat_completion:test", ChatCompletion
                )

        self.assertIn("未找到匹配的模型", str(ctx.exception))

    def test_auto_discovery_failure_raises(self):
        factory = self._make_chat_completion_config("auto")

        with patch.object(
            ChatCompletion, "discover_models", side_effect=Exception("401")
        ):
            with self.assertRaises(Exception):
                factory._build_configured_provider_client(
                    "chat_completion:test", ChatCompletion
                )

    def test_list_available_provider_models_returns_discovered_for_auto(self):
        factory = self._make_chat_completion_config("auto")
        discovered = [
            "tokenrhythm/deepseek",
            "modelscope/Kimi-K3",
            "GMI/MiniMax-M3",
            "shuo/glm-5.2",
        ]
        factory._auto_discovered_models["chat_completion:test"] = discovered

        result = factory.list_available_provider_models()

        self.assertEqual(result, [
            {
                "id": "chat_completion:test",
                "models": [
                    "GMI/MiniMax-M3",
                    "modelscope/Kimi-K3",
                    "shuo/glm-5.2",
                    "tokenrhythm/deepseek",
                ],
            },
        ])
        self.assertEqual(
            factory._auto_discovered_models["chat_completion:test"],
            discovered,
        )

    def test_list_available_provider_models_empty_for_auto_before_discovery(self):
        factory = self._make_chat_completion_config("auto")

        result = factory.list_available_provider_models()

        self.assertEqual(result, [])

    def test_manual_mode_uses_discovered_snapshot_for_auto(self):
        factory = self._make_chat_completion_config("auto")
        factory._auto_discovered_models["chat_completion:test"] = ["m1", "m2"]

        client = factory.get_client("chat_completion:test", "m2")

        self.assertIsInstance(client, RetryingApi)
        self.assertEqual(client.client.model, "m2")

    def test_manual_mode_rejects_model_not_in_discovered_snapshot(self):
        factory = self._make_chat_completion_config("auto")
        factory._auto_discovered_models["chat_completion:test"] = ["m1", "m2"]

        with self.assertRaises(ManualModelSelectionError):
            factory.get_client("chat_completion:test", "m3")

    def test_is_auto_model_detects_sentinels(self):
        factory = self.make_factory()
        self.assertTrue(factory._is_auto_model("auto"))
        self.assertTrue(factory._is_auto_model(""))
        self.assertTrue(factory._is_auto_model("auto:gpt-"))
        self.assertTrue(factory._is_auto_model("AUTO"))
        self.assertTrue(factory._is_auto_model("  auto  "))
        self.assertFalse(factory._is_auto_model("gpt-4o"))
        self.assertFalse(factory._is_auto_model("auto-1"))

    def test_parse_auto_pattern_extracts_pattern(self):
        factory = self.make_factory()
        self.assertIsNone(factory._parse_auto_pattern("auto"))
        self.assertIsNone(factory._parse_auto_pattern(""))
        self.assertEqual(factory._parse_auto_pattern("auto:gpt-"), "gpt-")
        self.assertEqual(factory._parse_auto_pattern("AUTO:claude"), "claude")

    def test_reload_auto_providers_replaces_on_change(self):
        factory = self._make_chat_completion_config("auto")
        factory._set_designated_providers(["chat_completion:test"])

        with patch.object(
            ChatCompletion, "discover_models", return_value=["m1", "m2"]
        ):
            factory._register_designated_provider()

        old_client = factory.get_client("chat_completion:test")
        self.assertIsInstance(old_client, FallbackApi)

        with patch.object(
            ChatCompletion, "discover_models", return_value=["m1", "m2", "m3"]
        ):
            results = factory.reload_auto_providers()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "ok")
        self.assertTrue(results[0]["rebuilt"])
        new_client = factory.get_client("chat_completion:test")
        self.assertIsInstance(new_client, FallbackApi)
        self.assertEqual(
            [e.target for e in new_client.entries],
            ["m1", "m2", "m3"],
        )

    def test_reload_auto_providers_skips_when_unchanged(self):
        factory = self._make_chat_completion_config("auto")
        factory._set_designated_providers(["chat_completion:test"])

        with patch.object(
            ChatCompletion, "discover_models", return_value=["m1", "m2"]
        ):
            factory._register_designated_provider()

        old_client = factory.get_client("chat_completion:test")

        with patch.object(
            ChatCompletion, "discover_models", return_value=["m1", "m2"]
        ):
            results = factory.reload_auto_providers()

        self.assertEqual(results[0]["rebuilt"], False)
        self.assertIs(factory.get_client("chat_completion:test"), old_client)

    def test_reload_auto_providers_keeps_old_on_failure(self):
        factory = self._make_chat_completion_config("auto")
        factory._set_designated_providers(["chat_completion:test"])

        with patch.object(
            ChatCompletion, "discover_models", return_value=["m1", "m2"]
        ):
            factory._register_designated_provider()

        old_client = factory.get_client("chat_completion:test")

        with patch.object(
            ChatCompletion, "discover_models", side_effect=Exception("network error")
        ):
            results = factory.reload_auto_providers()

        self.assertEqual(results[0]["status"], "failed")
        self.assertFalse(results[0]["rebuilt"])
        self.assertIs(factory.get_client("chat_completion:test"), old_client)


class CredentialsWatcherTest(unittest.TestCase):
    def test_start_credentials_watcher_calls_reload_on_matching_file_event(self) -> None:
        from api.credentials_watcher import start_credentials_watcher
        from watchfiles import Change

        reloaded = threading.Event()

        class FakeFactory:
            def reload_credentials(self) -> bool:
                reloaded.set()
                return True

        stop_event = threading.Event()

        def fake_watch(*_args, **_kwargs):
            yield {(Change.modified, str(Path.cwd() / "credentials.config"))}
            stop_event.set()
            return
            yield

        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                with open("credentials.config", "w", encoding="utf-8") as config_file:
                    config_file.write("[designated_provider]\nPROVIDER = p1\n")
                with patch("api.credentials_watcher.watch", side_effect=fake_watch):
                    thread = start_credentials_watcher(
                        FakeFactory(),
                        credentials_path="credentials.config",
                        stop_event=stop_event,
                    )
                    self.assertTrue(reloaded.wait(timeout=2))
                    stop_event.set()
                    thread.join(timeout=2)
            finally:
                os.chdir(previous_cwd)

        self.assertFalse(thread.is_alive())

    def test_watcher_continues_after_reload_raises(self) -> None:
        from api.credentials_watcher import start_credentials_watcher
        from watchfiles import Change

        call_count = 0
        second_call = threading.Event()

        class FakeFactory:
            def reload_credentials(self) -> bool:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("boom")
                second_call.set()
                return True

        stop_event = threading.Event()

        def fake_watch(*_args, **_kwargs):
            target = str(Path.cwd() / "credentials.config")
            yield {(Change.modified, target)}
            yield {(Change.modified, target)}
            stop_event.set()
            return
            yield

        with tempfile.TemporaryDirectory() as temp_dir:
            previous_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                with open("credentials.config", "w", encoding="utf-8") as config_file:
                    config_file.write("[designated_provider]\nPROVIDER = p1\n")
                with patch("api.credentials_watcher.watch", side_effect=fake_watch):
                    thread = start_credentials_watcher(
                        FakeFactory(),
                        credentials_path="credentials.config",
                        stop_event=stop_event,
                    )
                    self.assertTrue(second_call.wait(timeout=2))
                    stop_event.set()
                    thread.join(timeout=2)
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(call_count, 2)
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
