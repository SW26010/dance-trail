# Keep the desktop tray entry single-instance

Date: 2026-07-18

## Status

Accepted

## Context

The frozen `DanceTrail.exe` desktop entry previously started a new Local Web UI
listener and tray session every time it was launched. Python's HTTP server uses
`SO_REUSEADDR`; on Windows that can allow two processes to bind the same local
address, so port binding was not a safe substitute for explicit app-instance
ownership. The watcher lifetime lease protects watcher and database writers,
not the Desktop Tray Entry or its HTTP listener.

## Decision

The Windows Desktop Tray Entry owns the named mutex
`Local\DanceTrail.DesktopTray.v1` before it creates the app session or binds the
Local Web UI. The mutex is scoped to the interactive Windows session, matching
notification-area ownership. A later launch runs a bounded election loop. Each
iteration first tries to acquire a released or abandoned mutex, then probes the
existing `/home` page and verifies the `dance-trail` page identity. A ready
owner is opened in the default browser; a released owner lets the waiting
process become the replacement primary. The loop otherwise continues for five
seconds before showing a visible failure. A default-browser failure is also
shown visibly rather than opening an unrelated service on the same port.
The identity probe uses a direct localhost HTTP opener with proxy discovery
disabled. Expected socket and HTTP protocol failures remain inside its boolean
activation boundary so every failure reaches the same visible error path.
The Desktop Tray Entry always uses the canonical `127.0.0.1:8787` listener;
custom ports remain available only through the standalone `webui` command, whose
lifetime is not represented by the desktop mutex.

The mutex, Web UI server, and Live App Session Runtime are handed to one
idempotent shutdown coordinator. Normal tray exit and `WM_ENDSESSION(TRUE)` use
that same coordinator in server, runtime, mutex order. Normal exit fully drains
accepted HTTP operations and watcher settlement. End-session handling instead
propagates one absolute four-second deadline through HTTP request drain,
participant drain, lifecycle-transition waits, and watcher join. Every cleanup
action is still attempted, including mutex release, and combined failures remain
grouped. This leaves margin inside Windows' five-second notification window and
avoids claiming that a pathological non-cooperative operation always settles.
The app does not register a shutdown block reason for this bounded routine;
future genuinely non-interruptible work would require creating and destroying a
short, user-visible reason around that operation.

Windows local HTTP listeners also use `SO_EXCLUSIVEADDRUSE` instead of address
reuse. This is a defense-in-depth listener invariant and keeps Web UI-only or
other local HTTP entry points from silently sharing an address.

The watcher lifetime lease remains separate because it owns a different
invariant: exclusive watcher/database writing across CLI, Web UI, and tray
callers.

## Consequences

Launching `DanceTrail.exe` while it is already present in the notification area
acts as an Open Web UI command. Simultaneous launches converge on one app
session, and abnormal first-instance startup no longer permits two listeners to
share `127.0.0.1:8787`.

The portable smoke gate launches the frozen desktop executable repeatedly. It
requires the second process to exit, records the exact `/home` browser
activation, verifies one listener owner, and starts a replacement after the
first process exits. It also starts the executable behind a synthetic mutex
owner, releases that owner before the activation deadline, and requires the
same waiting process to take ownership and become the sole listener.

CLI commands are not redirected to the tray process. A standalone `webui`
command that targets an occupied address fails explicitly, while watcher
commands continue to use their existing app/database lifetime lease.
