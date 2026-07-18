"""Managed lifecycle for dancing-log's local HTTP adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import socket
import sys
import threading
import time
from typing import Protocol


class AcceptedOperationShutdown(Enum):
    """How stop handles requests that already entered an operation."""

    DRAIN = "drain"
    CANCEL = "cancel"


class BoundedHttpLifecycle(Protocol):
    """A long-lived HTTP participant with active cancellation and bounded drain."""

    def stop(self) -> None: ...

    def wait_until_drained(self, timeout: float) -> bool: ...


@dataclass(frozen=True)
class HttpShutdownParticipant:
    label: str
    lifecycle: BoundedHttpLifecycle
    timeout_seconds: float


class ManagedLocalHTTPServer(ThreadingHTTPServer):
    """Own listener, handler, operation, thread, and shutdown lifecycles."""

    daemon_threads = True

    def __init__(
        self,
        server_address,
        request_handler_class,
        *,
        accepted_operation_shutdown: AcceptedOperationShutdown,
        request_read_deadline_seconds: float | None = None,
        request_read_poll_seconds: float = 0.25,
        shutdown_participants: tuple[HttpShutdownParticipant, ...] = (),
    ) -> None:
        if request_read_deadline_seconds is not None and request_read_deadline_seconds <= 0:
            raise ValueError("request read deadline must be positive")
        if request_read_poll_seconds <= 0:
            raise ValueError("request read poll interval must be positive")
        super().__init__(server_address, request_handler_class)
        self.request_read_deadline_seconds = request_read_deadline_seconds
        self.request_read_poll_seconds = request_read_poll_seconds
        self._accepted_operation_shutdown = accepted_operation_shutdown
        self._shutdown_participants = shutdown_participants
        self._requests = _OrdinaryHttpRequests()
        self._serve_thread: threading.Thread | None = None
        self._stop_lock = threading.Lock()
        self._stopped = False

    @property
    def active_request_count(self) -> int:
        """Diagnostic count of handler connections owned by this Module."""
        return self._requests.active_count

    def start_http(self, *, thread_name: str) -> None:
        """Start serving transactionally; a failed thread start releases the listener."""
        thread = threading.Thread(
            target=self.serve_forever,
            name=thread_name,
            daemon=True,
        )
        try:
            thread.start()
        except BaseException as primary:
            cleanup_errors: list[BaseException] = []
            try:
                self.server_close()
            except BaseException as exc:
                cleanup_errors.append(exc)
            self._stopped = True
            if cleanup_errors:
                raise BaseExceptionGroup(
                    f"HTTP server start failed after {primary}",
                    [primary, *cleanup_errors],
                ) from None
            raise
        self._serve_thread = thread

    def stop_http(self) -> None:
        """Reject new work, apply shutdown policy, and drain every owned lifecycle."""
        with self._stop_lock:
            if self._stopped:
                return
            errors: list[Exception] = []
            _attempt_cleanup(
                errors,
                lambda: self._requests.begin_shutdown(
                    close_operations=(
                        self._accepted_operation_shutdown
                        is AcceptedOperationShutdown.CANCEL
                    )
                ),
            )
            for participant in self._shutdown_participants:
                _attempt_cleanup(errors, participant.lifecycle.stop)
            if self._serve_thread is not None:
                _attempt_cleanup(errors, self.shutdown)
            _attempt_cleanup(errors, self._requests.wait_until_drained)
            _attempt_cleanup(errors, self.server_close)
            for participant in self._shutdown_participants:
                try:
                    drained = participant.lifecycle.wait_until_drained(
                        participant.timeout_seconds
                    )
                except Exception as exc:
                    errors.append(exc)
                else:
                    if not drained:
                        errors.append(
                            TimeoutError(
                                f"{participant.label} did not drain within "
                                f"{participant.timeout_seconds:g} seconds"
                            )
                        )
            if self._serve_thread is not None:
                thread = self._serve_thread
                _attempt_cleanup(errors, lambda: thread.join(timeout=2.0))
                if thread.is_alive():
                    errors.append(TimeoutError("HTTP serve thread did not stop"))
                self._serve_thread = None
            self._stopped = True
            if len(errors) == 1:
                raise errors[0]
            if errors:
                raise ExceptionGroup("HTTP lifecycle shutdown failed", errors)

    def process_request(self, request, client_address) -> None:
        if not self._requests.register(request):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._requests.finish(request)
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._requests.finish(request)

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)):
            return
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) in {
            10038,
            10053,
            10054,
        }:
            return
        super().handle_error(request, client_address)


class ManagedLocalHTTPRequestHandler(BaseHTTPRequestHandler):
    """Hide request-generation tracking and expose one semantic operation entry."""

    server: ManagedLocalHTTPServer

    def setup(self) -> None:
        deadline = self.server.request_read_deadline_seconds
        if deadline is not None:
            self.request.settimeout(
                min(deadline, self.server.request_read_poll_seconds)
            )
        super().setup()
        if deadline is not None:
            self.rfile.close()
            self._interruptible_reader = _InterruptibleSocketReader(self.connection)
            self.rfile = io.BufferedReader(self._interruptible_reader)

    def handle_one_request(self) -> None:
        token = self.server._requests.begin_request(self.connection)
        if token is None:
            self.close_connection = True
            return
        deadline_seconds = self.server.request_read_deadline_seconds
        if deadline_seconds is not None:
            self.connection.settimeout(
                min(deadline_seconds, self.server.request_read_poll_seconds)
            )
        self._operation_token = token
        deadline = None
        if deadline_seconds is not None:
            deadline = threading.Timer(
                deadline_seconds,
                self.server._requests.expire_pre_operation,
                args=(self.connection, token),
            )
            deadline.daemon = True
            deadline.start()
        try:
            super().handle_one_request()
        finally:
            if deadline is not None:
                deadline.cancel()
            if not self.close_connection and not self.server._requests.prepare_next_request(
                self.connection
            ):
                self.close_connection = True

    def perform_operation(self, action: Callable[[], object]) -> bool:
        """Atomically accept one parsed request and run its Adapter action."""
        if not self.server._requests.enter_operation(
            self.connection,
            self._operation_token,
        ):
            self.close_connection = True
            return False
        self.connection.settimeout(None)
        action()
        return True

    def discard_available_body(self, *, length: int, grace_seconds: float) -> None:
        """Best-effort drain of a rejected body within a fixed grace period."""
        if length <= 0:
            return
        previous_timeout = self.connection.gettimeout()
        deadline = time.monotonic() + grace_seconds
        reader = getattr(self, "_interruptible_reader", None)
        if reader is not None:
            reader.retry_timeouts = False
        try:
            remaining = length
            while remaining > 0:
                timeout = deadline - time.monotonic()
                if timeout <= 0:
                    break
                self.connection.settimeout(timeout)
                try:
                    chunk = self.rfile.read1(min(remaining, 64 * 1024))
                except (OSError, ValueError):
                    break
                if not chunk:
                    break
                remaining -= len(chunk)
        finally:
            if reader is not None:
                reader.retry_timeouts = True
            try:
                self.connection.settimeout(previous_timeout)
            except OSError:
                pass


class _OrdinaryHttpRequests:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active: dict[int, object] = {}
        self._pre_operation: dict[int, object] = {}
        self._accepting = True

    def register(self, request: object) -> bool:
        with self._condition:
            if not self._accepting:
                return False
            key = id(request)
            self._active[key] = request
            self._pre_operation[key] = object()
            return True

    def begin_request(self, request: object) -> object | None:
        with self._condition:
            key = id(request)
            if not self._accepting or key not in self._active:
                return None
            return self._pre_operation.get(key)

    def enter_operation(self, request: object, token: object) -> bool:
        with self._condition:
            key = id(request)
            if not self._accepting or self._pre_operation.get(key) is not token:
                return False
            self._pre_operation.pop(key)
            return True

    def prepare_next_request(self, request: object) -> bool:
        with self._condition:
            key = id(request)
            if not self._accepting or key not in self._active:
                return False
            self._pre_operation[key] = object()
            return True

    def expire_pre_operation(self, request: object, token: object) -> bool:
        with self._condition:
            key = id(request)
            if self._pre_operation.get(key) is not token:
                return False
            self._pre_operation.pop(key)
            connection = self._active.get(key)
        if connection is not None:
            _close_http_connection(connection)
        return connection is not None

    def begin_shutdown(self, *, close_operations: bool) -> None:
        with self._condition:
            self._accepting = False
            if close_operations:
                connections = list(self._active.values())
            else:
                connections = [
                    self._active[key]
                    for key in self._pre_operation
                    if key in self._active
                ]
            self._pre_operation.clear()
        for connection in connections:
            _close_http_connection(connection)

    def finish(self, request: object) -> None:
        with self._condition:
            key = id(request)
            self._active.pop(key, None)
            self._pre_operation.pop(key, None)
            if not self._active:
                self._condition.notify_all()

    def wait_until_drained(self) -> None:
        with self._condition:
            while self._active:
                self._condition.wait()

    @property
    def active_count(self) -> int:
        with self._condition:
            return len(self._active)


class _InterruptibleSocketReader(io.RawIOBase):
    def __init__(self, connection: socket.socket) -> None:
        super().__init__()
        self.connection = connection
        self.retry_timeouts = True

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        while True:
            if self.closed or self.connection.fileno() < 0:
                return 0
            try:
                return self.connection.recv_into(buffer)
            except TimeoutError:
                if not self.retry_timeouts:
                    raise
            except OSError:
                return 0


def _close_http_connection(connection: object) -> None:
    try:
        connection.shutdown(2)
    except OSError:
        pass
    try:
        connection.close()
    except OSError:
        pass


def _attempt_cleanup(errors: list[Exception], action: Callable[[], object]) -> None:
    try:
        action()
    except Exception as exc:
        errors.append(exc)
