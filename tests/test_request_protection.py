import importlib
import http.client
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Condition, Event, Thread
from unittest.mock import patch

from flask import Flask, Response
from werkzeug.serving import WSGIRequestHandler, make_server

from api.base_api import BaseApi
from models.session_manager import SessionManager
from server.request_protection import (
    ProtectionSettings,
    RequestProtection,
    configure_protection_logging,
    install_request_protection,
    load_protection_settings,
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class RequestProtectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()

    def guard(self, **settings):
        return RequestProtection(replace(ProtectionSettings(), **settings), self.clock)

    def admit_and_finish(self, guard, ip="192.0.2.1", group="chat"):
        denial, lease = guard.admit(ip, "/", group)
        if lease:
            lease.release()
        return denial

    def test_ip_burst_recovers_without_banning_source(self) -> None:
        guard = self.guard(chat_ip_burst=2, chat_ip_per_minute=60)
        self.assertIsNone(self.admit_and_finish(guard))
        self.assertIsNone(self.admit_and_finish(guard))
        denial = self.admit_and_finish(guard)
        self.assertEqual((denial.status, denial.retry_after), (429, 1))
        self.assertEqual(guard._sources["192.0.2.1"].banned_until, 0)
        self.clock.now = 1
        self.assertIsNone(self.admit_and_finish(guard))

    def test_ip_rejection_does_not_spend_other_sources_global_tokens(self) -> None:
        guard = self.guard(chat_ip_burst=1, chat_global_burst=2)
        self.assertIsNone(self.admit_and_finish(guard))
        self.assertEqual(self.admit_and_finish(guard).status, 429)
        self.assertIsNone(self.admit_and_finish(guard, "192.0.2.2"))
        self.assertEqual(self.admit_and_finish(guard, "192.0.2.3").status, 503)

    def test_global_rate_recovers_and_auxiliary_has_separate_quota(self) -> None:
        guard = self.guard(chat_global_burst=1, chat_global_per_minute=60)
        self.assertIsNone(self.admit_and_finish(guard))
        self.assertEqual(self.admit_and_finish(guard, "192.0.2.2").reason, "chat_global_rate")
        self.assertIsNone(self.admit_and_finish(guard, group="auxiliary"))
        self.clock.now = 1
        self.assertIsNone(self.admit_and_finish(guard, "192.0.2.2"))

    def test_ip_and_global_concurrency_and_idempotent_release(self) -> None:
        guard = self.guard(chat_ip_concurrency=1, chat_global_concurrency=2)
        _, first = guard.admit("192.0.2.1", "/", "chat")
        self.assertEqual(guard.admit("192.0.2.1", "/", "chat")[0].status, 429)
        _, second = guard.admit("192.0.2.2", "/", "chat")
        self.assertEqual(guard.admit("192.0.2.3", "/", "chat")[0].status, 503)
        first.release()
        first.release()
        _, third = guard.admit("192.0.2.3", "/", "chat")
        second.release()
        third.release()
        self.assertEqual(guard._active_chat, 0)

    def test_concurrent_admission_cannot_exceed_global_limit(self) -> None:
        guard = self.guard(chat_global_concurrency=3)
        barrier = Barrier(20)

        def admit(index):
            barrier.wait(timeout=5)
            return guard.admit(f"192.0.2.{index + 1}", "/", "chat")

        with ThreadPoolExecutor(max_workers=20) as executor:
            admissions = list(executor.map(admit, range(20)))
        leases = [lease for _, lease in admissions if lease]
        self.assertEqual(len(leases), 3)
        self.assertTrue(all(denial.status == 503 for denial, _ in admissions if denial))
        for lease in leases:
            lease.release()
        self.assertEqual(guard._active_chat, 0)

    def test_scan_ban_expires_without_extending_on_blocked_requests(self) -> None:
        guard = self.guard()
        for _ in range(5):
            self.assertEqual(guard.admit("192.0.2.1", "/.env", "auxiliary", scan=True)[0].status, 404)
        self.clock.now = 899
        self.assertEqual(guard.admit("192.0.2.1", "/", "chat")[0].reason, "banned")
        self.assertIsNone(self.admit_and_finish(guard, "192.0.2.2"))
        self.clock.now = 900
        self.assertIsNone(self.admit_and_finish(guard))

    def test_old_scans_do_not_accumulate_forever(self) -> None:
        guard = self.guard()
        for index in range(8):
            self.clock.now = index * 61
            guard.admit("192.0.2.1", "/.git/config", "auxiliary", scan=True)
        self.assertEqual(guard._sources["192.0.2.1"].banned_until, 0)

    def test_ordinary_unknown_paths_and_query_text_are_not_scans(self) -> None:
        for path in ["/", "/stream", "/favicon.ico", "/robots.txt", "/missing", "/.environment"]:
            self.assertFalse(RequestProtection.is_scan(path))
        for path in ["/.env", "/.env.production", "/.git/config", "/%2egit/config", "/WP-LOGIN.PHP", "/phpmyadmin/"]:
            self.assertTrue(RequestProtection.is_scan(path))

    def test_preflights_do_not_spend_tokens_or_create_records(self) -> None:
        guard = self.guard(chat_ip_burst=1)
        for _ in range(50):
            self.assertEqual(guard.admit("192.0.2.1", "/", None), (None, None))
        self.assertEqual(guard._sources, {})
        self.assertIsNone(self.admit_and_finish(guard))

    def test_refresh_limit_is_global_and_does_not_count_as_chat(self) -> None:
        guard = self.guard(chat_ip_concurrency=1)
        _, refresh = guard.admit("192.0.2.1", "/refresh-upstream-models", "auxiliary", refresh=True)
        denial, _ = guard.admit("192.0.2.2", "/refresh-upstream-models", "auxiliary", refresh=True)
        self.assertEqual(denial.reason, "refresh_concurrency")
        self.assertIsNone(self.admit_and_finish(guard))
        refresh.release()
        self.assertEqual(guard._active_refresh, 0)

    def test_capacity_never_evicts_active_or_banned_sources(self) -> None:
        guard = self.guard(max_sources=2, idle_seconds=60)
        _, lease = guard.admit("192.0.2.1", "/", "chat")
        for _ in range(5):
            guard.admit("192.0.2.2", "/.env", "auxiliary", scan=True)
        self.clock.now = 120
        self.assertEqual(self.admit_and_finish(guard, "192.0.2.3").reason, "source_capacity")
        self.assertEqual(len(guard._sources), 2)
        lease.release()
        self.clock.now = 180
        self.assertIsNone(self.admit_and_finish(guard, "192.0.2.3"))
        self.assertIn("192.0.2.2", guard._sources)

    def test_observation_records_limits_without_enforcing(self) -> None:
        guard = self.guard(observe_only=True, chat_ip_concurrency=1, chat_ip_burst=1)
        with patch("server.request_protection.logger.info") as log:
            _, first = guard.admit("192.0.2.1", "/", "chat")
            denial, second = guard.admit("192.0.2.1", "/", "chat")
            self.assertIsNone(denial)
            self.assertEqual(json.loads(log.call_args.args[0])["action"], "would_block")
        first.release()
        second.release()

    def test_disabled_protection_does_not_track_requests(self) -> None:
        guard = self.guard(enabled=False)
        for _ in range(50):
            self.assertEqual(guard.admit("192.0.2.1", "/.env", "auxiliary", scan=True), (None, None))
        self.assertEqual(guard._sources, {})

    def test_default_ignores_forged_forwarding_headers_and_normalizes_ip(self) -> None:
        guard = self.guard()
        self.assertEqual(guard.client_ip("192.0.2.1", "198.51.100.2"), "192.0.2.1")
        self.assertEqual(guard.client_ip("::ffff:192.0.2.1"), "192.0.2.1")

    def test_proxy_chain_stops_at_first_untrusted_ip(self) -> None:
        guard = self.guard(trusted_proxy_networks=("127.0.0.1/32", "10.0.0.1/32"))
        self.assertEqual(guard.client_ip("127.0.0.1", "203.0.113.9, 192.0.2.1, 10.0.0.1"), "192.0.2.1")
        self.assertEqual(guard.client_ip("192.0.2.1", "198.51.100.1"), "192.0.2.1")
        self.assertEqual(guard.client_ip("127.0.0.1", "invalid"), "127.0.0.1")

    def test_repeated_logs_are_aggregated_and_ban_is_always_logged(self) -> None:
        guard = self.guard()
        with patch("server.request_protection.logger.info") as log:
            for _ in range(5):
                guard.admit("192.0.2.1", "/.env", "auxiliary", scan=True)
            self.assertEqual(log.call_count, 2)
            record = json.loads(log.call_args.args[0])
            self.assertEqual(record["rule"], "scan_ban")
            self.assertEqual(record["suppressed"], 3)


class ProtectionConfigTest(unittest.TestCase):
    def load_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "protection.config"
            path.write_text(text, encoding="utf-8")
            return load_protection_settings(path)

    def test_missing_file_and_partial_config_use_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_protection_settings(Path(directory) / "missing"), ProtectionSettings())
        settings = self.load_text("[protection]\nchat_ip_concurrency = 6\nobserve_only = true\n")
        self.assertEqual(settings.chat_ip_concurrency, 6)
        self.assertEqual(settings.chat_global_concurrency, 12)
        self.assertTrue(settings.observe_only)

    def test_invalid_config_does_not_silently_disable_protection(self) -> None:
        for text in [
            "[wrong]\nenabled=true", "[protection]\nchat_ip_burst=0",
            "[protection]\nchat_ip_burts=12", "[protection]\nenabled=maybe",
            "[protection]\ntrusted_proxy_networks=not-an-ip",
            "[protection]\nidle_seconds=1",
        ]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.load_text(text)

    def test_shipped_config_matches_defaults(self) -> None:
        self.assertEqual(load_protection_settings(), ProtectionSettings())

    def test_log_handler_is_rotating_and_does_not_write_outside_project(self) -> None:
        from server import request_protection

        old_handlers = request_protection.logger.handlers[:]
        old_level = request_protection.logger.level
        old_propagate = request_protection.logger.propagate
        try:
            request_protection.logger.handlers = []
            with tempfile.TemporaryDirectory() as directory:
                with patch.object(request_protection, "PROJECT_ROOT", Path(directory)):
                    configure_protection_logging()
                    configure_protection_logging()
                    self.assertEqual(len(request_protection.logger.handlers), 1)
                    handler = request_protection.logger.handlers[0]
                    self.assertEqual(handler.backupCount, 3)
                    request_protection.logger.info('{"rule":"test"}')
                    handler.close()
                    path = Path(directory) / "logs" / "request_protection.jsonl"
                    self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["rule"], "test")
        finally:
            request_protection.logger.handlers = old_handlers
            request_protection.logger.setLevel(old_level)
            request_protection.logger.propagate = old_propagate


class RecordingApi(BaseApi):
    def __init__(self) -> None:
        self.calls = []
        self.streams_closed = 0
        self.failure = False

    def reason(self, messages):
        self.calls.append(messages)
        if self.failure:
            raise RuntimeError("upstream failed")
        return "answer"

    def reason_stream(self, messages):
        self.calls.append(messages)
        try:
            if self.failure:
                raise RuntimeError("upstream failed")
            yield "one"
            yield "two"
        finally:
            self.streams_closed += 1


class RecordingFactory:
    def __init__(self, client) -> None:
        self.client = client

    def get_client(self, provider=None, model=None):
        return self.client


class ProtectionIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.upstream = RecordingApi()
        self.manager = SessionManager(api_factory=RecordingFactory(self.upstream))
        sys.modules.pop("server.web_server", None)
        with patch("models.session_manager.SessionManager", return_value=self.manager):
            self.server = importlib.import_module("server.web_server")
        self.addCleanup(lambda: sys.modules.pop("server.web_server", None))
        self.app = self.server.app
        self.app.testing = True
        self.set_guard()
        self.client = self.app.test_client()

    def set_guard(self, **settings):
        self.guard = RequestProtection(replace(ProtectionSettings(), **settings), self.clock)
        self.app.extensions["request_protection"] = self.guard

    def test_get_post_stream_and_new_session_ids_share_rate_quota(self) -> None:
        self.set_guard(chat_ip_burst=2)
        self.assertEqual(self.client.get("/?user_message=hello&id=first").status_code, 200)
        stream = self.client.post("/stream", json={"user_message": "hello", "id": "second"})
        stream.get_data()
        stream.close()
        blocked = self.client.post("/", json={"user_message": "hello", "id": "third"}, headers={
            "X-Forwarded-For": "198.51.100.1", "Origin": "http://intranet.example",
        })
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)
        self.assertEqual(blocked.headers["Access-Control-Allow-Origin"], "http://intranet.example")
        self.assertEqual(len(self.upstream.calls), 2)
        self.assertNotIn("third", self.manager.pool)

    def test_scan_ban_cannot_be_bypassed_by_forwarded_header(self) -> None:
        for _ in range(5):
            response = self.client.get("/.env?user_message=private&api_key=secret")
            self.assertEqual((response.status_code, response.get_data(as_text=True)), (404, "Not Found"))
        blocked = self.client.post("/", json={"user_message": "hello"}, headers={"X-Forwarded-For": "198.51.100.1"})
        self.assertEqual(blocked.status_code, 404)
        self.assertEqual(self.upstream.calls, [])
        self.assertEqual(self.client.get("/help", environ_overrides={"REMOTE_ADDR": "192.0.2.2"}).status_code, 200)
        self.clock.now = 900
        self.assertEqual(self.client.post("/", json={"user_message": "hello"}).status_code, 200)

    def test_errors_and_unknown_paths_do_not_ban_or_leak_slots(self) -> None:
        for _ in range(6):
            self.assertEqual(self.client.get("/missing").status_code, 404)
            self.assertEqual(self.client.post("/", json={}).status_code, 400)
        self.upstream.failure = True
        self.assertEqual(self.client.get("/stream?user_message=hello").status_code, 502)
        with self.assertRaises(RuntimeError):
            self.client.post("/", json={"user_message": "hello"})
        self.assertEqual(self.guard._active_chat, 0)
        self.assertEqual(self.guard._sources["127.0.0.1"].banned_until, 0)
        self.upstream.failure = False
        self.assertEqual(self.client.post("/", json={"user_message": "hello"}).status_code, 200)

    def test_stream_holds_slot_and_disconnect_releases_upstream_and_history(self) -> None:
        self.set_guard(chat_ip_concurrency=1)
        stream = self.client.post("/stream", json={"user_message": "first", "id": "shared", "preserve": True}, buffered=False)
        self.addCleanup(stream.close)
        self.assertEqual(self.guard._active_chat, 1)
        self.assertEqual(self.client.post("/", json={"user_message": "second"}).status_code, 429)
        # Long generation is not given a new timeout, and bans never interrupt
        # the already admitted stream.
        self.clock.now = 3600
        for _ in range(5):
            self.client.get("/.env")
        self.assertIn(b'"type": "session"', next(stream.response))
        self.assertIn(b'"type": "delta"', next(stream.response))
        stream.close()
        stream.close()
        self.assertEqual(self.guard._active_chat, 0)
        self.assertEqual(self.upstream.streams_closed, 1)
        self.assertEqual(self.manager.pool["shared"].snapshot_messages(), [])

    def test_completed_stream_releases_without_waiting_for_response_close(self) -> None:
        self.set_guard(chat_ip_concurrency=1)
        response = self.client.post("/stream", json={"user_message": "hello", "id": "s1", "preserve": True})
        events = [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines() if line.startswith("data: ")]
        self.assertEqual([event["type"] for event in events], ["session", "delta", "delta", "done"])
        self.assertEqual(self.guard._active_chat, 0)
        self.assertEqual(self.manager.pool["s1"].snapshot_messages()[-1]["content"], "onetwo")
        response.close()
        self.assertEqual(self.guard._active_chat, 0)

    def test_head_chat_is_counted_and_head_stream_closes_unstarted_body(self) -> None:
        self.set_guard(chat_ip_burst=2)
        response = self.client.head("/stream?user_message=hello&id=head")
        response.close()
        self.assertEqual(self.guard._active_chat, 0)
        self.assertEqual(self.upstream.streams_closed, 1)
        self.assertFalse(self.manager.pool["head"]._conversation_lock.locked())
        response = self.client.head("/?user_message=hello")
        response.close()
        self.assertEqual(self.client.get("/?user_message=hello").status_code, 429)

    def test_preflight_remains_compatible_even_when_chat_quota_is_exhausted(self) -> None:
        self.set_guard(chat_ip_burst=1)
        self.client.post("/", json={"user_message": "hello"})
        for _ in range(40):
            response = self.client.options("/", headers={
                "Origin": "http://intranet.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            })
            self.assertEqual(response.status_code, 200)
            self.assertIn("POST", response.headers["Access-Control-Allow-Methods"])
        self.assertEqual(len(self.upstream.calls), 1)

    def test_three_automatic_and_four_manual_requests_can_share_ip(self) -> None:
        admissions = [self.guard.admit("192.0.2.1", "/", "chat") for _ in range(7)]
        self.assertTrue(all(denial is None for denial, _ in admissions))
        self.assertEqual(self.guard._active_chat, 7)
        for _, lease in admissions:
            lease.release()

    def test_automatic_workload_with_variable_latencies_stays_below_limits(self) -> None:
        # Three continuously replenished workers, sharing an IP, with a 2/5/30s
        # mix. The fake clock covers ten minutes without real waits.
        pending = []
        index = 0
        for _ in range(3):
            denial, lease = self.guard.admit("192.0.2.1", "/", "chat")
            self.assertIsNone(denial)
            pending.append((self.clock.now + [2, 5, 30][index % 3], lease))
            index += 1
        while self.clock.now < 600:
            pending.sort(key=lambda item: item[0])
            self.clock.now, lease = pending.pop(0)
            lease.release()
            denial, lease = self.guard.admit("192.0.2.1", "/", "chat")
            self.assertIsNone(denial)
            pending.append((self.clock.now + [2, 5, 30][index % 3], lease))
            index += 1
        for _, lease in pending:
            lease.release()

    def test_refresh_concurrency_blocks_duplicate_work_and_recovers(self) -> None:
        started = Event()
        finish = Event()

        def reload():
            started.set()
            if not finish.wait(timeout=5):
                raise RuntimeError("test timed out")
            return []

        self.manager.api_factory.reload_auto_providers = reload
        responses = []

        def refresh():
            with self.app.test_client() as client:
                responses.append(client.post("/refresh-upstream-models").status_code)

        thread = Thread(target=refresh)
        thread.start()
        try:
            self.assertTrue(started.wait(timeout=2))
            self.assertEqual(self.client.post("/refresh-upstream-models").status_code, 503)
        finally:
            finish.set()
            thread.join(timeout=5)
        self.assertEqual(responses, [200])
        self.assertEqual(self.guard._active_refresh, 0)

    def test_real_http_shared_ip_concurrency_and_sse_compatibility(self) -> None:
        finish = Event()
        started = Condition()
        count = 0

        def answer(messages):
            nonlocal count
            with started:
                count += 1
                started.notify_all()
            if not finish.wait(timeout=10):
                raise RuntimeError("test timed out")
            return "answer"

        self.upstream.reason = answer

        class QuietHandler(WSGIRequestHandler):
            def log_request(self, code="-", size="-"):
                pass

        server = make_server("127.0.0.1", 0, self.app, threaded=True, request_handler=QuietHandler)
        thread = Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
        thread.start()

        def post(path="/", origin=False):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            try:
                headers = {"Content-Type": "application/json"}
                if origin:
                    headers["Origin"] = "http://intranet.example"
                connection.request("POST", path, json.dumps({"user_message": "hello"}), headers)
                response = connection.getresponse()
                return response.status, dict(response.getheaders()), response.read()
            finally:
                connection.close()

        try:
            with ThreadPoolExecutor(max_workers=8) as executor:
                requests = [executor.submit(post) for _ in range(8)]
                try:
                    with started:
                        self.assertTrue(started.wait_for(lambda: count == 8, timeout=5))
                    self.assertEqual(self.guard._active_chat, 8)
                    status, headers, _ = post(origin=True)
                    self.assertEqual(status, 429)
                    self.assertIn("Retry-After", headers)
                    self.assertEqual(headers["Access-Control-Allow-Origin"], "http://intranet.example")
                finally:
                    finish.set()
                self.assertEqual([item.result(timeout=5)[0] for item in requests], [200] * 8)
            self.assertEqual(self.guard._active_chat, 0)
            status, headers, body = post("/stream", origin=True)
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "text/event-stream; charset=utf-8")
            self.assertEqual(headers["X-Accel-Buffering"], "no")
            self.assertEqual(headers["Access-Control-Allow-Origin"], "http://intranet.example")
            events = [json.loads(line[6:]) for line in body.decode().splitlines() if line.startswith("data: ")]
            self.assertEqual([event["type"] for event in events], ["session", "delta", "delta", "done"])
        finally:
            finish.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class StreamCleanupTest(unittest.TestCase):
    def test_unstarted_and_failed_closing_iterables_release_exactly_once(self) -> None:
        for started in [False, True]:
            with self.subTest(started=started):
                app = Flask(__name__)
                guard = RequestProtection()
                install_request_protection(app, guard)
                closed = []

                class Body:
                    def __iter__(self):
                        yield "first"

                    def close(self):
                        closed.append(True)
                        raise RuntimeError("close failed")

                @app.route("/")
                def stream():
                    return Response(Body())

                with app.test_request_context("/"):
                    app.preprocess_request()
                    response = app.process_response(app.make_response(stream()))
                    self.assertEqual(guard._active_chat, 1)
                    if started:
                        self.assertEqual(next(response.response), "first")
                    with self.assertRaisesRegex(RuntimeError, "close failed"):
                        response.close()
                    response.close()
                    self.assertEqual(guard._active_chat, 0)
                    self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
