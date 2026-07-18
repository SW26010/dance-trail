"""Local-only OBS overlay server for live playback state."""

from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler
import json
from queue import Empty, Full, Queue
import socket
import threading
from urllib.parse import urlparse, urlsplit

from dancing_log.http_request_lifecycle import (
    AcceptedOperationShutdown,
    HttpShutdownParticipant,
    ManagedLocalHTTPRequestHandler,
    ManagedLocalHTTPServer,
)
from dancing_log.overlay_view_model import build_overlay_view_model
from dancing_log.time_utils import now_utc_iso


OVERLAY_HOST = "127.0.0.1"
LOCAL_HTTP_HOSTS = frozenset({OVERLAY_HOST, "localhost"})
OVERLAY_PAGE_PATH = "/overlay"
OVERLAY_STATE_PATH = "/api/overlay/state"
OVERLAY_EVENTS_PATH = "/api/overlay/events"
EVENT_STREAM_DRAIN_TIMEOUT_SECONDS = 2.0
_STOP_EVENT_STREAM = object()


def is_allowed_local_http_host(value: str, *, port: int) -> bool:
    """Accept only this localhost listener's expected Host header."""
    try:
        parsed = urlparse(f"//{value}")
        request_port = _normalized_http_port(parsed.port)
    except ValueError:
        return False
    return (
        (parsed.hostname or "").lower() in LOCAL_HTTP_HOSTS
        and parsed.username is None
        and parsed.password is None
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and request_port == port
    )


def is_allowed_local_http_origin(value: str, *, port: int) -> bool:
    """Accept only an HTTP origin for this localhost listener."""
    try:
        parsed = urlsplit(value)
        request_port = _normalized_http_port(parsed.port)
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "http"
        and (parsed.hostname or "").lower() in LOCAL_HTTP_HOSTS
        and parsed.username is None
        and parsed.password is None
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and request_port == port
    )


def _normalized_http_port(port: int | None) -> int:
    return 80 if port is None else port


@dataclass
class OverlayState:
    """Thread-safe in-memory state shared by HTTP and watcher threads."""

    max_events: int = 20
    enabled: bool = True
    _events: dict[str, dict] = field(default_factory=dict)
    _status: dict | None = None
    _subscribers: list[Queue] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _sequence: int = 0
    _cleared_sequence: int = 0

    def publish(self, event: dict) -> dict:
        """Store one event update and notify SSE subscribers."""
        with self._lock:
            key = str(event.get("live_event_key") or event.get("event_key") or "")
            if key:
                stored = dict(event)
                self._sequence += 1
                stored["_overlay_sequence"] = self._sequence
                stored["received_at"] = _utc_now()
                self._events[key] = stored
                self._trim_locked()
            snapshot = self._snapshot_locked()
            for subscriber in self._subscribers:
                _put_latest(subscriber, snapshot)
        return snapshot

    def publish_status(self, status: dict) -> dict:
        """Publish a non-playback status update such as room leave or shutdown."""
        with self._lock:
            stored = dict(status)
            if "overlay_enabled" in stored:
                self.enabled = bool(stored["overlay_enabled"])
                stored["overlay_enabled"] = self.enabled
            self._sequence += 1
            stored["_overlay_sequence"] = self._sequence
            stored["received_at"] = _utc_now()
            self._status = stored
            if stored.get("clear_current"):
                self._cleared_sequence = self._sequence
            snapshot = self._snapshot_locked()
            for subscriber in self._subscribers:
                _put_latest(subscriber, snapshot)
        return snapshot

    def snapshot(self) -> dict:
        """Return the current overlay state."""
        with self._lock:
            return self._snapshot_locked()

    def clear(self) -> dict:
        """Clear runtime-only playback context and notify state subscribers."""
        with self._lock:
            self._events.clear()
            self._status = None
            self._sequence += 1
            self._cleared_sequence = self._sequence
            snapshot = self._snapshot_locked()
            for subscriber in self._subscribers:
                _put_latest(subscriber, snapshot)
        return snapshot

    def subscribe(self) -> Queue:
        """Subscribe to future snapshots through a latest-state mailbox."""
        subscriber: Queue = Queue(maxsize=1)
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: Queue) -> None:
        """Remove a previously registered SSE subscriber."""
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    @property
    def subscriber_count(self) -> int:
        """Return the number of active SSE subscribers."""
        with self._lock:
            return len(self._subscribers)

    def _trim_locked(self) -> None:
        if len(self._events) <= self.max_events:
            return
        ordered = sorted(self._events.values(), key=_event_sort_key, reverse=True)
        keep_keys = {
            str(event.get("live_event_key") or event.get("event_key"))
            for event in ordered[: self.max_events]
        }
        self._events = {
            key: value
            for key, value in self._events.items()
            if key in keep_keys
        }

    def _snapshot_locked(self) -> dict:
        events = sorted(self._events.values(), key=_event_sort_key, reverse=True)
        current = next(
            (
                event
                for event in events
                if _is_current_event(event, cleared_sequence=self._cleared_sequence)
            ),
            None,
        )
        return {
            "generated_at": _utc_now(),
            "sequence": self._sequence,
            "overlay_enabled": self.enabled,
            "current": current,
            "current_view": build_overlay_view_model(current),
            "events": events,
            "status": self._status,
        }


class MountedOverlayAdapter:
    """Gate watcher publication to an overlay mounted on an existing server."""

    def __init__(
        self,
        state: OverlayState,
        *,
        url: str,
        live_state: OverlayState | None = None,
    ) -> None:
        self.state = state
        self.live_state = live_state or OverlayState(max_events=state.max_events)
        self.url = url
        self._enabled = state.enabled
        self._lock = threading.RLock()

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def enable(self) -> dict:
        """Enable publication and restore the latest watcher context."""
        with self._lock:
            if self._enabled:
                return self.state.snapshot()
            self._enabled = True
            snapshot = self.state.publish_status(
                {
                    "event_type": "overlay-started",
                    "message": "Waiting for playback",
                    "overlay_enabled": True,
                    "clear_current": True,
                }
            )
            shadow = self.live_state.snapshot()
            if shadow["current"] is not None:
                snapshot = self.state.publish(shadow["current"])
            elif shadow["status"] is not None:
                snapshot = self.state.publish_status(shadow["status"])
            return snapshot

    def disable(self) -> dict:
        """Stop publication without stopping or resetting the watcher."""
        with self._lock:
            if not self._enabled:
                return self.state.snapshot()
            self._enabled = False
            return self.state.publish_status(
                {
                    "event_type": "overlay-stopped",
                    "message": "Overlay inactive",
                    "overlay_enabled": False,
                    "clear_current": True,
                }
            )

    def publish(self, event: dict) -> dict:
        with self._lock:
            self.live_state.publish(event)
            if not self._enabled:
                return self.state.snapshot()
            return self.state.publish(event)

    def publish_status(self, status: dict) -> dict:
        with self._lock:
            self.live_state.publish_status(status)
            if not self._enabled:
                return self.state.snapshot()
            return self.state.publish_status(status)

    def close(self) -> None:
        with self._lock:
            self.live_state.clear()
            self.disable()

    def borrow(self) -> "MountedOverlayPublisher":
        """Return a watcher-facing publisher that does not own this adapter."""
        return MountedOverlayPublisher(self)


class MountedOverlayPublisher:
    """Borrowed watcher view of a Web UI-owned mounted overlay adapter."""

    def __init__(self, adapter: MountedOverlayAdapter) -> None:
        self._adapter = adapter
        self.url = adapter.url

    def publish(self, event: dict) -> dict:
        return self._adapter.publish(event)

    def publish_status(self, status: dict) -> dict:
        return self._adapter.publish_status(status)

    def close(self) -> None:
        """Release this borrowed view without closing the session-owned adapter."""
        return None



class OverlayEventStreams:
    """Own SSE subscriptions for one HTTP server lifetime."""

    def __init__(self, state: OverlayState) -> None:
        self.state = state
        self.stop_event = threading.Event()
        self._lock = threading.Lock()
        self._subscribers: dict[Queue, object] = {}
        self._drained = threading.Event()
        self._drained.set()

    @property
    def stopped(self) -> bool:
        return self.stop_event.is_set()

    def subscribe(self, connection: object) -> Queue | None:
        with self._lock:
            if self.stop_event.is_set():
                return None
            subscriber = self.state.subscribe()
            self._subscribers[subscriber] = connection
            self._drained.clear()
            return subscriber

    def unsubscribe(self, subscriber: Queue) -> None:
        with self._lock:
            if subscriber not in self._subscribers:
                return
            del self._subscribers[subscriber]
            self.state.unsubscribe(subscriber)
            if not self._subscribers:
                self._drained.set()

    def stop(self) -> None:
        """Wake and stop every stream owned by this server."""
        with self._lock:
            self.stop_event.set()
            for subscriber in self._subscribers:
                _put_latest(subscriber, _STOP_EVENT_STREAM)
            connections = list(self._subscribers.values())
        for connection in connections:
            _close_stream_connection(connection)

    def wait_until_drained(self, timeout: float) -> bool:
        return self._drained.wait(timeout=timeout)


class OverlayServer:
    """Small local HTTP/SSE server for OBS Browser Source."""

    def __init__(
        self,
        *,
        host: str = OVERLAY_HOST,
        port: int,
        state: OverlayState | None = None,
    ) -> None:
        if host != OVERLAY_HOST:
            raise ValueError("overlay server must bind to 127.0.0.1")
        self.host = host
        self.port = port
        self.state = state or OverlayState()
        self._server: _OverlayHTTPServer | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}{OVERLAY_PAGE_PATH}"

    def start(self) -> None:
        server = _OverlayHTTPServer((self.host, self.port), _OverlayHandler, self.state)
        self.port = int(server.server_address[1])
        server.start_http(thread_name="DancingLogOverlayHTTP")
        self._server = server

    def stop(self) -> None:
        if self._server is not None:
            server = self._server
            try:
                server.stop_http()
            finally:
                self._server = None

    def publish(self, event: dict) -> dict:
        return self.state.publish(event)

    def publish_status(self, status: dict) -> dict:
        return self.state.publish_status(status)

    def snapshot(self) -> dict:
        return self.state.snapshot()


class _OverlayHTTPServer(ManagedLocalHTTPServer):
    def __init__(self, server_address, request_handler_class, state: OverlayState) -> None:
        self.state = state
        self.event_streams = OverlayEventStreams(state)
        super().__init__(
            server_address,
            request_handler_class,
            accepted_operation_shutdown=AcceptedOperationShutdown.CANCEL,
            shutdown_participants=(
                HttpShutdownParticipant(
                    "overlay event streams",
                    self.event_streams,
                    EVENT_STREAM_DRAIN_TIMEOUT_SECONDS,
                ),
            ),
        )


class _OverlayHandler(ManagedLocalHTTPRequestHandler):
    server: _OverlayHTTPServer

    def do_GET(self) -> None:
        if not is_allowed_local_http_host(
            self.headers.get("Host", ""),
            port=int(self.server.server_address[1]),
        ):
            self._send_bytes(403, "text/plain; charset=utf-8", b"invalid Host\n")
            return
        self.perform_operation(self._serve_overlay_request)

    def _serve_overlay_request(self) -> None:
        path = urlparse(self.path).path
        if path == OVERLAY_PAGE_PATH:
            self._send_bytes(200, "text/html; charset=utf-8", _OVERLAY_HTML.encode("utf-8"))
        elif path in {OVERLAY_STATE_PATH, "/state"}:
            payload = json.dumps(
                self.server.state.snapshot(),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            self._send_bytes(200, "application/json; charset=utf-8", payload)
        elif path in {OVERLAY_EVENTS_PATH, "/events"}:
            send_overlay_events(self, self.server.event_streams)
        else:
            self._send_bytes(404, "text/plain; charset=utf-8", b"not found\n")

    def log_message(self, format: str, *args) -> None:
        return

    def _send_bytes(self, status: int, content_type: str, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)



def send_overlay_events(
    handler: BaseHTTPRequestHandler,
    event_streams: OverlayEventStreams,
) -> None:
    """Stream overlay snapshots through any localhost HTTP handler."""
    subscriber = event_streams.subscribe(handler.connection)
    if subscriber is None:
        handler.send_response(503)
        handler.send_header("Content-Length", "0")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.close_connection = True
        return
    try:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Connection", "keep-alive")
        handler.end_headers()
        if event_streams.stopped:
            return
        _write_sse(handler, event_streams.state.snapshot())
        while not event_streams.stopped:
            try:
                snapshot = subscriber.get(timeout=15)
                if snapshot is _STOP_EVENT_STREAM or event_streams.stopped:
                    break
                _write_sse(handler, snapshot)
            except Empty:
                if event_streams.stopped:
                    break
                handler.wfile.write(b": ping\n\n")
                handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        handler.close_connection = True
        event_streams.unsubscribe(subscriber)


def _put_latest(queue: Queue, item: object) -> None:
    """Replace stale queued state so consumers always receive the latest item."""
    while True:
        try:
            queue.put_nowait(item)
            return
        except Full:
            try:
                queue.get_nowait()
            except Empty:
                pass


def _close_stream_connection(connection: object) -> None:
    """Interrupt a stream handler blocked in socket write or flush."""
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        connection.close()
    except OSError:
        pass


def _write_sse(handler: BaseHTTPRequestHandler, snapshot: dict) -> None:
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    handler.wfile.write(f"event: state\ndata: {payload}\n\n".encode("utf-8"))
    handler.wfile.flush()


def _event_sort_key(event: dict) -> tuple[str, str, str]:
    return (
        str(event.get("actual_play_at") or event.get("first_seen_at") or ""),
        str(event.get("received_at") or ""),
        str(event.get("event_key") or ""),
    )


def _is_current_event(event: dict, *, cleared_sequence: int) -> bool:
    sequence = int(event.get("_overlay_sequence") or 0)
    if sequence <= cleared_sequence:
        return False
    return event.get("completion_status") != "interrupted"


def _utc_now() -> str:
    return now_utc_iso()


def render_overlay_html() -> str:
    """Return the self-contained OBS overlay page."""
    return _OVERLAY_HTML


_OVERLAY_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>dancing-log overlay</title>
<style>
:root {
  --text: #fff;
  --stroke: #000;
}
* { box-sizing: border-box; }
html, body { margin: 0; width: 100%; height: 100%; background: transparent; }
body {
  display: flex;
  align-items: center;
  font-family: Consolas, Menlo, Monaco, "Segoe UI", monospace;
  color: var(--text);
  overflow: hidden;
}
.overlay {
  width: 100vw;
  display: grid;
  gap: 5px;
  padding: 8px 14px;
  background: transparent;
}
.line {
  min-width: 0;
  color: var(--text);
  font-weight: 700;
  line-height: 1.08;
  letter-spacing: 0;
  white-space: nowrap;
  -webkit-text-stroke: 3px var(--stroke);
  paint-order: stroke fill;
  font-variant-numeric: tabular-nums;
}
.iso-time {
  font-size: 48px;
}
.meta {
  font-size: 34px;
}
.title-frame {
  width: 100%;
  overflow: hidden;
  font-size: 42px;
}
.title-text {
  display: inline-block;
  max-width: none;
  transform: translateX(0);
  will-change: transform;
}
.title-text.is-scrolling {
  animation: title-scroll var(--scroll-duration, 16s) ease-in-out infinite alternate;
}
.source {
  font-size: 30px;
}
@keyframes title-scroll {
  0%, 12% { transform: translateX(0); }
  88%, 100% { transform: translateX(var(--scroll-x, 0px)); }
}
@media (max-width: 760px) {
  .overlay { padding: 8px 10px; gap: 4px; }
  .iso-time { font-size: 32px; }
  .meta { font-size: 24px; }
  .title-frame { font-size: 28px; }
  .source { font-size: 22px; }
  .line { -webkit-text-stroke-width: 2px; }
}
</style>
</head>
<body>
<main class="overlay" aria-live="polite">
  <div class="line iso-time" id="iso-time">0000-00-00T00:00:00+00:00</div>
  <div class="line meta" id="meta">loading</div>
  <div class="line title-frame"><span class="title-text" id="title">Loading overlay state</span></div>
  <div class="line source" id="source-player">checking Live Overlay status</div>
</main>
<script>
const state = { sequence: -1, current: null, currentView: null };
const nodes = {
  isoTime: document.getElementById("iso-time"),
  meta: document.getElementById("meta"),
  title: document.getElementById("title"),
  titleFrame: document.querySelector(".title-frame"),
  sourcePlayer: document.getElementById("source-player")
};

function parseVrcTime(value) {
  if (!value) return null;
  const match = String(value).match(/^(\\d{4})\\.(\\d{2})\\.(\\d{2}) (\\d{2}):(\\d{2}):(\\d{2})(?:\\.(\\d+))?/);
  if (!match) return null;
  const ms = Number((match[7] || "0").padEnd(3, "0").slice(0, 3));
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4]), Number(match[5]), Number(match[6]), ms);
}

function formatIso8601Local(date) {
  const pad = value => String(value).padStart(2, "0");
  const offset = -date.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const offsetHours = pad(Math.floor(Math.abs(offset) / 60));
  const offsetMinutes = pad(Math.abs(offset) % 60);
  return [
    date.getFullYear(),
    "-",
    pad(date.getMonth() + 1),
    "-",
    pad(date.getDate()),
    "T",
    pad(date.getHours()),
    ":",
    pad(date.getMinutes()),
    ":",
    pad(date.getSeconds()),
    sign,
    offsetHours,
    ":",
    offsetMinutes
  ].join("");
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  const mins = Math.floor(total / 60);
  const secs = String(total % 60).padStart(2, "0");
  return `${mins}:${secs}`;
}

function updateTitleScroll() {
  nodes.title.classList.remove("is-scrolling");
  nodes.title.style.removeProperty("--scroll-x");
  nodes.title.style.removeProperty("--scroll-duration");
  const overflow = nodes.title.scrollWidth - nodes.titleFrame.clientWidth;
  if (overflow <= 2) return;
  nodes.title.style.setProperty("--scroll-x", `${-overflow}px`);
  nodes.title.style.setProperty("--scroll-duration", `${Math.min(30, Math.max(10, overflow / 24))}s`);
  nodes.title.classList.add("is-scrolling");
}

function updateClock() {
  const now = new Date();
  nodes.isoTime.textContent = formatIso8601Local(now);
  const event = state.current;
  const view = state.currentView;
  if (!event || !view) return;
  const started = parseVrcTime(event.actual_play_at);
  const elapsed = started ? Math.max(0, (Date.now() - started.getTime()) / 1000) : 0;
  updateMeta(view, elapsed);
}

function visibleStatus(snapshot) {
  const status = snapshot.status || null;
  if (!status) return null;
  const statusSequence = Number(status._overlay_sequence || 0);
  const latestEventSequence = (snapshot.events || []).reduce(
    (latest, event) => Math.max(latest, Number(event._overlay_sequence || 0)),
    0
  );
  if (status.event_type === "room-entering" && latestEventSequence > statusSequence) {
    return null;
  }
  return status;
}

function render(snapshot) {
  const sequence = Number(snapshot.sequence || 0);
  if (sequence < state.sequence) return;
  state.sequence = sequence;
  state.current = snapshot.current || null;
  state.currentView = snapshot.current_view || null;
  if (snapshot.overlay_enabled !== true) {
    state.current = null;
    state.currentView = null;
    nodes.title.textContent = "Overlay inactive";
    nodes.meta.textContent = "disabled";
    nodes.sourcePlayer.textContent = "enable Live Overlay in WebUI";
    requestAnimationFrame(updateTitleScroll);
    updateClock();
    return;
  }
  const event = state.current;
  const view = state.currentView;
  if (!event || !view) {
    const status = visibleStatus(snapshot);
    nodes.title.textContent = status && status.message
      ? status.message
      : "Waiting for playback";
    nodes.meta.textContent = "waiting";
    nodes.sourcePlayer.textContent = "watcher active; no playback captured";
    requestAnimationFrame(updateTitleScroll);
    updateClock();
    return;
  }
  nodes.title.textContent = view.title || "Waiting for playback";
  nodes.sourcePlayer.textContent = view.source_label || "source unknown";
  requestAnimationFrame(updateTitleScroll);
  updateClock();
}

function formatTimer(timer, elapsed) {
  const mode = String((timer && timer.mode) || "elapsed");
  const duration = Number(timer && timer.duration_seconds);
  if (mode === "elapsed_total" && Number.isFinite(duration) && duration > 0) {
    const displayElapsed = Math.min(elapsed, duration);
    return `${formatDuration(displayElapsed)}/${formatDuration(duration)}`;
  }
  return formatDuration(elapsed);
}

function updateMeta(view, elapsed) {
  const parts = [
    view.system_track_label || "-- ID: ?",
    formatTimer(view.timer, elapsed)
  ];
  const series = String(view.series_name || "").trim();
  if (series) parts.push(series);
  nodes.meta.textContent = parts.join(" | ");
}

async function loadInitialState() {
  const response = await fetch("/api/overlay/state", { cache: "no-store" });
  render(await response.json());
}

loadInitialState().catch(() => {});
const events = new EventSource("/api/overlay/events");
events.addEventListener("state", event => render(JSON.parse(event.data)));
addEventListener("resize", updateTitleScroll);
setInterval(updateClock, 250);
</script>
</body>
</html>
"""
