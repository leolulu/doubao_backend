import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Callable, Literal, cast, override

import requests

from api.base_api import BaseApi
from api.streaming import IncompleteStreamError
from api.timeouts import attempt_deadline, reset_attempt_deadline, set_attempt_deadline


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
    """记录模型回退中失败的目标和异常。"""

    targets: list[str]
    exceptions: list[Exception]
    secret_values: tuple[str, ...] = ()


@dataclass
class ModelFallbackResult:
    """Model and earlier failed attempts for one successful provider call."""

    model: str | None = None
    failed_attempts: FallbackEvent | None = None


ProviderFallbackOutcome = Literal["success", "failed", "interrupted", "cancelled"]


@dataclass(frozen=True)
class ProviderFallbackEvent(FailureEvent):
    """Final result of a provider chain that encountered a failure."""

    providers: list[str]
    exceptions: list[Exception]
    secret_values: tuple[str, ...] = ()
    outcome: ProviderFallbackOutcome = "failed"
    model_result: ModelFallbackResult | None = None


FailureHandler = Callable[[FailureEvent], None]
Sleeper = Callable[[float], None]
Clock = Callable[[], float]
PostRequest = Callable[..., requests.Response]


class FeishuNotifier:
    """通过飞书自定义机器人发送最终失败和供应商回退结果。"""

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

    def _format_provider_fallback_message(self, event: ProviderFallbackEvent) -> str:
        providers = event.providers
        title = "大模型供应商已切换" if len(providers) > 1 else "大模型供应商回退链彻底失败"
        lines = [
            title,
            f"供应商回退链: {' -> '.join(providers)}",
        ]
        for index, (provider, exception) in enumerate(zip(providers, event.exceptions)):
            lines.extend(("", f"失败供应商: {provider}"))
            if index + 1 < len(providers):
                lines.append(f"切换目标: {providers[index + 1]}")
            fallback_event = getattr(exception, "fallback_event", None)
            if isinstance(fallback_event, FallbackEvent):
                targets = fallback_event.targets
                exceptions = fallback_event.exceptions
            else:
                targets = [provider]
                exceptions = [exception]
            lines.extend(self._format_model_failures(targets, exceptions, event.secret_values))
        outcome = {
            "success": "成功",
            "failed": "失败",
            "interrupted": "失败（流式输出中断）",
            "cancelled": "未完成（流式请求提前关闭）",
        }[event.outcome]
        lines.extend(("", f"最终供应商: {providers[-1]}"))
        model_result = event.model_result
        if model_result is not None:
            failed_attempts = model_result.failed_attempts
            if failed_attempts is not None:
                lines.extend(self._format_model_failures(
                    failed_attempts.targets,
                    failed_attempts.exceptions,
                    event.secret_values + failed_attempts.secret_values,
                ))
            if model_result.model is not None:
                lines.append(f"最终模型: {model_result.model}")
        lines.append(f"最终结果: {outcome}")
        return "\n".join(lines)

    def _format_model_failures(
        self,
        targets: list[str],
        exceptions: list[Exception],
        secret_values: tuple[str, ...],
    ) -> list[str]:
        lines = [f"失败链路: {' -> '.join(targets)}", "失败明细:"]
        for target, exception in zip(targets, exceptions):
            lines.append(f"- {target}: {type(exception).__name__}: {self._format_reason(exception, secret_values)}")
        return lines

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

    DEFAULT_MAX_RETRIES: int = 3
    DEFAULT_RETRY_DELAY_SECONDS: float = 5.0
    DEFAULT_TARGET_TIMEOUT_SECONDS: float = 120.0
    # 部分中转用 HTTP 567 表示上游分组负载饱和。
    RETRYABLE_STATUS_CODES: set[int] = {408, 409, 425, 500, 502, 503, 504, 567}
    STATUS_CODE_PATTERN: re.Pattern[str] = re.compile(r"(?<!\d)(\d{3})(?!\d)")

    def __init__(
        self,
        provider_name: str,
        client: BaseApi,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
        failure_handlers: list[FailureHandler] | None = None,
        sleeper: Sleeper = time.sleep,
        clock: Clock = time.monotonic,
        target_timeout_seconds: float = DEFAULT_TARGET_TIMEOUT_SECONDS,
        *,
        model: str | None = None,
    ) -> None:
        self.provider_name: str = provider_name
        self.client: BaseApi = client
        self.model: str | None = model
        self.max_retries: int = max_retries
        self.retry_delay_seconds: float = retry_delay_seconds
        self.failure_handlers: list[FailureHandler] = failure_handlers or []
        self.sleeper: Sleeper = sleeper
        self.clock: Clock = clock
        self.target_timeout_seconds: float = target_timeout_seconds

    @override
    def reason(self, messages: list[dict[str, str]]) -> str:
        deadline = self.clock() + self.target_timeout_seconds
        last_exception: Exception | None = None
        for retry_count in range(self.max_retries + 1):
            if retry_count > 0 and self._remaining_seconds(deadline) <= 0:
                raise self._budget_exhausted(last_exception)
            try:
                with attempt_deadline(deadline):
                    return self.client.reason(messages)
            except Exception as exception:
                last_exception = exception
                retry_delay = self._retry_delay(retry_count, exception, deadline)
                self._handle_failure(
                    RetryEvent(
                        provider_name=self.provider_name,
                        will_retry=retry_delay is not None,
                        attempt_number=retry_count + 1,
                        max_retries=self.max_retries,
                        delay_seconds=retry_delay if retry_delay is not None else 0.0,
                        exception=exception,
                    )
                )
                if retry_delay is None:
                    raise
                self.sleeper(retry_delay)

        raise RuntimeError("重试流程异常结束")

    @override
    def reason_stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        deadline = self.clock() + self.target_timeout_seconds
        last_exception: Exception | None = None
        for retry_count in range(self.max_retries + 1):
            if retry_count > 0 and self._remaining_seconds(deadline) <= 0:
                raise self._budget_exhausted(last_exception)
            yielded_content = False
            stream = None
            deadline_active = True
            token = set_attempt_deadline(deadline)
            try:
                stream = self.client.reason_stream(messages)
                for chunk in stream:
                    if not chunk:
                        continue
                    if not yielded_content:
                        yielded_content = True
                        # 已开始输出可见文本，不再受单目标时限约束，避免截断回答。
                        reset_attempt_deadline(token)
                        deadline_active = False
                    yield chunk
                return
            except Exception as exception:
                last_exception = exception
                retry_delay = (
                    None
                    if yielded_content
                    else self._retry_delay(retry_count, exception, deadline)
                )
                self._handle_failure(
                    RetryEvent(
                        provider_name=self.provider_name,
                        will_retry=retry_delay is not None,
                        attempt_number=retry_count + 1,
                        max_retries=self.max_retries,
                        delay_seconds=retry_delay if retry_delay is not None else 0.0,
                        exception=exception,
                    )
                )
                if retry_delay is None:
                    raise
                self.sleeper(retry_delay)
            finally:
                if deadline_active:
                    reset_attempt_deadline(token)
                close = getattr(stream, "close", None)
                if callable(close):
                    close()

    def _remaining_seconds(self, deadline: float) -> float:
        return deadline - self.clock()

    def _retry_delay(
        self,
        retry_count: int,
        exception: Exception,
        deadline: float,
    ) -> float | None:
        """本次失败后实际等待的时间；None 表示不再重试。"""
        if retry_count >= self.max_retries or not self._should_retry(exception):
            return None
        if self._remaining_seconds(deadline) <= self.retry_delay_seconds:
            return None
        return self.retry_delay_seconds

    def _budget_exhausted(self, last_exception: Exception | None) -> Exception:
        if last_exception is not None:
            return last_exception
        return RuntimeError("重试流程异常结束")

    def _should_retry(self, exception: Exception) -> bool:
        if isinstance(exception, (IncompleteStreamError, JSONDecodeError, requests.exceptions.JSONDecodeError)):
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
