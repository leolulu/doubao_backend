from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import override

from api.base_api import BaseApi
from api.retrying_api import (
    FailureHandler,
    FallbackEvent,
    ProviderFallbackEvent,
    ProviderSwitchEvent,
)


@dataclass(frozen=True)
class ProviderFallbackEntry:
    provider_name: str
    client: BaseApi


class ProviderFallbackApi(BaseApi):
    """Try configured providers in priority order."""

    def __init__(
        self,
        entries: Sequence[ProviderFallbackEntry],
        failure_handlers: list[FailureHandler] | None = None,
    ) -> None:
        if not entries:
            raise ValueError("provider fallback chain cannot be empty")
        self.provider_name: str = "provider-chain"
        self.entries: list[ProviderFallbackEntry] = list(entries)
        self.failure_handlers: list[FailureHandler] = failure_handlers or []

    @override
    def reason(self, messages: list[dict[str, str]]) -> str:
        exceptions: list[Exception] = []
        for index, entry in enumerate(self.entries):
            try:
                return entry.client.reason(messages)
            except Exception as exception:
                exceptions.append(exception)
                next_entry = self._next_entry(index)
                if next_entry is not None:
                    self._handle_failure(
                        self._build_switch_event(entry, next_entry, exception)
                    )

        event = ProviderFallbackEvent(
            provider_name=self.provider_name,
            will_retry=False,
            providers=[entry.provider_name for entry in self.entries],
            exceptions=exceptions,
            secret_values=self._collect_secret_values(exceptions),
        )
        self._handle_failure(event)
        raise exceptions[-1]

    @override
    def reason_stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        exceptions: list[Exception] = []
        attempted_entries: list[ProviderFallbackEntry] = []

        for index, entry in enumerate(self.entries):
            attempted_entries.append(entry)
            yielded_content = False
            stream = None
            try:
                stream = entry.client.reason_stream(messages)
                for chunk in stream:
                    if not chunk:
                        continue
                    yielded_content = True
                    yield chunk
                return
            except Exception as exception:
                exceptions.append(exception)
                if yielded_content:
                    break
                next_entry = self._next_entry(index)
                if next_entry is not None:
                    self._handle_failure(
                        self._build_switch_event(entry, next_entry, exception)
                    )
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()

        event = ProviderFallbackEvent(
            provider_name=self.provider_name,
            will_retry=False,
            providers=[entry.provider_name for entry in attempted_entries],
            exceptions=exceptions,
            secret_values=self._collect_secret_values(exceptions),
        )
        self._handle_failure(event)
        raise exceptions[-1]

    def _next_entry(self, current_index: int) -> ProviderFallbackEntry | None:
        next_index = current_index + 1
        if next_index >= len(self.entries):
            return None
        return self.entries[next_index]

    def _build_switch_event(
        self,
        failed_entry: ProviderFallbackEntry,
        next_entry: ProviderFallbackEntry,
        exception: Exception,
    ) -> ProviderSwitchEvent:
        fallback_event = self._get_fallback_event(exception)
        targets = fallback_event.targets if fallback_event is not None else [failed_entry.provider_name]
        exceptions = fallback_event.exceptions if fallback_event is not None else [exception]
        secret_values = fallback_event.secret_values if fallback_event is not None else ()
        return ProviderSwitchEvent(
            provider_name=failed_entry.provider_name,
            will_retry=False,
            from_provider=failed_entry.provider_name,
            to_provider=next_entry.provider_name,
            targets=targets,
            exceptions=exceptions,
            secret_values=secret_values,
        )

    def _collect_secret_values(self, exceptions: list[Exception]) -> tuple[str, ...]:
        secrets: list[str] = []
        for exception in exceptions:
            fallback_event = self._get_fallback_event(exception)
            if fallback_event is not None:
                secrets.extend(fallback_event.secret_values)
        return tuple(secrets)

    def _get_fallback_event(self, exception: Exception) -> FallbackEvent | None:
        fallback_event = getattr(exception, "fallback_event", None)
        if isinstance(fallback_event, FallbackEvent):
            return fallback_event
        return None

    def _handle_failure(self, event: ProviderSwitchEvent | ProviderFallbackEvent) -> None:
        for handler in self.failure_handlers:
            try:
                handler(event)
            except Exception as exception:
                print(f"failure handler failed: {type(exception).__name__}")
