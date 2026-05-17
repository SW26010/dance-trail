import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from dancing_log.storage import WANNA_SYSTEM_KEY
from dancing_log.vrc_log_watcher import parse_vrc_log_line, watch_vrc_logs


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class VrcLogParserTest(unittest.TestCase):
    def test_parses_video_playback_resolve_and_classifies_wanna(self):
        events = parse_vrc_log_line(
            "2026.05.17 15:30:00 Log - [Video Playback] "
            "Resolving URL 'https://api.udon.dance/Api/Songs/play?id=3114'"
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].timestamp, "2026.05.17 15:30:00")
        self.assertEqual(events[0].video_url, "https://api.udon.dance/Api/Songs/play?id=3114")
        self.assertEqual(events[0].parser_name, "video_playback_resolve")
        record = events[0].to_capture_record()
        self.assertEqual(record["dance_system_key"], WANNA_SYSTEM_KEY)
        self.assertEqual(record["dance_external_id"], "3114")

    def test_parses_user_added_url_and_usharp_requester(self):
        user_events = parse_vrc_log_line(
            "2026.05.17 15:30:01 Log - User Alice Example added URL "
            "http://play.udon.dance/files/2502/5038-abcdef.mp4"
        )
        usharp_events = parse_vrc_log_line(
            "2026.05.17 15:30:02 Log - [USharpVideo] Started video load for URL: "
            "https://api.udon.dance/Api/Songs/play?id=6495, requested by Bob"
        )

        self.assertEqual(user_events[0].display_name, "Alice Example")
        self.assertEqual(user_events[0].to_capture_record()["dance_external_id"], "5038")
        self.assertEqual(usharp_events[0].display_name, "Bob")
        self.assertEqual(usharp_events[0].to_capture_record()["dance_external_id"], "6495")

        colored_events = parse_vrc_log_line(
            "2026.05.17 15:30:02 Log - "
            "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
            "Started video load for URL: https://api.udon.dance/Api/Songs/play?id=3881, "
            "requested by 示例玩家乙"
        )
        self.assertEqual(colored_events[0].event_type, "load-start")
        self.assertEqual(colored_events[0].display_name, "示例玩家乙")
        self.assertEqual(colored_events[0].to_capture_record()["dance_external_id"], "3881")

    def test_parses_vrcx_video_play_payloads(self):
        pypy_events = parse_vrc_log_line(
            '2026.05.17 15:30:03 Log - [VRCX] VideoPlay(PyPyDance) '
            '"http://jd.pypy.moe/api/v1/videos/4051.mp4","Carol"'
        )
        json_events = parse_vrc_log_line(
            '2026.05.17 15:30:04 Log - [VRCX] VideoPlay(PopcornPalace) '
            '{"url":"https://api.dudufit.dance/api/v1/videos/1321?cdn=jpn",'
            '"displayName":"Dana"}'
        )

        self.assertEqual(pypy_events[0].world_parser, "PyPyDance")
        self.assertEqual(pypy_events[0].display_name, "Carol")
        self.assertEqual(pypy_events[0].to_capture_record()["url_kind"], "pypydance_api")
        self.assertEqual(json_events[0].world_parser, "PopcornPalace")
        self.assertEqual(json_events[0].display_name, "Dana")
        self.assertEqual(json_events[0].to_capture_record()["url_kind"], "dudu")

    def test_parses_vrcx_video_play_offset_duration_title_and_requester_marker(self):
        events = parse_vrc_log_line(
            '2026.05.17 15:50:18 Debug - [VRCX] VideoPlay(PyPyDance) '
            '"http://api.pypy.dance/video?id=4666",0,150,'
            '"4666 : [MIRRORED] NewJeans - ETA dance cover (示例玩家乙)"'
        )

        self.assertEqual(events[0].display_name, "示例玩家乙")
        self.assertEqual(events[0].requester_marker, "示例玩家乙")
        self.assertEqual(events[0].video_offset_seconds, 0.0)
        self.assertEqual(events[0].duration_seconds, 150.0)
        self.assertEqual(events[0].video_id, "4666")
        self.assertEqual(events[0].video_name, "[MIRRORED] NewJeans - ETA dance cover")
        self.assertEqual(events[0].to_capture_record()["dance_system_key"], "pypydance")
        self.assertEqual(events[0].to_capture_record()["dance_external_id"], "4666")

        random_events = parse_vrc_log_line(
            '2026.05.17 15:46:16 Debug - [VRCX] VideoPlay(PyPyDance) '
            '"http://api.udon.dance/Api/Songs/play?node=cf&id=3881",0,114514,'
            '"$3881. Kung Fu Fighting - Carl Douglas (Random)"'
        )
        self.assertIsNone(random_events[0].display_name)
        self.assertEqual(random_events[0].requester_marker, "Random")
        self.assertEqual(random_events[0].source_hint, "random")
        self.assertIsNone(random_events[0].duration_seconds)

    def test_parses_vrcx_progress_offset_as_actual_play_signal(self):
        events = parse_vrc_log_line(
            '2026.05.17 15:30:10 Debug - [VRCX] VideoPlay(PyPyDance) '
            '"http://api.pypy.dance/video?id=4664",0.25,167,'
            '"4664 : [KPOP] KISS OF LIFE - Who is she (示例玩家乙)"'
        )

        self.assertEqual(events[0].event_type, "playback-progress")
        self.assertEqual(events[0].actual_play_at, "2026.05.17 15:30:09.75")
        self.assertEqual(events[0].actual_play_signal_at, "2026.05.17 15:30:10")
        self.assertEqual(events[0].actual_play_offset_seconds, 0.25)
        self.assertEqual(events[0].actual_play_method, "vrcx_progress_offset")

    def test_parses_usharp_playing_synced_as_mid_play_signal(self):
        events = parse_vrc_log_line(
            "2026.05.17 15:30:10 Debug - "
            "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
            "Playing synced http://api.udon.dance/Api/Songs/play?id=3823"
        )

        self.assertEqual(events[0].event_type, "playback-sync")
        self.assertEqual(events[0].parser_name, "usharp_playing_synced")
        self.assertEqual(events[0].to_capture_record()["dance_external_id"], "3823")

    def test_ignores_unrelated_lines(self):
        self.assertEqual(parse_vrc_log_line("2026.05.17 15:30:05 Log - Joined room"), [])


class VrcLogWatcherTest(unittest.TestCase):
    def test_watcher_reads_existing_file_from_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            (log_dir / "output_log_0001.txt").write_text(
                "noise\n"
                "2026.05.17 15:30:00 Log - [Video Playback] "
                "Resolving URL 'https://api.udon.dance/Api/Songs/play?id=3114'\n",
                encoding="utf-8",
            )

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="from-start",
                from_start=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            self.assertEqual(stats.raw_lines, 2)
            self.assertEqual(stats.candidate_lines, 1)
            self.assertEqual(stats.parsed_events, 1)
            self.assertEqual(stats.playback_events, 1)
            parsed = read_jsonl(stats.session_dir / "parsed_events.jsonl")
            self.assertEqual(parsed[0]["dance_external_id"], "3114")
            playback = read_jsonl(stats.session_dir / "playback_events.jsonl")
            self.assertEqual(playback[0]["dance_external_id"], "3114")
            self.assertTrue((stats.session_dir / "raw_output_log.txt").exists())
            self.assertTrue((stats.session_dir / "summary.json").exists())

    def test_watcher_defaults_to_current_eof_then_reads_appended_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            log_path = log_dir / "output_log_0001.txt"
            log_path.write_text(
                "2026.05.17 15:30:00 Log - [Video Playback] "
                "Resolving URL 'https://api.udon.dance/Api/Songs/play?id=3114'\n",
                encoding="utf-8",
            )

            def append_line():
                time.sleep(0.05)
                with open(log_path, "a", encoding="utf-8") as handle:
                    handle.write(
                        "2026.05.17 15:30:01 Log - [Video Playback] "
                        "Resolving URL 'https://api.udon.dance/Api/Songs/play?id=5038'\n"
                    )

            thread = threading.Thread(target=append_line)
            thread.start()
            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="append",
                from_start=False,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.15,
            )
            thread.join()

            self.assertEqual(stats.parsed_events, 1)
            parsed = read_jsonl(stats.session_dir / "parsed_events.jsonl")
            self.assertEqual(parsed[0]["dance_external_id"], "5038")

    def test_watcher_reads_new_rotated_file_from_beginning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            (log_dir / "output_log_0001.txt").write_text("old\n", encoding="utf-8")

            def create_rotated_file():
                time.sleep(0.05)
                (log_dir / "output_log_9999.txt").write_text(
                    "2026.05.17 15:30:02 Log - [Video Playback] "
                    "Resolving URL 'https://api.udon.dance/Api/Songs/play?id=6495'\n",
                    encoding="utf-8",
                )

            thread = threading.Thread(target=create_rotated_file)
            thread.start()
            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="rotate",
                from_start=False,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.15,
            )
            thread.join()

            self.assertEqual(stats.parsed_events, 1)
            parsed = read_jsonl(stats.session_dir / "parsed_events.jsonl")
            self.assertEqual(parsed[0]["dance_external_id"], "6495")
            self.assertEqual(parsed[0]["line_number"], 1)

    def test_watcher_writes_playback_events_with_delay_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            (log_dir / "output_log_0001.txt").write_text(
                "2026.05.17 15:30:00 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "PlayVideoInternal: Playing video https://api.udon.dance/Api/Songs/play?id=3114\n"
                "2026.05.17 15:30:00 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "Started video load for URL: https://api.udon.dance/Api/Songs/play?id=3114, "
                "requested by 示例玩家乙\n"
                '2026.05.17 15:30:00 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"https://api.udon.dance/Api/Songs/play?node=cf&id=3114",0,114514,'
                '"$3114. Example Song (Random)"\n'
                "2026.05.17 15:30:02 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "Video loaded (2.0 seconds), but let's wait for 8.0 seconds before playing it\n"
                "2026.05.17 15:30:10 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "DelayedVideoReady: Time's up, let's play\n",
                encoding="utf-8",
            )

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="delay",
                from_start=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            self.assertEqual(stats.playback_events, 1)
            self.assertEqual(stats.delay_metrics["count"], 1)
            self.assertEqual(stats.delay_metrics["avg_seconds"], 10.0)
            playback = read_jsonl(stats.session_dir / "playback_events.jsonl")
            self.assertEqual(playback[0]["delay_to_actual_seconds"], 10.0)
            self.assertEqual(playback[0]["load_to_actual_seconds"], 8.0)
            self.assertEqual(playback[0]["display_name"], "示例玩家乙")
            self.assertEqual(playback[0]["source_type"], "random")
            self.assertIsNone(playback[0]["source_display_name"])

    def test_watcher_keeps_repeated_same_track_as_separate_occurrences(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            (log_dir / "output_log_0001.txt").write_text(
                "2026.05.17 15:30:00 Debug - [Video Playback] "
                "Resolving URL 'https://api.udon.dance/Api/Songs/play?id=3114'\n"
                "2026.05.17 15:30:05 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "DelayedVideoReady: Time's up, let's play\n"
                "2026.05.17 15:31:00 Debug - [Video Playback] "
                "Resolving URL 'https://api.udon.dance/Api/Songs/play?id=3114'\n"
                "2026.05.17 15:31:05 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "DelayedVideoReady: Time's up, let's play\n",
                encoding="utf-8",
            )

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="repeat",
                from_start=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            playback = read_jsonl(stats.session_dir / "playback_events.jsonl")
            self.assertEqual(stats.playback_events, 2)
            self.assertEqual([event["canonical_key"] for event in playback], ["wannadance:3114", "wannadance:3114"])
            self.assertEqual([event["event_key"] for event in playback], ["wannadance:3114#1", "wannadance:3114#2"])

    def test_watcher_estimates_actual_play_from_vrcx_progress_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            (log_dir / "output_log_0001.txt").write_text(
                "2026.05.17 15:30:00 Debug - [Video Playback] "
                "Attempting to resolve URL 'http://api.pypy.dance/video?id=4664'\n"
                '2026.05.17 15:30:01 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"http://api.pypy.dance/video?id=4664",0,167,'
                '"4664 : [KPOP] KISS OF LIFE - Who is she (示例玩家乙)"\n'
                "2026.05.17 15:30:02 Debug - [Video Playback] URL "
                "'http://api.pypy.dance/video?id=4664' resolved to "
                "'http://806bb815.cdn.pypy.dance/kTkjQjbHLSQ.mp4'\n"
                '2026.05.17 15:30:10 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"http://api.pypy.dance/video?id=4664",0.25,167,'
                '"4664 : [KPOP] KISS OF LIFE - Who is she (示例玩家乙)"\n',
                encoding="utf-8",
            )

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="pypy-progress",
                from_start=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            self.assertEqual(stats.playback_events, 1)
            self.assertEqual(stats.delay_metrics["count"], 1)
            playback = read_jsonl(stats.session_dir / "playback_events.jsonl")
            self.assertEqual(playback[0]["actual_play_at"], "2026.05.17 15:30:09.75")
            self.assertEqual(playback[0]["actual_play_signal_at"], "2026.05.17 15:30:10")
            self.assertEqual(playback[0]["actual_play_offset_seconds"], 0.25)
            self.assertEqual(playback[0]["actual_play_method"], "vrcx_progress_offset")
            self.assertEqual(playback[0]["delay_to_actual_seconds"], 9.75)
            self.assertEqual(playback[0]["source_type"], "player")
            self.assertEqual(playback[0]["source_display_name"], "示例玩家乙")
            self.assertIn("playback-progress", playback[0]["raw_event_types"])

    def test_watcher_marks_mid_play_from_large_vrcx_progress_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            (log_dir / "output_log_0001.txt").write_text(
                "2026.05.17 15:30:00 Debug - [Video Playback] "
                "Attempting to resolve URL 'http://api.pypy.dance/video?id=4603'\n"
                '2026.05.17 15:30:00 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"http://api.pypy.dance/video?id=4603",153.3415,177,'
                '"4603 : Spice Girls - Wannabe (Nanashi Neko)"\n',
                encoding="utf-8",
            )

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="pypy-mid-play",
                from_start=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            self.assertEqual(stats.playback_events, 1)
            self.assertEqual(stats.delay_metrics["count"], 0)
            playback = read_jsonl(stats.session_dir / "playback_events.jsonl")
            self.assertTrue(playback[0]["observed_mid_play"])
            self.assertEqual(playback[0]["elapsed_at_first_seen_seconds"], 153.341)
            self.assertIsNone(playback[0]["delay_to_actual_seconds"])

    def test_watcher_marks_wanna_playing_synced_as_mid_play(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            (log_dir / "output_log_0001.txt").write_text(
                "2026.05.17 15:30:00 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "Started video load for URL: http://api.udon.dance/Api/Songs/play?id=3823, "
                "requested by Alice\n"
                "2026.05.17 15:30:00 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "Playing synced http://api.udon.dance/Api/Songs/play?id=3823\n"
                "2026.05.17 15:30:02 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "OnVideoStart: Started video: http://api.udon.dance/Api/Songs/play?id=3823\n",
                encoding="utf-8",
            )

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="wanna-synced",
                from_start=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            self.assertEqual(stats.playback_events, 1)
            self.assertEqual(stats.delay_metrics["count"], 0)
            playback = read_jsonl(stats.session_dir / "playback_events.jsonl")
            self.assertTrue(playback[0]["observed_mid_play"])
            self.assertEqual(playback[0]["synced_play_at"], "2026.05.17 15:30:00")
            self.assertIsNone(playback[0]["delay_to_actual_seconds"])
            self.assertIn("playback-sync", playback[0]["raw_event_types"])


if __name__ == "__main__":
    unittest.main()
