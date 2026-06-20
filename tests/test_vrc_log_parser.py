import unittest

from dancing_log.vrc_log_parser import parse_vrc_lifecycle_event, parse_vrc_log_line


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

    def test_parses_lifecycle_event_directly(self):
        event = parse_vrc_lifecycle_event(
            "2026.05.17 15:30:05 Debug - [Behaviour] OnLeftRoom"
        )

        self.assertEqual(event["event_type"], "room-left")
        self.assertTrue(event["clear_current"])


if __name__ == "__main__":
    unittest.main()
