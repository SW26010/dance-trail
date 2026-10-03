import unittest

from dance_trail.vrc_log_parser import (
    parse_vrc_identity_event,
    parse_vrc_lifecycle_event,
    parse_vrc_log_line,
)


class VrcLogParserModuleTest(unittest.TestCase):
    def test_parses_vrcx_payload_directly(self):
        events = parse_vrc_log_line(
            '2026.05.17 15:50:18 Debug - [VRCX] VideoPlay(PyPyDance) '
            '"http://api.pypy.dance/video?id=4666",0,150,'
            '"4666 : NewJeans - ETA dance cover (Alice)"'
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "request")
        self.assertEqual(events[0].world_parser, "PyPyDance")
        self.assertEqual(events[0].display_name, "Alice")
        self.assertEqual(events[0].duration_seconds, 150.0)
        self.assertEqual(events[0].to_capture_record()["dance_system_key"], "pypydance")
        self.assertEqual(events[0].to_capture_record()["dance_external_id"], "4666")

    def test_parses_structured_vrcx_requester_user_id(self):
        events = parse_vrc_log_line(
            '2026.05.17 15:50:18 Debug - [VRCX] VideoPlay(PopcornPalace) '
            '{"videoUrl":"http://api.udon.dance/Api/Songs/play?id=3114",'
            '"displayName":"Alice","userId":"usr_alice","title":"Promoted Title"}'
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].display_name, "Alice")
        self.assertEqual(events[0].requester_user_id, "usr_alice")
        self.assertEqual(events[0].to_capture_record()["requester_user_id"], "usr_alice")
        self.assertEqual(events[0].to_capture_record()["requester_user_id_source"], "payload")

    def test_ignores_non_vrchat_payload_player_id_as_requester_user_id(self):
        events = parse_vrc_log_line(
            '2026.05.17 15:50:18 Debug - [VRCX] VideoPlay(PopcornPalace) '
            '{"videoUrl":"http://api.udon.dance/Api/Songs/play?id=3114",'
            '"displayName":"Alice","playerId":"42","title":"Promoted Title"}'
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].display_name, "Alice")
        self.assertIsNone(events[0].requester_user_id)
        self.assertIsNone(events[0].to_capture_record()["requester_user_id"])
        self.assertIsNone(events[0].to_capture_record()["requester_user_id_source"])

    def test_parses_lifecycle_event_directly(self):
        event = parse_vrc_lifecycle_event(
            "2026.05.17 15:30:05 Debug - [Behaviour] OnLeftRoom"
        )

        self.assertEqual(event["event_type"], "room-left")
        self.assertTrue(event["clear_current"])

    def test_parses_transient_identity_events(self):
        joined = parse_vrc_identity_event(
            "2026.05.17 15:30:05 Debug - [Behaviour] OnPlayerJoined Alice (usr_alice)"
        )
        left = parse_vrc_identity_event(
            "2026.05.17 15:30:10 Debug - [Behaviour] OnPlayerLeft Alice (usr_alice)"
        )
        authenticated = parse_vrc_identity_event(
            "2026.05.17 15:29:59 Debug - User Authenticated: Alice (usr_alice)"
        )

        self.assertEqual(joined["event_type"], "player-joined")
        self.assertEqual(joined["display_name"], "Alice")
        self.assertEqual(joined["user_id"], "usr_alice")
        self.assertEqual(left["event_type"], "player-left")
        self.assertEqual(authenticated["event_type"], "user-authenticated")


if __name__ == "__main__":
    unittest.main()
