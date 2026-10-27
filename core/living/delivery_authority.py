"""Restricted worker RPC for one authoritative delivery queue.

This is an optional isolated-test seam, not a deployed service. Administrative
approval / ownership / content APIs are deliberately absent. A worker token is
a privileged cluster credential, not an end-user credential. The authority must
remain the only writer and must not be cloned into independent node databases.
Plain HTTP is restricted to loopback; remote use requires a validated TLS
server and HTTPS client. No transport exception includes credentials or bodies.
"""
from __future__ import annotations

import http.client
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import logging
import math
import secrets
import socket
import ssl
import threading
from urllib.parse import urlsplit

from .delivery_store import DeliveryConflict


MAX_REQUEST = 65536
MAX_RESPONSE = 262144
WORKER_OPERATIONS = frozenset({"get", "claim", "begin", "finish", "defer", "counters", "health"})
_METRIC_OPERATIONS = WORKER_OPERATIONS | frozenset({"renew", "permit"})
_LOGGER = logging.getLogger(__name__)


class AuthorityUnavailable(RuntimeError):
    """No dispatch is allowed after an unavailable authority / lost response."""


class _AuthorityTimeout(AuthorityUnavailable):
    """Locally observed transport deadline, not proof of an uncommitted call."""


def _loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class DeliveryAuthority:
    """Local handler, independently testable without opening a socket."""
    def __init__(self, store, token):
        if not isinstance(token, str) or not 32 <= len(token) <= 256 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError("a strong printable worker token is required")
        self.store, self._token = store, token

    def dispatch(self, authorization, body):
        expected = "Bearer " + self._token
        if not isinstance(authorization, str) or not secrets.compare_digest(authorization.encode("utf-8"), expected.encode("utf-8")):
            return 401, {"ok": False, "error": "unauthorized"}
        if not isinstance(body, bytes) or len(body) > MAX_REQUEST:
            return 413, {"ok": False, "error": "request_too_large"}
        try:
            request = json.loads(body)
            if not isinstance(request, dict) or set(request) - {"operation", "args", "kwargs"}:
                raise ValueError("invalid request")
            operation = request.get("operation")
            if operation not in WORKER_OPERATIONS:
                return 403, {"ok": False, "error": "operation_forbidden"}
            args, kwargs = request.get("args", []), request.get("kwargs", {})
            if not isinstance(args, list) or len(args) > 6 or not isinstance(kwargs, dict) or len(kwargs) > 6:
                raise ValueError("invalid arguments")
            # Signature validation occurs before calling the explicit allowlist.
            import inspect
            target = getattr(self.store, operation)
            inspect.signature(target).bind(*args, **kwargs)
            result = target(*args, **kwargs)
            response = {"ok": True, "result": result}
            if len(json.dumps(response, allow_nan=False).encode()) > MAX_RESPONSE:
                return 500, {"ok": False, "error": "response_too_large"}
            return 200, response
        except DeliveryConflict:
            return 409, {"ok": False, "error": "delivery_conflict"}
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            return 400, {"ok": False, "error": "invalid_request"}
        except PermissionError:
            return 403, {"ok": False, "error": "forbidden"}
        except Exception:
            # Local lifecycle/store exceptions cannot become remote traceback,
            # SQL content, plaintext credentials, paths, or message payloads.
            return 503, {"ok": False, "error": "authority_unavailable"}


class _BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8
    block_on_close = True

    def __init__(self, address, handler):
        self._slots = threading.BoundedSemaphore(8)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        # HTTP server's default handler emits a full traceback to stderr.
        # Worker failures already have bounded protocol error responses.
        return


class AuthorityServer:
    """Owns a bounded standard-library HTTP server; lifecycle is explicit."""
    def __init__(self, authority, *, host="127.0.0.1", port=0, tls_context=None, request_timeout=3):
        if not _loopback(host) and not isinstance(tls_context, ssl.SSLContext):
            raise ValueError("remote authority requires TLS")
        if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
            raise ValueError("invalid authority port")
        if isinstance(request_timeout, bool) or not isinstance(request_timeout, (int, float)) or not math.isfinite(request_timeout) or not 0.1 <= request_timeout <= 10:
            raise ValueError("invalid request deadline")

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def setup(self):
                super().setup()
                self.connection.settimeout(request_timeout)
                # Inactivity timeout alone permits a client to dribble bytes
                # indefinitely. A bounded timer enforces the whole envelope
                # deadline as well, including HTTP header parsing.
                # Capture the socket, not the handler. Timer retains its
                # function after cancellation; capturing self would form
                # Handler -> Timer -> closure -> Handler and keep every
                # request's synchronization handles until cyclic GC runs.
                connection = self.connection
                def expire():
                    try:
                        connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                self._deadline_timer = threading.Timer(request_timeout, expire)
                self._deadline_timer.daemon = True
                self._deadline_timer.start()

            def finish(self):
                self._deadline_timer.cancel()
                super().finish()

            def log_message(self, fmt, *args):
                return

            def do_POST(self):
                if self.path != "/delivery/v1":
                    self.send_error(404)
                    return
                length = self.headers.get("Content-Length", "")
                if not length.isdecimal() or int(length) > MAX_REQUEST or self.headers.get("Transfer-Encoding") or self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                    status, payload = 400, {"ok": False, "error": "invalid_envelope"}
                else:
                    try:
                        size = int(length)
                        body = self.rfile.read(size)
                        if len(body) != size:
                            raise ValueError("truncated request")
                        status, payload = authority.dispatch(self.headers.get("Authorization"), body)
                    except (TimeoutError, OSError, ValueError):
                        status, payload = 408, {"ok": False, "error": "request_deadline"}
                encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(encoded)
                except OSError:
                    # Commit may have succeeded. Client must query/recover the
                    # existing task, never assume response loss means unsent.
                    return

        self._server = _BoundedHTTPServer((host, port), Handler)
        if tls_context is not None:
            if not isinstance(tls_context, ssl.SSLContext):
                self._server.server_close()
                raise ValueError("invalid TLS context")
            self._server.socket = tls_context.wrap_socket(self._server.socket, server_side=True)
        self.address = self._server.server_address
        self.url = ("https" if tls_context else "http") + "://" + host + ":" + str(self.address[1])

    def serve_forever(self):
        self._server.serve_forever(poll_interval=0.05)

    def shutdown(self):
        self._server.shutdown()
        self._server.server_close()


class AuthorityClient:
    """Synchronous restricted worker client; call via asyncio.to_thread.

    A failed ``begin`` response is not permission to dispatch. A failed
    ``finish`` response is not permission to resend. Query the task and retain
    unknown outcomes; clients do not perform implicit RPC retries.
    """
    def __init__(self, url, token, *, timeout=3, tls_context=None, transport=None):
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("invalid authority URL")
        if parsed.scheme == "http" and not _loopback(parsed.hostname):
            raise ValueError("plain HTTP authority must be loopback")
        if not isinstance(token, str) or not 32 <= len(token) <= 256 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError("invalid worker credential")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0.1 <= timeout <= 10:
            raise ValueError("invalid client deadline")
        if tls_context is not None and (not isinstance(tls_context, ssl.SSLContext) or tls_context.verify_mode != ssl.CERT_REQUIRED or not tls_context.check_hostname):
            raise ValueError("client TLS must verify certificate and hostname")
        self._parsed, self._token, self._timeout = parsed, token, timeout
        self._tls_context, self._transport = tls_context, transport
        self._metrics_lock = threading.Lock()
        self._metrics = self._new_metrics()
        self._operation_metrics = {}

    @staticmethod
    def _new_metrics():
        # conflicts/timeouts are subsets of failed, not additional outcomes.
        return dict(calls=0, succeeded=0, failed=0, cancelled=0, inflight=0,
                    conflicts=0, timeouts=0)

    @property
    def metrics(self):
        return self.diagnostics()["metrics"]

    def diagnostics(self):
        """Local counters only: this must never make a health RPC itself."""
        with self._metrics_lock:
            return dict(metrics=dict(self._metrics),
                        operations={key: dict(value) for key, value in self._operation_metrics.items()})

    def _record_call(self, operation, outcome=None):
        # Fixed cardinality and fixed log fields: no task/scope/token/URL/body.
        key = operation if operation in _METRIC_OPERATIONS else "other"
        with self._metrics_lock:
            per_operation = self._operation_metrics.setdefault(key, self._new_metrics())
            for metrics in (self._metrics, per_operation):
                if outcome is None:
                    metrics["calls"] += 1
                    metrics["inflight"] += 1
                else:
                    metrics["inflight"] -= 1
                    metrics["cancelled" if outcome == "cancelled" else
                            "succeeded" if outcome == "succeeded" else "failed"] += 1
                    if outcome in {"conflict", "timeout"}:
                        metrics["conflicts" if outcome == "conflict" else "timeouts"] += 1
            failures = self._metrics["failed"]
        # Bound repeated failure logging while retaining every counter. First,
        # second, fourth, eighth... failures remain visible without log storms.
        if outcome not in {None, "succeeded", "cancelled"} and failures & (failures - 1) == 0:
            _LOGGER.warning("TLS authority RPC failed: operation=%s outcome=%s failures=%d",
                            key, outcome, failures)

    def _call(self, operation, *args, **kwargs):
        body = json.dumps({"operation": operation, "args": args, "kwargs": kwargs}, separators=(",", ":"), allow_nan=False).encode()
        if len(body) > MAX_REQUEST:
            raise ValueError("authority request is too large")
        # Invalid local serialization never attempts a transport operation.
        self._record_call(operation)
        try:
            result = self._request(body)
        except asyncio.CancelledError:
            self._record_call(operation, "cancelled")
            raise
        except DeliveryConflict:
            self._record_call(operation, "conflict")
            raise
        except _AuthorityTimeout:
            self._record_call(operation, "timeout")
            raise
        except BaseException:
            self._record_call(operation, "failed")
            raise
        self._record_call(operation, "succeeded")
        return result

    def _request(self, body):
        headers = {"Authorization": "Bearer " + self._token, "Content-Type": "application/json"}
        try:
            if self._transport is not None:
                status, payload = self._transport(headers["Authorization"], body)
            else:
                parsed = self._parsed
                conn_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
                options = {"timeout": self._timeout}
                if parsed.scheme == "https":
                    options["context"] = self._tls_context or ssl.create_default_context()
                connection = conn_type(parsed.hostname, parsed.port, **options)
                try:
                    connection.request("POST", "/delivery/v1", body, headers)
                    response = connection.getresponse()
                    if response.length is not None and response.length > MAX_RESPONSE:
                        raise ValueError("response too large")
                    raw = response.read(MAX_RESPONSE + 1)
                    if len(raw) > MAX_RESPONSE:
                        raise ValueError("response too large")
                    status, payload = response.status, json.loads(raw)
                finally:
                    connection.close()
            if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
                raise ValueError("invalid authority response")
            if status == 409:
                raise DeliveryConflict("delivery authority rejected stale mutation")
            if status != 200 or payload["ok"] is not True:
                raise AuthorityUnavailable("delivery authority rejected request")
            return payload["result"]
        except DeliveryConflict:
            raise
        except TimeoutError:
            raise _AuthorityTimeout("delivery authority transport unavailable") from None
        except (OSError, http.client.HTTPException, ValueError, TypeError, KeyError, RecursionError) as exc:
            raise AuthorityUnavailable("delivery authority transport unavailable") from None

    def get(self, task_id):
        return self._call("get", task_id)

    def claim(self, node, lease_seconds=30):
        return self._call("claim", node, lease_seconds)

    def begin(self, task_id, node, token, policy):
        return self._call("begin", task_id, node, token, policy)

    def finish(self, task_id, node, token, outcome, code=""):
        return self._call("finish", task_id, node, token, outcome, code)

    def defer(self, task_id, node, token, available_at, code="frequency_gate"):
        return self._call("defer", task_id, node, token, available_at, code)

    def counters(self, scope, day):
        return self._call("counters", scope, day)

    def health(self):
        return self._call("health")
