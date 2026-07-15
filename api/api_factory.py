import configparser
import os
from typing import Any, Dict, Optional, Type

from api.base_api import BaseApi
from api.chat_completion import ChatCompletion
from api.deepseek import DeepSeek
from api.doubao import Doubao
from api.fallback_api import FallbackApi, FallbackEntry
from api.kimi import Kimi
from api.minimax import MiniMax
from api.modelscope import ModelScope
from api.provider_fallback_api import ProviderFallbackApi, ProviderFallbackEntry
from api.retrying_api import FailureHandler, FeishuNotifier, RetryingApi
from api.zhipu import Zhipu


class ManualModelSelectionError(ValueError):
    """The requested provider/model pair is not available in configuration."""


class ApiFactory:
    """Factory for configured AI provider clients."""

    FEISHU_WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/b06a606f-9cc9-4033-bed8-8ff2e65ecec9"
    CHAT_COMPLETION_PREFIX = "chat_completion:"

    def __init__(self):
        self._clients: Dict[str, BaseApi] = {}
        self._default_client: BaseApi | None = None
        self._designated_providers: list[str] = ["doubao"]
        self._designated_provider: str = "doubao"
        self._credentials: Dict[str, Any] = {
            "designated_provider": "doubao",
            "designated_providers": ["doubao"],
        }
        self._config: configparser.ConfigParser | None = None
        self._failure_handlers: list[FailureHandler] = [FeishuNotifier(self.FEISHU_WEBHOOK_URL).notify_failure]
        self._provider_classes: Dict[str, Type[BaseApi]] = {}
        self._register_provider_classes()
        self._load_config()
        self._register_designated_provider()

    def _register_provider_classes(self):
        self._provider_classes["doubao"] = Doubao
        self._provider_classes["zhipu"] = Zhipu
        self._provider_classes["deepseek"] = DeepSeek
        self._provider_classes["minimax"] = MiniMax
        self._provider_classes["modelscope"] = ModelScope
        self._provider_classes["kimi"] = Kimi

    def _create_minimal_config(self, credential_file: str):
        lines = []

        lines.append("[designated_provider]")
        lines.append("# AI provider names in fallback priority order.")
        lines.append("# Generic Chat Completion example: PROVIDER = chat_completion:provider_name")
        lines.append("# 单供应商示例: PROVIDER = doubao")
        lines.append("# 供应商回退链示例: PROVIDER = doubao,zhipu,kimi")
        lines.append("# 按从左到右的顺序尝试供应商，不要留下空项。")
        lines.append("PROVIDER = doubao")
        lines.append("")

        for provider_name, provider_class in self._provider_classes.items():
            lines.extend(self._build_provider_config_lines(provider_name, provider_class))
            lines.append("")

        lines.extend(self._build_provider_config_lines("chat_completion:provider_name", ChatCompletion))
        lines.append("")

        with open(credential_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _load_config(self):
        credential_file = "credentials.config"

        if not os.path.exists(credential_file):
            self._create_minimal_config(credential_file)
            raise UserWarning(f"已在当前目录生成 {credential_file} 文件，请填入凭据信息!")

        try:
            config = configparser.ConfigParser()
            config.read(credential_file, encoding="utf-8")
            self._config = config

            raw_provider = "doubao"
            if config.has_section("designated_provider"):
                raw_provider = config.get("designated_provider", "PROVIDER", fallback="doubao")

            providers = self._parse_designated_providers(raw_provider)
            self._set_designated_providers(providers)

            for provider_name in providers:
                self._load_provider_config(config, provider_name, credential_file)

        except UserWarning:
            raise
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"配置文件读取失败: {str(e)}")

    def _parse_designated_providers(self, value: Any) -> list[str]:
        raw_value = str(value)
        providers = [
            part.strip().strip('"').strip("'").lower()
            for part in raw_value.split(",")
        ]
        if any(not provider for provider in providers):
            raise ValueError("[designated_provider] PROVIDER 配置包含空的供应商名称")

        seen: set[str] = set()
        duplicated: list[str] = []
        for provider in providers:
            if provider in seen:
                duplicated.append(provider)
            seen.add(provider)
        if duplicated:
            raise ValueError(f"[designated_provider] PROVIDER 配置包含重复供应商: {', '.join(duplicated)}")

        unknown = [
            provider
            for provider in providers
            if not self._is_known_provider(provider)
        ]
        if unknown:
            available_providers = self._format_available_provider_names()
            raise ValueError(
                f"[designated_provider] PROVIDER 包含未知供应商: {', '.join(unknown)}，"
                f"可用的服务商: {available_providers}"
            )

        return providers

    def _set_designated_providers(self, providers: list[str]) -> None:
        self._designated_providers = list(providers)
        self._designated_provider = ",".join(providers)
        self._credentials["designated_provider"] = self._designated_provider
        self._credentials["designated_providers"] = list(providers)

    def _load_provider_config(
        self,
        config: configparser.ConfigParser,
        provider_name: str,
        credential_file: str,
    ) -> None:
        section_name = self._get_provider_section_name(provider_name)
        provider_class = self._get_provider_class(provider_name)

        if not config.has_section(section_name):
            self._ensure_provider_config(provider_name, credential_file)
            raise ValueError(f"配置文件中未找到服务商 [{section_name}] 的配置段")

        provider_config = {}
        for config_key, raw_value in config.items(section_name):
            if config_key.startswith("#"):
                continue
            provider_config[config_key.lower()] = raw_value

        for param in provider_class.get_params():
            if param.name in provider_config:
                provider_config[param.name] = param.parse_value(provider_config[param.name])
            elif param.default is not None:
                provider_config[param.name] = param.default

        if self._is_chat_completion_provider(provider_name):
            provider_config["provider_name"] = provider_name

        is_valid, errors = provider_class.validate_config(provider_config)
        if not is_valid:
            error_msg = f"服务商 [{section_name}] 配置错误:\n" + "\n".join(f"  - {e}" for e in errors)
            raise ValueError(error_msg)

        self._credentials[provider_name] = provider_config

    def _ensure_provider_config(self, provider_name: str, credential_file: str):
        if os.path.exists(credential_file):
            with open(credential_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        else:
            lines = []

        section_name = self._get_provider_section_name(provider_name)
        section_exists = any(f"[{section_name}]" in line for line in lines)

        if not section_exists:
            provider_class = self._get_provider_class(provider_name)
            if provider_class:
                lines.append("\n")
                lines.extend(self._build_provider_config_lines(
                    provider_name,
                    provider_class,
                    trailing_newline=True,
                ))

                with open(credential_file, "w", encoding="utf-8") as f:
                    f.writelines(lines)

                raise UserWarning(f"已添加 {provider_name} 配置段到 {credential_file}，请填入凭据信息!")

    def _build_provider_config_lines(
        self,
        provider_name: str,
        provider_class: Type[BaseApi],
        trailing_newline: bool = False,
    ) -> list[str]:
        line_end = "\n" if trailing_newline else ""
        lines = [f"[{provider_name.upper()}]{line_end}"]

        for param in provider_class.get_params():
            config_key = param.to_config_key()
            for comment in self._build_param_config_comments(config_key, param.description):
                lines.append(f"# {comment}{line_end}")
            default_value = "" if param.default is None else str(param.default)
            lines.append(f"{config_key} = {default_value}{line_end}")

        return lines

    def _build_param_config_comments(self, config_key: str, description: str) -> list[str]:
        comments = [description]
        if config_key == "API_KEY":
            comments.extend([
                "回退语法: API_KEY = key-a,key-b",
                "按从左到右的顺序尝试 API Key。",
            ])
        elif config_key == "MODEL":
            comments.extend([
                "回退语法: MODEL = model-a,model-b",
                "每个 API_KEY 下按从左到右的顺序尝试模型。",
            ])
        elif config_key == "ACCESS_POINT":
            comments.extend([
                "回退语法: ACCESS_POINT = ep-a,ep-b",
                "每个 API_KEY 下按从左到右的顺序尝试访问点。",
            ])
        elif config_key == "BASE_URL":
            comments.append("Use the OpenAI-compatible base URL, usually ending with /v1.")
        return comments

    def _register_designated_provider(self):
        for provider_name in self._designated_providers:
            self._register_provider(provider_name, self._get_provider_class(provider_name))
        self._default_client = self._build_default_client(self._designated_providers)

    def _register_provider(
        self,
        name: str,
        client_class: Type[BaseApi],
        failure_handlers: list[FailureHandler] | None = None,
        **kwargs: Any,
    ):
        self._clients[name] = self._build_configured_provider_client(
            name,
            client_class,
            extra_kwargs=kwargs,
            failure_handlers=failure_handlers,
        )

    def _build_default_client(self, providers: list[str]) -> BaseApi:
        if len(providers) == 1:
            return self._clients[providers[0]]

        entries: list[ProviderFallbackEntry] = []
        for provider_name in providers:
            client = self._build_configured_provider_client(
                provider_name,
                self._get_provider_class(provider_name),
                failure_handlers=[],
            )
            entries.append(ProviderFallbackEntry(provider_name=provider_name, client=client))
        return ProviderFallbackApi(entries, failure_handlers=self._failure_handlers)

    def _build_configured_provider_client(
        self,
        name: str,
        client_class: Type[BaseApi],
        extra_kwargs: Dict[str, Any] | None = None,
        failure_handlers: list[FailureHandler] | None = None,
    ) -> BaseApi:
        credential_file = "credentials.config"

        if name.lower() not in self._credentials:
            self._ensure_provider_config(name, credential_file)
            self._load_config()

        creds = self._credentials.get(name.lower(), {})
        client_kwargs = creds.copy()
        if extra_kwargs:
            client_kwargs.update(extra_kwargs)

        is_valid, errors = client_class.validate_config(client_kwargs)
        if not is_valid:
            error_msg = f"服务商 '{name}' 参数错误:\n" + "\n".join(f"  - {e}" for e in errors)
            raise ValueError(error_msg)

        return self._build_provider_client(name, client_class, client_kwargs, failure_handlers=failure_handlers)

    def _build_provider_client(
        self,
        name: str,
        client_class: Type[BaseApi],
        client_kwargs: Dict[str, Any],
        failure_handlers: list[FailureHandler] | None = None,
    ) -> BaseApi:
        handlers = self._failure_handlers if failure_handlers is None else failure_handlers
        api_keys: list[str | None] = []
        has_api_key = "api_key" in client_kwargs
        if has_api_key:
            api_keys.extend(self._parse_ordered_targets(client_kwargs["api_key"], name, "api_key"))
        else:
            api_keys.append(None)

        target_param_name = self._get_target_param_name(client_class)
        active_target_param_name: str | None = None
        targets: list[str | None] = []
        if target_param_name is not None and target_param_name in client_kwargs:
            active_target_param_name = target_param_name
            targets.extend(self._parse_ordered_targets(client_kwargs[active_target_param_name], name, active_target_param_name))
        else:
            targets.append(None)

        if len(api_keys) == 1 and len(targets) == 1:
            provider_kwargs = client_kwargs.copy()
            if has_api_key:
                provider_kwargs["api_key"] = api_keys[0]
            if active_target_param_name is not None:
                provider_kwargs[active_target_param_name] = targets[0]
            client = client_class(**provider_kwargs)  # type: ignore
            return self._wrap_provider_client(name, client, handlers)

        entries: list[FallbackEntry] = []
        api_key_varies = len(api_keys) > 1
        for api_key_index, api_key in enumerate(api_keys, start=1):
            for target in targets:
                provider_kwargs = client_kwargs.copy()
                if has_api_key:
                    provider_kwargs["api_key"] = api_key
                if active_target_param_name is not None:
                    provider_kwargs[active_target_param_name] = target
                label = self._build_fallback_label(api_key_index, api_key_varies, target)
                secrets = (api_key,) if has_api_key and api_key is not None else ()
                client = client_class(**provider_kwargs)  # type: ignore
                entries.append(FallbackEntry(
                    target=label,
                    client=self._wrap_provider_client(label, client, []),
                    secrets=secrets,
                ))

        return FallbackApi(name, entries, failure_handlers=handlers)

    def _build_fallback_label(self, api_key_index: int, api_key_varies: bool, target: str | None) -> str:
        if target is None:
            return f"api_key#{api_key_index}"
        if api_key_varies:
            return f"api_key#{api_key_index}:{target}"
        return target

    def _get_target_param_name(self, client_class: Type[BaseApi]) -> Optional[str]:
        if client_class is Doubao:
            return "access_point"
        if client_class.get_param("model") is not None:
            return "model"
        return None

    def _parse_ordered_targets(self, value: Any, provider_name: str, param_name: str) -> list[str]:
        raw_value = str(value)
        targets = [part.strip().strip('"').strip("'") for part in raw_value.split(",")]
        if any(not target for target in targets):
            config_key = param_name.upper()
            raise ValueError(f"服务商 [{provider_name.upper()}] 的 {config_key} 配置包含空值")
        return targets

    def _wrap_provider_client(
        self,
        name: str,
        client: BaseApi,
        failure_handlers: list[FailureHandler] | None = None,
    ) -> BaseApi:
        if isinstance(client, (RetryingApi, FallbackApi, ProviderFallbackApi)):
            return client
        handlers = self._failure_handlers if failure_handlers is None else failure_handlers
        return RetryingApi(name, client, failure_handlers=handlers)

    def register_provider(self, name: str, client: BaseApi):
        if not isinstance(client, BaseApi):
            raise TypeError(f"客户端必须实现 BaseApi 接口，当前类型: {type(client)}")
        self._clients[name] = self._wrap_provider_client(name, client)

    def register_provider_class(self, name: str, client_class: Type[BaseApi], **kwargs):
        self._register_provider(name, client_class, **kwargs)

    def get_client(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> BaseApi:
        if model is not None:
            return self._build_manual_client(provider, model)

        if provider is None:
            if self._default_client is None:
                raise ValueError("默认服务商客户端尚未初始化")
            return self._default_client

        provider = provider.strip().lower()
        if provider not in self._clients:
            available_providers = ", ".join(self._clients.keys())
            raise ValueError(
                f"未找到服务商 '{provider}'，可用的服务商: {available_providers}"
            )

        return self._clients[provider]

    def _build_manual_client(
        self,
        provider: Optional[str],
        model: str,
    ) -> BaseApi:
        if provider is None:
            raise ManualModelSelectionError("指定 model 时必须同时指定 provider")
        if not isinstance(provider, str):
            raise ManualModelSelectionError("参数 'provider' 必须是字符串")
        if not isinstance(model, str):
            raise ManualModelSelectionError("参数 'model' 必须是字符串")

        provider_name = provider.strip().lower()
        model_name = model.strip()
        if not provider_name:
            raise ManualModelSelectionError("参数 'provider' 不能为空")
        if not model_name:
            raise ManualModelSelectionError("参数 'model' 不能为空")
        if "," in model_name:
            raise ManualModelSelectionError("参数 'model' 只能指定一个模型")

        config = self._config
        if config is None:
            raise ManualModelSelectionError("服务商配置尚未加载")

        try:
            provider_class = self._get_provider_class(provider_name)
        except ValueError as exception:
            raise ManualModelSelectionError(str(exception)) from exception

        section_name = self._get_provider_section_name(provider_name)
        if not config.has_section(section_name):
            raise ManualModelSelectionError(
                f"配置文件中未找到服务商 [{section_name}] 的配置段"
            )

        target_param_name = self._get_target_param_name(provider_class)
        if target_param_name is None:
            raise ManualModelSelectionError(
                f"服务商 '{provider_name}' 不支持通过 model 选择模型"
            )

        target_config_key = target_param_name.upper()
        if not config.has_option(section_name, target_config_key):
            raise ManualModelSelectionError(
                f"服务商 [{section_name}] 未配置 {target_config_key}"
            )

        raw_targets = config.get(section_name, target_config_key)
        try:
            configured_targets = self._parse_ordered_targets(
                raw_targets,
                provider_name,
                target_param_name,
            )
        except ValueError as exception:
            raise ManualModelSelectionError(str(exception)) from exception

        if model_name not in configured_targets:
            raise ManualModelSelectionError(
                f"模型 '{model_name}' 未配置在服务商 '{provider_name}' 中"
            )

        provider_config: Dict[str, Any] = {}
        for config_key, raw_value in config.items(section_name):
            if config_key.startswith("#"):
                continue
            provider_config[config_key.lower()] = raw_value

        for param in provider_class.get_params():
            if param.name in provider_config:
                provider_config[param.name] = param.parse_value(provider_config[param.name])
            elif param.default is not None:
                provider_config[param.name] = param.default

        if self._is_chat_completion_provider(provider_name):
            provider_config["provider_name"] = provider_name

        provider_config[target_param_name] = model_name
        is_valid, errors = provider_class.validate_config(provider_config)
        if not is_valid:
            error_msg = f"服务商 [{section_name}] 配置错误:\n" + "\n".join(
                f"  - {error}" for error in errors
            )
            raise ManualModelSelectionError(error_msg)

        return self._build_provider_client(
            provider_name,
            provider_class,
            provider_config,
        )

    def set_designated_provider(self, provider: str):
        providers = self._parse_designated_providers(provider)
        missing_providers = [name for name in providers if name not in self._clients]
        if missing_providers:
            available_providers = ", ".join(self._clients.keys())
            raise ValueError(
                f"无法设置服务商 '{','.join(missing_providers)}'，可用的服务商: {available_providers}"
            )
        self._set_designated_providers(providers)
        self._default_client = self._build_default_client(providers)

    def get_designated_provider(self) -> str:
        return self._designated_provider

    def get_designated_providers(self) -> list[str]:
        return list(self._designated_providers)

    def list_providers(self) -> list[str]:
        return list(self._clients.keys())

    def list_available_provider_models(self) -> list[dict[str, Any]]:
        config = self._config
        if config is None:
            return []

        providers: list[dict[str, Any]] = []
        seen_providers: set[str] = set()
        for section_name in config.sections():
            provider_name = section_name.lower()
            if provider_name in seen_providers:
                continue
            if self._get_provider_section_name(provider_name) != section_name:
                continue
            if not self._is_known_provider(provider_name):
                continue

            models = self._list_available_models_for_provider(
                config,
                provider_name,
                section_name,
            )
            if not models:
                continue

            providers.append({"id": provider_name, "models": models})
            seen_providers.add(provider_name)

        return providers

    def _list_available_models_for_provider(
        self,
        config: configparser.ConfigParser,
        provider_name: str,
        section_name: str,
    ) -> list[str]:
        try:
            provider_class = self._get_provider_class(provider_name)
            target_param_name = self._get_target_param_name(provider_class)
            if target_param_name is None:
                return []

            target_config_key = target_param_name.upper()
            if not config.has_option(section_name, target_config_key):
                return []

            configured_targets = self._parse_ordered_targets(
                config.get(section_name, target_config_key),
                provider_name,
                target_param_name,
            )

            provider_config: Dict[str, Any] = {}
            for config_key, raw_value in config.items(section_name):
                if config_key.startswith("#"):
                    continue
                provider_config[config_key.lower()] = raw_value

            for param in provider_class.get_params():
                if param.name in provider_config:
                    provider_config[param.name] = param.parse_value(provider_config[param.name])
                elif param.default is not None:
                    provider_config[param.name] = param.default

            if "api_key" in provider_config:
                self._parse_ordered_targets(
                    provider_config["api_key"],
                    provider_name,
                    "api_key",
                )

            if self._is_chat_completion_provider(provider_name):
                provider_config["provider_name"] = provider_name

            models: list[str] = []
            for target in configured_targets:
                if target in models:
                    continue
                candidate_config = provider_config.copy()
                candidate_config[target_param_name] = target
                is_valid, _ = provider_class.validate_config(candidate_config)
                if is_valid:
                    models.append(target)
            return models
        except (configparser.Error, TypeError, ValueError):
            return []

    def _is_chat_completion_provider(self, provider_name: str) -> bool:
        return (
            provider_name.startswith(self.CHAT_COMPLETION_PREFIX)
            and len(provider_name) > len(self.CHAT_COMPLETION_PREFIX)
        )

    def _is_known_provider(self, provider_name: str) -> bool:
        return (
            provider_name in self._provider_classes
            or self._is_chat_completion_provider(provider_name)
        )

    def _get_provider_class(self, provider_name: str) -> Type[BaseApi]:
        normalized_name = provider_name.lower()
        if self._is_chat_completion_provider(normalized_name):
            return ChatCompletion

        provider_class = self._provider_classes.get(normalized_name)
        if provider_class is None:
            available_providers = self._format_available_provider_names()
            raise ValueError(
                f"未知服务商 '{provider_name}'，可用的服务商: {available_providers}"
            )
        return provider_class

    def _get_provider_section_name(self, provider_name: str) -> str:
        return provider_name.upper()

    def _format_available_provider_names(self) -> str:
        available_providers = list(self._provider_classes.keys())
        available_providers.append(f"{self.CHAT_COMPLETION_PREFIX}<alias>")
        return ", ".join(available_providers)
