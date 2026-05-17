"""Local-only OBS overlay server for live playback state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from queue import Empty, Full, Queue
import threading
from urllib.parse import urlparse


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
    return event.get("completion_status") not in {"completed", "interrupted"}


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
  color-scheme: dark;
  --ink: #f8fafc;
  --muted: #cbd5e1;
  --dim: #94a3b8;
  --line: rgba(255, 255, 255, 0.18);
  --panel: rgba(15, 23, 42, 0.72);
  --accent: #22d3ee;
  --good: #a3e635;
}
* { box-sizing: border-box; }
html, body { margin: 0; width: 100%; height: 100%; background: transparent; }
body {
  font-family: "Segoe UI", Arial, sans-serif;
  color: var(--ink);
  overflow: hidden;
}
.overlay {
  position: fixed;
  left: 28px;
  right: 28px;
  bottom: 28px;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 16px;
  align-items: end;
  padding: 18px 20px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.35);
}
.meta {
  display: flex;
  gap: 10px;
  align-items: center;
  min-width: 0;
  color: var(--muted);
  font-size: 18px;
}
.pill {
  padding: 3px 8px;
  border: 1px solid var(--line);
  border-radius: 999px;
  color: var(--good);
  font-weight: 700;
}
.title {
  margin-top: 7px;
  font-size: 34px;
  line-height: 1.12;
  font-weight: 760;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sub {
  margin-top: 8px;
  display: flex;
  gap: 14px;
  min-width: 0;
  color: var(--muted);
  font-size: 18px;
}
.sub span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.debug {
  margin-top: 9px;
  color: var(--dim);
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.time {
  min-width: 230px;
  text-align: right;
}
.clock {
  font-size: 42px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.elapsed {
  margin-top: 12px;
  color: var(--muted);
  font-size: 18px;
  font-variant-numeric: tabular-nums;
}
.bar {
  margin-top: 10px;
  width: 230px;
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.16);
}
.fill {
  width: 0%;
  height: 100%;
  background: var(--accent);
  transition: width 240ms linear;
}
@media (max-width: 760px) {
  .overlay { left: 14px; right: 14px; bottom: 14px; grid-template-columns: 1fr; }
  .title { font-size: 25px; white-space: normal; }
  .time { min-width: 0; text-align: left; }
  .clock { font-size: 32px; }
  .bar { width: 100%; }
}
</style>
</head>
<body>
<main class="overlay" aria-live="polite">
  <section>
    <div class="meta"><span class="pill" id="track-id">live</span><span id="system">waiting</span></div>
    <div class="title" id="title">Waiting for playback</div>
    <div class="sub"><span id="source">source unknown</span><span id="requester"></span></div>
    <div class="debug" id="debug"></div>
  </section>
  <section class="time">
    <div class="clock" id="clock">--:--</div>
    <div class="elapsed" id="elapsed">0:00</div>
    <div class="bar"><div class="fill" id="fill"></div></div>
  </section>
</main>
<script>
const state = { current: null };
const nodes = {
  trackId: document.getElementById("track-id"),
  system: document.getElementById("system"),
  title: document.getElementById("title"),
  source: document.getElementById("source"),
  requester: document.getElementById("requester"),
  debug: document.getElementById("debug"),
  clock: document.getElementById("clock"),
  elapsed: document.getElementById("elapsed"),
  fill: document.getElementById("fill")
};

function parseVrcTime(value) {
  if (!value) return null;
  const match = String(value).match(/^(\\d{4})\\.(\\d{2})\\.(\\d{2}) (\\d{2}):(\\d{2}):(\\d{2})(?:\\.(\\d+))?/);
  if (!match) return null;
  const ms = Number((match[7] || "0").padEnd(3, "0").slice(0, 3));
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4]), Number(match[5]), Number(match[6]), ms);
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  const mins = Math.floor(total / 60);
  const secs = String(total % 60).padStart(2, "0");
  return `${mins}:${secs}`;
}

function updateClock() {
  const now = new Date();
  nodes.clock.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const event = state.current;
  if (!event) return;
  const started = parseVrcTime(event.actual_play_at);
  const duration = Number(event.duration_seconds);
  if (!started) {
    nodes.elapsed.textContent = "0:00";
    nodes.fill.style.width = "0%";
    return;
  }
  const elapsed = Math.max(0, (Date.now() - started.getTime()) / 1000);
  nodes.elapsed.textContent = Number.isFinite(duration) && duration > 0
    ? `${formatDuration(elapsed)} / ${formatDuration(duration)}`
    : formatDuration(elapsed);
  nodes.fill.style.width = Number.isFinite(duration) && duration > 0
    ? `${Math.max(0, Math.min(100, (elapsed / duration) * 100))}%`
    : "0%";
}

function render(snapshot) {
  state.current = snapshot.current || null;
  const event = state.current;
  if (!event) {
    nodes.trackId.textContent = "live";
    nodes.system.textContent = "waiting";
    nodes.title.textContent = snapshot.status && snapshot.status.message
      ? snapshot.status.message
      : "Waiting for playback";
    nodes.source.textContent = "source unknown";
    nodes.requester.textContent = "";
    nodes.debug.textContent = "";
    updateClock();
    return;
  }
  const system = event.dance_system_key || "unknown";
  const external = event.dance_external_id || "?";
  nodes.trackId.textContent = `${system}:${external}`;
  nodes.system.textContent = event.observed_mid_play ? "mid-play" : "playing";
  nodes.title.textContent = event.video_name || event.video_url || `${system}:${external}`;
  nodes.source.textContent = event.source_type ? `source ${event.source_type}` : "source unknown";
  nodes.requester.textContent = event.source_display_name || "";
  const parts = [event.actual_play_method, event.observed_mid_play ? "mid-play" : "", event.source_file].filter(Boolean);
  nodes.debug.textContent = parts.join(" | ");
  updateClock();
}

async function loadInitialState() {
  const response = await fetch("/state", { cache: "no-store" });
  render(await response.json());
}

loadInitialState().catch(() => {});
const events = new EventSource("/events");
events.addEventListener("state", event => render(JSON.parse(event.data)));
setInterval(updateClock, 500);
</script>
</body>
</html>
"""
