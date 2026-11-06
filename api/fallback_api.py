from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import override

from api.base_api import BaseApi
from api.retrying_api import FailureHandler, FallbackEvent, ModelFallbackResult, RetryingApi


@dataclass(frozen=True)
class FallbackEntry:
    """One target in a fallback chain."""

    target: str
    client: BaseApi
    secrets: tuple[str, ...] = ()


class FallbackApi(BaseApi):
    """Try multiple clients in order and report only after the whole chain fails."""

    def __init__(
        self,
        provider_name: str,
        entries: Sequence[FallbackEntry],
        failure_handlers: list[FailureHandler] | None = None,
    ) -> None:
        if not entries:
            raise ValueError("fallback chain cannot be empty")
        self.provider_name: str = provider_name
        self.entries: list[FallbackEntry] = list(entries)
        self.failure_handlers: list[FailureHandler] = failure_handlers or []

    @override
    def reason(
        self,
        messages: list[dict[str, str]],
        *,
        model_result: ModelFallbackResult | None = None,
    ) -> str:
        exceptions: list[Exception] = []
        for entry in self.entries:
            try:
                response = entry.client.reason(messages)
            except Exception as exception:
                exceptions.append(exception)
            else:
                if model_result is not None:
                    self._record_success(model_result, entry, exceptions)
                return response

        event = self._build_failure_event(exceptions)
        self._handle_failure(event)
        self._attach_fallback_event(exceptions[-1], event)
        raise exceptions[-1]

    @override
    def reason_stream(
        self,
        messages: list[dict[str, str]],
        *,
        model_result: ModelFallbackResult | None = None,
    ) -> Iterator[str]:
        exceptions: list[Exception] = []

        for entry in self.entries:
            yielded_content = False
            stream = None
            try:
                stream = entry.client.reason_stream(messages)
                for chunk in stream:
                    if not chunk:
                        continue
                    yielded_content = True
                    yield chunk
            except Exception as exception:
                exceptions.append(exception)
                if yielded_content:
                    break
            else:
                if model_result is not None:
                    self._record_success(model_result, entry, exceptions)
                return
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()

        event = self._build_failure_event(exceptions)
        self._handle_failure(event)
        self._attach_fallback_event(exceptions[-1], event)
        raise exceptions[-1]

    def _record_success(
        self,
        model_result: ModelFallbackResult,
        entry: FallbackEntry,
        exceptions: list[Exception],
    ) -> None:
        client = entry.client
        model_result.model = client.model if isinstance(client, RetryingApi) else None
        model_result.failed_attempts = self._build_failure_event(exceptions) if exceptions else None

    def _build_failure_event(self, exceptions: list[Exception]) -> FallbackEvent:
        failed_entries = self.entries[:len(exceptions)]
        return FallbackEvent(
            provider_name=self.provider_name,
            will_retry=False,
            targets=[entry.target for entry in failed_entries],
            exceptions=exceptions,
            secret_values=tuple(secret for entry in failed_entries for secret in entry.secrets),
        )

    def _handle_failure(self, event: FallbackEvent) -> None:
        for handler in self.failure_handlers:
            try:
                handler(event)
            except Exception as exception:
                print(f"failure handler failed: {type(exception).__name__}")

    def _attach_fallback_event(self, exception: Exception, event: FallbackEvent) -> None:
        try:
            setattr(exception, "fallback_event", event)
        except Exception:
            pass
