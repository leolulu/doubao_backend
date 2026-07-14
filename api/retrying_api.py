import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Callable, cast, override

import requests

from api.base_api import BaseApi
from api.streaming import IncompleteStreamError


@dataclass(frozen=True)
class FailureEvent:
    provider_name: str
    will_retry: bool


@dataclass(frozen=True)
class RetryEvent(FailureEvent):
    """统一失败事件，后续可用于接入通知、日志或监控。"""

    attempt_number: int
    max_retries: int
    delay_seconds: float
    exception: Exception


@dataclass(frozen=True)
class FallbackEvent(FailureEvent):
    """整条回退链彻底失败时的统一事件。"""

    targets: list[str]
    exceptions: list[Exception]
    secret_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderSwitchEvent(FailureEvent):
    """A provider failed completely and traffic is moving to the next provider."""

    from_provider: str
    to_provider: str
    targets: list[str]
    exceptions: list[Exception]
    secret_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderFallbackEvent(FailureEvent):
    """All configured providers failed."""

    providers: list[str]
    exceptions: list[Exception]
    secret_values: tuple[str, ...] = ()


FailureHandler = Callable[[FailureEvent], None]
Sleeper = Callable[[float], None]
PostRequest = Callable[..., requests.Response]


class FeishuNotifier:
    """通过飞书自定义机器人发送最终失败通知。"""

    ALLOWED_WEBHOOK_PREFIXES: tuple[str, ...] = (
        "https://open.feishu.cn/open-apis/bot/v2/hook/",
        "https://open.larksuite.com/open-apis/bot/v2/hook/",
    )
    SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"https?://\S+", re.IGNORECASE),
        re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]+"),
        re.compile(r"(?i)\b(api[_-]?key|token|authorization)\s*[:=]\s*[^\s,;]+"),
        re.compile(r"\bms-[0-9a-fA-F-]{32,}\b"),
        re.compile(r"\b[A-Za-z0-9._-]{40,}\b"),
    )

    def __init__(self, webhook_url: str, post_request: PostRequest = requests.post) -> None:
        if not webhook_url.startswith(self.ALLOWED_WEBHOOK_PREFIXES):
            raise ValueError("飞书 webhook 地址必须使用飞书或 Lark 官方机器人地址")
        self.webhook_url: str = webhook_url
        self.post_request: PostRequest = post_request

    def notify_failure(self, event: FailureEvent) -> None:
        if event.will_retry:
            return

        try:
            response = self.post_request(
                self.webhook_url,
                headers={"Content-Type": "application/json"},
                json={
                    "msg_type": "text",
                    "content": {
                        "text": self._format_message(event)
                    },
                },
                timeout=10,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as exception:
            response = exception.response
            if response is not None:
                raise RuntimeError(f"飞书通知请求失败: HTTP {response.status_code}") from exception
            raise RuntimeError(f"飞书通知请求失败: {type(exception).__name__}") from exception

        try:
            raw_result = cast(object, response.json())
        except ValueError as exception:
            raise RuntimeError("飞书通知响应解析失败") from exception
        if not isinstance(raw_result, dict):
            raise RuntimeError("飞书通知响应格式错误")

        result = cast(dict[str, object], raw_result)
        code = result.get("code")
        if code != 0:
            msg = result.get("msg", "")
            raise RuntimeError(f"飞书通知发送失败: {code}, {msg}")

    def _format_message(self, event: FailureEvent) -> str:
        if isinstance(event, ProviderSwitchEvent):
            return self._format_provider_switch_message(event)
        if isinstance(event, ProviderFallbackEvent):
            return self._format_provider_fallback_message(event)
        if isinstance(event, FallbackEvent):
            return self._format_fallback_message(event)
        if isinstance(event, RetryEvent):
            return self._format_retry_message(event)
        raise TypeError(f"未知失败事件类型: {type(event).__name__}")

    def _format_retry_message(self, event: RetryEvent) -> str:
        retry_count = max(event.attempt_number - 1, 0)
        return "\n".join([
            "大模型请求彻底失败",
            f"渠道: {event.provider_name}",
            f"请求次数: {event.attempt_number}",
            f"已重试次数: {retry_count}/{event.max_retries}",
            f"失败类型: {type(event.exception).__name__}",
            f"失败原因摘要: {self._format_reason(event.exception)}",
        ])

    def _format_fallback_message(self, event: FallbackEvent) -> str:
        targets = event.targets
        exceptions = event.exceptions
        lines = [
            "大模型请求彻底失败",
            f"渠道: {event.provider_name}",
            f"回退链: {' -> '.join(targets)}",
            "失败明细:",
        ]
        for target, exception in zip(targets, exceptions):
            lines.append(f"- {target}: {type(exception).__name__}: {self._format_reason(exception, event.secret_values)}")
        return "\n".join(lines)

    def _format_provider_switch_message(self, event: ProviderSwitchEvent) -> str:
        lines = [
            "大模型供应商已切换",
            f"失败供应商: {event.from_provider}",
            f"切换目标: {event.to_provider}",
            f"失败链路: {' -> '.join(event.targets)}",
            "失败明细:",
        ]
        for target, exception in zip(event.targets, event.exceptions):
            lines.append(
                f"- {target}: {type(exception).__name__}: "
                f"{self._format_reason(exception, event.secret_values)}"
            )
        return "\n".join(lines)

    def _format_provider_fallback_message(self, event: ProviderFallbackEvent) -> str:
        lines = [
            "大模型供应商回退链彻底失败",
            f"供应商回退链: {' -> '.join(event.providers)}",
            "失败明细:",
        ]
        for provider, exception in zip(event.providers, event.exceptions):
            fallback_event = getattr(exception, "fallback_event", None)
            if isinstance(fallback_event, FallbackEvent):
                lines.append(f"- {provider}:")
                for target, target_exception in zip(fallback_event.targets, fallback_event.exceptions):
                    lines.append(
                        f"  - {target}: {type(target_exception).__name__}: "
                        f"{self._format_reason(target_exception, event.secret_values)}"
                    )
            else:
                lines.append(
                    f"- {provider}: {type(exception).__name__}: "
                    f"{self._format_reason(exception, event.secret_values)}"
                )
        return "\n".join(lines)

    def _format_reason(self, exception: Exception, secret_values: tuple[str, ...] = ()) -> str:
        reason = str(exception).strip()
        for secret in sorted({secret for secret in secret_values if secret}, key=len, reverse=True):
            reason = reason.replace(secret, "[redacted]")
        for pattern in self.SECRET_PATTERNS:
            reason = pattern.sub("[redacted]", reason)
        if len(reason) <= 300:
            return reason
        return f"{reason[:300]}..."


class RetryingApi(BaseApi):
    """为所有服务商统一提供重试能力的透明代理。"""

    DEFAULT_MAX_RETRIES: int = 5
    DEFAULT_RETRY_DELAY_SECONDS: float = 5.0
    RETRYABLE_STATUS_CODES: set[int] = {408, 409, 425, 429, 500, 502, 503, 504}
    STATUS_CODE_PATTERN: re.Pattern[str] = re.compile(r"(?<!\d)(\d{3})(?!\d)")

    def __init__(
        self,
        provider_name: str,
        client: BaseApi,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
        failure_handlers: list[FailureHandler] | None = None,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        self.provider_name: str = provider_name
        self.client: BaseApi = client
        self.max_retries: int = max_retries
        self.retry_delay_seconds: float = retry_delay_seconds
        self.failure_handlers: list[FailureHandler] = failure_handlers or []
        self.sleeper: Sleeper = sleeper

    @override
    def reason(self, messages: list[dict[str, str]]) -> str:
        for retry_count in range(self.max_retries + 1):
            try:
                return self.client.reason(messages)
            except Exception as exception:
                will_retry = retry_count < self.max_retries and self._should_retry(exception)
                self._handle_failure(
                    RetryEvent(
                        provider_name=self.provider_name,
                        will_retry=will_retry,
                        attempt_number=retry_count + 1,
                        max_retries=self.max_retries,
                        delay_seconds=self.retry_delay_seconds if will_retry else 0,
                        exception=exception,
                    )
                )
                if not will_retry:
                    raise
                self.sleeper(self.retry_delay_seconds)

        raise RuntimeError("重试流程异常结束")

    @override
    def reason_stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        for retry_count in range(self.max_retries + 1):
            yielded_content = False
            stream = None
            try:
                stream = self.client.reason_stream(messages)
                for chunk in stream:
                    if not chunk:
                        continue
                    yielded_content = True
                    yield chunk
                return
            except Exception as exception:
                will_retry = (
                    not yielded_content
                    and retry_count < self.max_retries
                    and self._should_retry(exception)
                )
                self._handle_failure(
                    RetryEvent(
                        provider_name=self.provider_name,
                        will_retry=will_retry,
                        attempt_number=retry_count + 1,
                        max_retries=self.max_retries,
                        delay_seconds=self.retry_delay_seconds if will_retry else 0,
                        exception=exception,
                    )
                )
                if not will_retry:
                    raise
                self.sleeper(self.retry_delay_seconds)
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()

        raise RuntimeError("流式重试流程异常结束")

    def _should_retry(self, exception: Exception) -> bool:
        if isinstance(exception, IncompleteStreamError):
            return True
        if isinstance(exception, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
            return True

        if isinstance(exception, requests.exceptions.RequestException):
            response = exception.response
            if response is not None:
                return response.status_code in self.RETRYABLE_STATUS_CODES
            return False

        status_code = self._extract_status_code(exception)
        return status_code in self.RETRYABLE_STATUS_CODES

    def _extract_status_code(self, exception: Exception) -> int | None:
        for match in self.STATUS_CODE_PATTERN.finditer(str(exception)):
            status_code = int(match.group(1))
            if 400 <= status_code <= 599:
                return status_code
        return None

    def _handle_failure(self, event: RetryEvent) -> None:
        for handler in self.failure_handlers:
            try:
                handler(event)
            except Exception as exception:
                print(f"失败处理器执行失败: {type(exception).__name__}")
