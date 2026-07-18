import socket
import unittest

from dancing_log.http_request_lifecycle import (
    AcceptedOperationShutdown,
    HttpShutdownParticipant,
    ManagedLocalHTTPRequestHandler,
    ManagedLocalHTTPServer,
)


class _NoopHandler(ManagedLocalHTTPRequestHandler):
    def do_GET(self) -> None:
        self.perform_operation(self._send_empty_response)

    def _send_empty_response(self) -> None:
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return


class ManagedLocalHttpLifecycleTest(unittest.TestCase):
    def test_stop_attempts_all_lifecycle_cleanup_after_participant_failure(self):
        events: list[str] = []

        class FailingParticipant:
            def stop(self) -> None:
                events.append("participant.stop")
                raise RuntimeError("participant stop failed")

            def wait_until_drained(self, timeout: float) -> bool:
                events.append(f"participant.wait:{timeout:g}")
                return True

        server = ManagedLocalHTTPServer(
            ("127.0.0.1", 0),
            _NoopHandler,
            accepted_operation_shutdown=AcceptedOperationShutdown.DRAIN,
            shutdown_participants=(
                HttpShutdownParticipant(
                    "test participant",
                    FailingParticipant(),
                    0.25,
                ),
            ),
        )
        port = int(server.server_address[1])
        server.start_http(thread_name="DancingLogHttpLifecycleTest")

        with self.assertRaisesRegex(RuntimeError, "participant stop failed"):
            server.stop_http()

        self.assertEqual(
            events,
            ["participant.stop", "participant.wait:0.25"],
        )
        probe = socket.socket()
        try:
            probe.bind(("127.0.0.1", port))
        finally:
            probe.close()


if __name__ == "__main__":
    unittest.main()
