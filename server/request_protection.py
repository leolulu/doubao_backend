import configparser
import ipaddress
import json
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field, fields
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Callable
from urllib.parse import unquote

from flask import Flask, Response, g, request


PROJECT_ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProtectionSettings:
    enabled: bool = True
    observe_only: bool = False
    chat_ip_per_minute: int = 120
    chat_global_per_minute: int = 240
    chat_ip_burst: int = 12
    chat_global_burst: int = 24
    chat_ip_concurrency: int = 8
    chat_global_concurrency: int = 12
    auxiliary_ip_per_minute: int = 120
    auxiliary_global_per_minute: int = 600
    auxiliary_ip_burst: int = 30
    auxiliary_global_burst: int = 120
    scan_window_seconds: int = 60
    scan_threshold: int = 5
    ban_seconds: int = 900
    max_sources: int = 4096
    idle_seconds: int = 1800
    trusted_proxy_networks: tuple[str, ...] = ()


def load_protection_settings(path: Path | None = None) -> ProtectionSettings:
    path = path if path is not None else PROJECT_ROOT / "protection.config"
    if not path.exists():
        return ProtectionSettings()
    parser = configparser.ConfigParser(interpolation=None)
    with path.open(encoding="utf-8") as file:
        parser.read_file(file)
    if parser.sections() != ["protection"]:
        raise ValueError("protection.config 必须只包含 [protection] 配置段")
    values = {}
    names = {item.name for item in fields(ProtectionSettings)}
    section = parser["protection"]
    unknown = set(section) - names
    if unknown:
        raise ValueError(f"未知防护配置项: {', '.join(sorted(unknown))}")
    for name in section:
        if name in {"enabled", "observe_only"}:
            values[name] = section.getboolean(name)
        elif name == "trusted_proxy_networks":
            networks = tuple(value.strip() for value in section[name].split(",") if value.strip())
            for network in networks:
                ipaddress.ip_network(network)
            values[name] = networks
        else:
            value = section.getint(name)
            if value <= 0:
                raise ValueError(f"防护配置项 {name} 必须大于 0")
            values[name] = value
    settings = ProtectionSettings(**values)
    longest_refill = max(
        settings.chat_ip_burst * 60 / settings.chat_ip_per_minute,
        settings.auxiliary_ip_burst * 60 / settings.auxiliary_ip_per_minute,
        settings.scan_window_seconds,
    )
    if settings.idle_seconds < longest_refill:
        raise ValueError("idle_seconds 不得小于额度恢复时间或扫描统计窗口")
    return settings


def configure_protection_logging() -> None:
    if logger.handlers:
        return
    path = PROJECT_ROOT / "logs" / "request_protection.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8", delay=True,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


@dataclass
class _Bucket:
    tokens: float
    updated_at: float

    def refill(self, now: float, per_minute: int, burst: int) -> None:
        self.tokens = min(burst, self.tokens + (now - self.updated_at) * per_minute / 60)
        self.updated_at = now


@dataclass
class _Source:
    last_seen: float
    buckets: dict[str, _Bucket] = field(default_factory=dict)
    scans: deque[float] = field(default_factory=deque)
    banned_until: float = 0
    active: int = 0
    active_chat: int = 0
    logged_at: float | None = None
    suppressed: int = 0


@dataclass(frozen=True)
class Denial:
    status: int
    reason: str
    retry_after: int = 1


class _Lease:
    def __init__(self, guard: "RequestProtection", source: _Source, kind: str) -> None:
        self.guard = guard
        self.source = source
        self.kind = kind
        self.released = False

    def release(self) -> None:
        with self.guard._lock:
            if self.released:
                return
            self.released = True
            self.source.active -= 1
            self.source.last_seen = self.guard._clock()
            if self.kind == "chat":
                self.source.active_chat -= 1
                self.guard._active_chat -= 1
            else:
                self.guard._active_refresh -= 1


class RequestProtection:
    """Single-process admission control; each accepted stream owns a closing lease."""

    def __init__(
        self,
        settings: ProtectionSettings | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or ProtectionSettings()
        self._clock = clock
        self._lock = Lock()
        self._sources: dict[str, _Source] = {}
        self._global_buckets: dict[str, _Bucket] = {}
        self._active_chat = 0
        self._active_refresh = 0
        self._next_cleanup = 0.0
        self._capacity_logged_at: float | None = None
        self._trusted_proxies = tuple(
            ipaddress.ip_network(network) for network in self.settings.trusted_proxy_networks
        )

    def client_ip(self, remote_addr: str | None, forwarded_for: str | None = None) -> str:
        try:
            peer = ipaddress.ip_address(remote_addr or "")
        except ValueError:
            return "unknown"
        if isinstance(peer, ipaddress.IPv6Address) and peer.ipv4_mapped:
            peer = peer.ipv4_mapped
        if not self._trusted(peer) or not forwarded_for or len(forwarded_for) > 2048:
            return str(peer)
        parts = forwarded_for.split(",")
        if len(parts) > 16:
            return str(peer)
        # Walk only the trusted suffix. Client-supplied prefixes cannot override
        # the first untrusted address appended by a correctly configured proxy.
        for part in reversed(parts):
            if not self._trusted(peer):
                break
            try:
                peer = ipaddress.ip_address(part.strip())
            except ValueError:
                return self.client_ip(remote_addr)
            if isinstance(peer, ipaddress.IPv6Address) and peer.ipv4_mapped:
                peer = peer.ipv4_mapped
        return str(peer)

    def _trusted(self, address) -> bool:
        return any(address in network for network in self._trusted_proxies)

    @staticmethod
    def is_scan(path: str) -> bool:
        path = unquote(path).lower().rstrip("/")
        return (
            path == "/.env" or path.startswith("/.env.")
            or path == "/.git" or path.startswith("/.git/")
            or path in {"/wp-login.php", "/xmlrpc.php", "/wp-admin", "/phpmyadmin"}
            or path.startswith("/wp-admin/") or path.startswith("/phpmyadmin/")
        )

    def _record(
        self, source: _Source | None, ip: str, path: str, denial: Denial, now: float,
        force: bool = False,
    ) -> None:
        last = source.logged_at if source else self._capacity_logged_at
        if not force and last is not None and now - last < 60:
            if source:
                source.suppressed += 1
            return
        record = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "ip": ip,
            "path": path[:160],
            "rule": denial.reason,
            "action": "would_block" if self.settings.observe_only else "block",
            "status": denial.status,
            "suppressed": source.suppressed if source else 0,
        }
        logger.info(json.dumps(record, ensure_ascii=False))
        if source:
            source.logged_at = now
            source.suppressed = 0
        else:
            self._capacity_logged_at = now

    def _reject(self, source, ip, path, denial, now, force=False) -> Denial | None:
        self._record(source, ip, path, denial, now, force)
        return None if self.settings.observe_only else denial

    def _cleanup(self, now: float) -> None:
        if now < self._next_cleanup:
            return
        expired = [
            ip for ip, source in self._sources.items()
            if not source.active and source.banned_until <= now
            and now - source.last_seen >= self.settings.idle_seconds
        ]
        for ip in expired:
            del self._sources[ip]
        self._next_cleanup = now + 60

    def admit(
        self, ip: str, path: str, group: str | None, *, scan: bool = False,
        refresh: bool = False,
    ) -> tuple[Denial | None, _Lease | None]:
        if not self.settings.enabled:
            return None, None
        with self._lock:
            now = self._clock()
            self._cleanup(now)
            source = self._sources.get(ip)
            if source and source.banned_until > now:
                denial = self._reject(source, ip, path, Denial(404, "banned"), now)
                if denial:
                    return denial, None
            # Legal preflights do not consume quotas or create source records.
            if group is None:
                return None, None
            if source is None:
                if len(self._sources) >= self.settings.max_sources:
                    denial = self._reject(None, ip, path, Denial(503, "source_capacity", 60), now)
                    return denial, None
                source = self._sources[ip] = _Source(now)
            source.last_seen = now
            if scan:
                while source.scans and now - source.scans[0] >= self.settings.scan_window_seconds:
                    source.scans.popleft()
                source.scans.append(now)
                banned = len(source.scans) >= self.settings.scan_threshold
                if banned:
                    source.banned_until = now + self.settings.ban_seconds
                    source.scans.clear()
                denial = self._reject(
                    source, ip, path, Denial(404, "scan_ban" if banned else "scan"), now, banned,
                )
                if denial:
                    return denial, None

            settings = self.settings
            ip_rate = getattr(settings, f"{group}_ip_per_minute")
            global_rate = getattr(settings, f"{group}_global_per_minute")
            ip_burst = getattr(settings, f"{group}_ip_burst")
            global_burst = getattr(settings, f"{group}_global_burst")
            ip_bucket = source.buckets.setdefault(group, _Bucket(ip_burst, now))
            global_bucket = self._global_buckets.setdefault(group, _Bucket(global_burst, now))
            ip_bucket.refill(now, ip_rate, ip_burst)
            global_bucket.refill(now, global_rate, global_burst)
            checks = [
                (ip_bucket.tokens < 1, Denial(429, f"{group}_ip_rate", max(1, math.ceil((1 - ip_bucket.tokens) * 60 / ip_rate)))),
                (global_bucket.tokens < 1, Denial(503, f"{group}_global_rate", max(1, math.ceil((1 - global_bucket.tokens) * 60 / global_rate)))),
            ]
            if group == "chat":
                checks.extend([
                    (source.active_chat >= settings.chat_ip_concurrency, Denial(429, "chat_ip_concurrency")),
                    (self._active_chat >= settings.chat_global_concurrency, Denial(503, "chat_global_concurrency")),
                ])
            elif refresh:
                checks.append((self._active_refresh >= 1, Denial(503, "refresh_concurrency")))
            for exceeded, rejection in checks:
                if exceeded:
                    denial = self._reject(source, ip, path, rejection, now)
                    if denial:
                        return denial, None
            # Reserve both buckets atomically, only when all checks have passed.
            ip_bucket.tokens = max(0, ip_bucket.tokens - 1)
            global_bucket.tokens = max(0, global_bucket.tokens - 1)
            if group == "chat" or refresh:
                source.active += 1
                if group == "chat":
                    source.active_chat += 1
                    self._active_chat += 1
                else:
                    self._active_refresh += 1
                return None, _Lease(self, source, "chat" if group == "chat" else "refresh")
            return None, None


def install_request_protection(app: Flask, guard: RequestProtection) -> None:
    app.extensions["request_protection"] = guard

    @app.before_request
    def protect_request():
        guard = app.extensions["request_protection"]
        ip = guard.client_ip(request.remote_addr, request.headers.get("X-Forwarded-For"))
        chat = request.path in {"/", "/stream"} and request.method in {"GET", "POST", "HEAD"}
        preflight = request.method == "OPTIONS" and request.url_rule is not None
        denial, lease = guard.admit(
            ip, request.path, None if preflight else ("chat" if chat else "auxiliary"),
            scan=request.url_rule is None and guard.is_scan(request.path),
            refresh=request.path == "/refresh-upstream-models" and request.method == "POST",
        )
        g.protection_lease = lease
        if denial:
            text = "Not Found" if denial.status == 404 else "请求过于频繁，请稍后重试" if denial.status == 429 else "服务繁忙，请稍后重试"
            response = Response(text, status=denial.status, content_type="text/plain; charset=utf-8")
            if denial.status != 404:
                response.headers["Retry-After"] = str(denial.retry_after)
            return response

    @app.after_request
    def release_completed_request(response):
        lease = getattr(g, "protection_lease", None)
        if lease is not None:
            if response.is_streamed:
                # Close even an unstarted iterable; the upstream may have been
                # advanced to obtain the first chunk before headers were sent.
                iterable = response.response
                closed = False

                def close_stream():
                    nonlocal closed
                    if closed:
                        return
                    closed = True
                    try:
                        close = getattr(iterable, "close", None)
                        if close:
                            close()
                    finally:
                        lease.release()

                def generate():
                    try:
                        yield from iterable
                    finally:
                        close_stream()

                response.response = generate()
                response.call_on_close(close_stream)
            else:
                lease.release()
            g.protection_lease = None
        return response

    @app.teardown_request
    def release_failed_request(exception):
        lease = getattr(g, "protection_lease", None)
        if lease is not None:
            lease.release()
