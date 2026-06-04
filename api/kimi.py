from typing import Any, Dict, List

import requests

from api.base_api import BaseApi
from api.param_schema import ParamType, ProviderParam


class Kimi(BaseApi):
    """Kimi Code provider.

    The default protocol is Anthropic Compatible because Kimi Code documents
    OpenAI Compatible client allowlist restrictions for some integrations.
    """

    ANTHROPIC_BASE_URL = "https://api.kimi.com/coding"
    OPENAI_BASE_URL = "https://api.kimi.com/coding/v1"
    DEFAULT_MODEL = "kimi-for-coding"
    DEFAULT_PROTOCOL = "anthropic"
    DEFAULT_MAX_TOKENS = 32768
    DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
    USER_AGENT = "claude-code/0.1.0"
    SUPPORTED_PROTOCOLS = {"anthropic", "openai"}

    @classmethod
    def get_params(cls) -> List[ProviderParam]:
        return [
            ProviderParam(
                name="api_key",
                param_type=ParamType.STRING,
                required=True,
                description="Kimi Code API key"
            ),
            ProviderParam(
                name="model",
                param_type=ParamType.STRING,
                required=True,
                default=cls.DEFAULT_MODEL,
                description="Model name, e.g. kimi-for-coding or kimi-k2.6"
            ),
        ]

    @classmethod
    def validate_config(cls, config: Dict[str, Any]) -> tuple[bool, List[str]]:
        is_valid, errors = super().validate_config(config)

        protocol = str(config.get("protocol", cls.DEFAULT_PROTOCOL)).strip().lower()
        if protocol and protocol not in cls.SUPPORTED_PROTOCOLS:
            errors.append(
                f"protocol must be one of: {', '.join(sorted(cls.SUPPORTED_PROTOCOLS))}"
            )

        max_tokens = config.get("max_tokens", cls.DEFAULT_MAX_TOKENS)
        if isinstance(max_tokens, int) and max_tokens <= 0:
            errors.append("max_tokens must be greater than 0")

        return is_valid and not errors, errors

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        protocol: str = DEFAULT_PROTOCOL,
        base_url: str = "",
        max_tokens: int = DEFAULT_MAX_TOKENS,
        anthropic_version: str = DEFAULT_ANTHROPIC_VERSION,
    ) -> None:
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.protocol = (protocol or self.DEFAULT_PROTOCOL).strip().lower()
        if self.protocol not in self.SUPPORTED_PROTOCOLS:
            raise ValueError(f"Unsupported Kimi protocol: {protocol}")
        self.base_url = self._resolve_base_url(base_url)
        self.max_tokens = max_tokens
        self.anthropic_version = anthropic_version or self.DEFAULT_ANTHROPIC_VERSION

    def reason(self, messages: List[Dict[str, str]]) -> str:
        if self.protocol == "openai":
            return self._reason_openai(messages)
        return self._reason_anthropic(messages)

    def _resolve_base_url(self, base_url: str) -> str:
        if base_url:
            return base_url.rstrip("/")
        if self.protocol == "openai":
            return self.OPENAI_BASE_URL
        return self.ANTHROPIC_BASE_URL

    def _reason_openai(self, messages: List[Dict[str, str]]) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": self.USER_AGENT,
        }
        data = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
        }

        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            result = response.json()
            choice = result["choices"][0]
            content = choice["message"].get("content", "")
            if content:
                return content
            if choice.get("finish_reason") == "length":
                raise Exception(
                    "Kimi API returned no final content because max_tokens was exhausted"
                )
            return content
        raise Exception(f"Kimi API call failed: {response.status_code}, {response.text}")

    def _reason_anthropic(self, messages: List[Dict[str, str]]) -> str:
        url = self._anthropic_messages_url()
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.anthropic_version,
            "Content-Type": "application/json",
            "User-Agent": self.USER_AGENT,
        }
        data = self._build_anthropic_payload(messages)

        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            return self._extract_anthropic_text(response.json())
        raise Exception(f"Kimi API call failed: {response.status_code}, {response.text}")

    def _anthropic_messages_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/messages"
        return f"{self.base_url}/v1/messages"

    def _build_anthropic_payload(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        system_messages: list[str] = []
        anthropic_messages: list[Dict[str, str]] = []

        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            if role == "system":
                system_messages.append(content)
            else:
                anthropic_messages.append({"role": role, "content": content})

        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": anthropic_messages,
        }
        if system_messages:
            payload["system"] = "\n\n".join(system_messages)
        return payload

    def _extract_anthropic_text(self, result: Dict[str, Any]) -> str:
        content = result.get("content")
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            text_parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            text = "".join(text_parts)
            if text:
                return text

        raise Exception(f"Kimi API returned unexpected response: {result}")
