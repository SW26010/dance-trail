"""Local-only OBS overlay server for live playback state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from queue import Empty, Full, Queue
import sys
import threading
from urllib.parse import urlparse

from dancing_log.overlay_view_model import build_overlay_view_model


OVERLAY_HOST = "127.0.0.1"


@dataclass
class OverlayState:
    """Thread-safe in-memory state shared by HTTP and watcher threads."""

    max_events: int = 20
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
            subscribers = list(self._subscribers)

        for subscriber in subscribers:
            try:
                subscriber.put_nowait(snapshot)
            except Full:
                pass
        return snapshot

    def publish_status(self, status: dict) -> dict:
        """Publish a non-playback status update such as room leave or shutdown."""
        with self._lock:
            stored = dict(status)
            self._sequence += 1
            stored["_overlay_sequence"] = self._sequence
            stored["received_at"] = _utc_now()
            self._status = stored
            if stored.get("clear_current"):
                self._cleared_sequence = self._sequence
            snapshot = self._snapshot_locked()
            subscribers = list(self._subscribers)

        for subscriber in subscribers:
            try:
                subscriber.put_nowait(snapshot)
            except Full:
                pass
        return snapshot

    def snapshot(self) -> dict:
        """Return the current overlay state."""
        with self._lock:
            return self._snapshot_locked()

    def subscribe(self) -> Queue:
        """Subscribe to future snapshots."""
        subscriber: Queue = Queue(maxsize=10)
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: Queue) -> None:
        """Remove a previously registered SSE subscriber."""
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

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
            "current": current,
            "current_view": build_overlay_view_model(current),
            "events": events,
            "status": self._status,
        }


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
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/overlay"

    def start(self) -> None:
        self._server = _OverlayHTTPServer((self.host, self.port), _OverlayHandler, self.state)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def publish(self, event: dict) -> dict:
        return self.state.publish(event)

    def publish_status(self, status: dict) -> dict:
        return self.state.publish_status(status)

    def snapshot(self) -> dict:
        return self.state.snapshot()


class _OverlayHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, request_handler_class, state: OverlayState) -> None:
        super().__init__(server_address, request_handler_class)
        self.state = state

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)):
            return
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) in {10053, 10054}:
            return
        super().handle_error(request, client_address)


class _OverlayHandler(BaseHTTPRequestHandler):
    server: _OverlayHTTPServer

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/overlay":
            self._send_bytes(200, "text/html; charset=utf-8", _OVERLAY_HTML.encode("utf-8"))
        elif path == "/state":
            payload = json.dumps(
                self.server.state.snapshot(),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            self._send_bytes(200, "application/json; charset=utf-8", payload)
        elif path == "/events":
            self._send_events()
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

    def _send_events(self) -> None:
        subscriber = self.server.state.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self._write_sse(self.server.state.snapshot())
            while True:
                try:
                    snapshot = subscriber.get(timeout=15)
                    self._write_sse(snapshot)
                except Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.server.state.unsubscribe(subscriber)

    def _write_sse(self, snapshot: dict) -> None:
        payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        self.wfile.write(f"event: state\ndata: {payload}\n\n".encode("utf-8"))
        self.wfile.flush()


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
    return datetime.now(timezone.utc).isoformat()


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
  <div class="line meta" id="meta">waiting</div>
  <div class="line title-frame"><span class="title-text" id="title">Waiting for playback</span></div>
  <div class="line source" id="source-player">source player: unknown</div>
</main>
<script>
const state = { current: null, currentView: null };
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
  state.current = snapshot.current || null;
  state.currentView = snapshot.current_view || null;
  const event = state.current;
  const view = state.currentView;
  if (!event || !view) {
    const status = visibleStatus(snapshot);
    nodes.title.textContent = status && status.message
      ? status.message
      : "Waiting for playback";
    nodes.meta.textContent = "waiting";
    nodes.sourcePlayer.textContent = "source player: unknown";
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
  const response = await fetch("/state", { cache: "no-store" });
  render(await response.json());
}

loadInitialState().catch(() => {});
const events = new EventSource("/events");
events.addEventListener("state", event => render(JSON.parse(event.data)));
addEventListener("resize", updateTitleScroll);
setInterval(updateClock, 250);
</script>
</body>
</html>
"""
