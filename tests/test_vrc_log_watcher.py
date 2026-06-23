import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from dancing_log.storage import WANNA_SYSTEM_KEY, connect_db
from dancing_log.vrc_log_watcher import (
    parse_vrc_lifecycle_event,
    parse_vrc_log_line,
    replay_vrc_log_files,
    watch_vrc_logs,
)


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

    def test_parses_wannadance_preview_marker(self):
        events = parse_vrc_log_line(
            "2026.05.17 22:49:02 Debug - [VideoListManager] "
            "PreviewVideo: 3335 http://api.udon.dance/Api/Songs/play?id=3335, time 30 - 220"
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "preview")
        self.assertEqual(events[0].parser_name, "wannadance_preview")
        self.assertEqual(events[0].video_id, "3335")
        self.assertEqual(events[0].to_capture_record()["source_hint"], "preview")

        colored_events = parse_vrc_log_line(
            "2026.05.17 15:30:02 Log - "
            "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
            "Started video load for URL: https://api.udon.dance/Api/Songs/play?id=3881, "
            "requested by 示例玩家乙"
        )
        self.assertEqual(colored_events[0].event_type, "load-start")
        self.assertEqual(colored_events[0].display_name, "示例玩家乙")
        self.assertEqual(colored_events[0].to_capture_record()["dance_external_id"], "3881")

    def test_parses_wannadance_queue_metadata_duration(self):
        events = parse_vrc_log_line(
            '2026.05.17 19:46:33 Debug - [VideoQueueManager] [19:46:33] : '
            'OnPreSerialization: queue info serialized: '
            '[{"playerNames":["Alice"],"title":"8385. Poker Face","songId":8385,'
            '"duration":254,"group":"Just Dance Solo"}]'
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "metadata")
        self.assertEqual(events[0].parser_name, "wannadance_queue_info")
        self.assertEqual(events[0].duration_seconds, 254.0)
        self.assertEqual(events[0].duration_source, "wanna_queue_json")
        record = events[0].to_capture_record()
        self.assertEqual(record["dance_system_key"], WANNA_SYSTEM_KEY)
        self.assertEqual(record["dance_external_id"], "8385")
        self.assertEqual(record["video_name"], "Poker Face")

    def test_parses_wannadance_play_video_duration_metadata(self):
        events = parse_vrc_log_line(
            '2026.05.17 15:23:33 Debug - [VideoQueueManager] [15:23:33] : '
            'PlayRandomVideo: randomIndex = 2836, infoString = 2836. Random Song, '
            'userData = {"songId":2836,"isRandom":true,"playerName":"",'
            '"videoUrl":"http://api.udon.dance/Api/Songs/play?id=2836",'
            '"videoTitle":"2836. Random Song"}, videoDuration = 155'
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "metadata")
        self.assertEqual(events[0].parser_name, "wannadance_play_video")
        self.assertEqual(events[0].duration_seconds, 155.0)
        self.assertEqual(events[0].duration_source, "wanna_video_duration")
        self.assertEqual(events[0].source_hint, "random")
        self.assertIsNone(events[0].display_name)
        record = events[0].to_capture_record()
        self.assertEqual(record["dance_system_key"], WANNA_SYSTEM_KEY)
        self.assertEqual(record["dance_external_id"], "2836")

    def test_parses_wannadance_user_data_metadata(self):
        events = parse_vrc_log_line(
            '2026.05.17 19:50:28 Debug - [VideoQueueManager] [19:50:28] : '
            'DeserializeVideoUserData: userData = '
            '{"songId":8385,"isRandom":false,"playerName":"Alice",'
            '"videoUrl":"http://api.udon.dance/Api/Songs/play?id=8385",'
            '"videoTitle":"8385. Poker Face","duration":254}'
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "metadata")
        self.assertEqual(events[0].display_name, "Alice")
        self.assertEqual(events[0].duration_seconds, 254.0)

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
        self.assertEqual(events[0].duration_source, "vrcx_payload")
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

    def test_parses_room_and_application_lifecycle_events(self):
        entering = parse_vrc_lifecycle_event(
            "2026.05.17 15:30:00 Debug - [Behaviour] Entering Room: PyPyDance"
        )
        left = parse_vrc_lifecycle_event(
            "2026.05.17 15:30:05 Debug - [Behaviour] OnLeftRoom"
        )
        quit_event = parse_vrc_lifecycle_event(
            "2026.05.17 15:30:06 Debug - VRCApplication: HandleApplicationQuit at 313.2613"
        )

        self.assertEqual(entering["event_type"], "room-entering")
        self.assertEqual(entering["room_name"], "PyPyDance")
        self.assertFalse(entering["clear_current"])
        self.assertEqual(left["event_type"], "room-left")
        self.assertTrue(left["clear_current"])
        self.assertEqual(quit_event["event_type"], "application-quit")
        self.assertEqual(quit_event["message"], "VRChat ended")

    def test_ignores_unrelated_lines(self):
        self.assertEqual(parse_vrc_log_line("2026.05.17 15:30:05 Log - Joined room"), [])


class VrcLogWatcherTest(unittest.TestCase):
    def test_watcher_fails_when_log_directory_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with self.assertRaises(FileNotFoundError) as context:
                watch_vrc_logs(
                    log_dir=root / "missing-logs",
                    output_dir=root / "capture",
                    session_name="missing",
                    archive_source_logs=False,
                )

            self.assertIn("VRChat log directory is missing", str(context.exception))
            self.assertFalse((root / "capture").exists())

    def test_watcher_stops_when_stop_event_is_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            stop_event = threading.Event()
            stop_event.set()

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="stop-event",
                poll_seconds=0.01,
                stop_event=stop_event,
                archive_source_logs=False,
            )

            self.assertTrue(stats.stop_requested)
            summary = json.loads((stats.session_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["stop_requested"])

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

    def test_source_archive_copies_current_log_from_start_while_parser_tails_eof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            log_path = log_dir / "output_log_0001.txt"
            source_bytes = (
                "noise\n"
                "2026.05.17 15:30:00 Log - [Video Playback] "
                "Resolving URL 'https://api.udon.dance/Api/Songs/play?id=3114'\n"
            ).encode("utf-8")
            log_path.write_bytes(source_bytes)

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="archive-current",
                from_start=False,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            archived = root / "source-vrc-logs" / log_path.name
            self.assertEqual(stats.parsed_events, 0)
            self.assertEqual(archived.read_bytes(), source_bytes)
            self.assertEqual(stats.source_log_dir, str(root / "source-vrc-logs"))
            self.assertEqual(stats.source_log_bytes, len(source_bytes))
            self.assertEqual(stats.source_log_files[0]["archived_bytes"], len(source_bytes))
            self.assertTrue(stats.source_log_files[0]["complete"])

    def test_source_archive_resumes_from_archived_size_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            log_path = log_dir / "output_log_0001.txt"
            first_chunk = b"first line\n"
            second_chunk = b"second line\n"
            log_path.write_bytes(first_chunk)

            watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="archive-first",
                from_start=False,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            with log_path.open("ab") as handle:
                handle.write(second_chunk)

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="archive-second",
                from_start=False,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            archived = root / "source-vrc-logs" / log_path.name
            self.assertEqual(archived.read_bytes(), first_chunk + second_chunk)
            self.assertEqual(archived.read_bytes().count(first_chunk), 1)
            self.assertEqual(stats.source_log_bytes, len(second_chunk))

    def test_source_archive_preserves_binary_log_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            log_path = log_dir / "output_log_0001.txt"
            source_bytes = (
                b"prefix\x00\xff\r\n"
                b"2026.05.17 15:30:00 Log - [Video Playback] "
                b"Resolving URL 'https://api.udon.dance/Api/Songs/play?id=5038'\r\n"
            )
            log_path.write_bytes(source_bytes)

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="archive-binary",
                from_start=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            archived = root / "source-vrc-logs" / log_path.name
            self.assertEqual(archived.read_bytes(), source_bytes)
            self.assertEqual(stats.source_log_files[0]["source_size"], len(source_bytes))

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

    def test_watcher_merges_same_track_retry_after_delayed_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            db_path = root / "app.sqlite3"
            (log_dir / "output_log_0001.txt").write_text(
                "2026.05.17 15:30:00 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "PlayVideoInternal: Playing video http://api.udon.dance/Api/Songs/play?id=5437\n"
                "2026.05.17 15:30:00 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "Started video load for URL: http://api.udon.dance/Api/Songs/play?id=5437, "
                "requested by Alice\n"
                '2026.05.17 15:30:00 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"http://api.udon.dance/Api/Songs/play?node=cf&id=5437",0,114514,'
                '"$5437. Masayume Chasing - BoA | wani (Alice)"\n'
                "2026.05.17 15:30:05 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "DelayedVideoReady: Time's up, let's play\n"
                "2026.05.17 15:30:10 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "LoadRoutedURL: http://api.udon.dance/Api/Songs/play?id=5437 "
                "routed to http://api.udon.dance/Api/Songs/play?node=cf&id=5437\n"
                "2026.05.17 15:30:10 Debug - [Video Playback] "
                "Attempting to resolve URL 'http://api.udon.dance/Api/Songs/play?node=cf&id=5437'\n"
                "2026.05.17 15:30:12 Debug - [Video Playback] "
                "URL 'http://api.udon.dance/Api/Songs/play?node=cf&id=5437' resolved to "
                "'http://play.udon.dance/files/2407/5437-example.mp4'\n"
                "2026.05.17 15:30:12 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "OnVideoStart: Started video: http://api.udon.dance/Api/Songs/play?id=5437, "
                "since I'm the owner\n",
                encoding="utf-8",
            )

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="same-track-retry",
                app_db_path=db_path,
                from_start=True,
                live_db=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            playback = read_jsonl(stats.session_dir / "playback_events.jsonl")
            self.assertEqual(stats.playback_events, 1)
            self.assertEqual(playback[0]["event_key"], "wannadance:5437#1")
            self.assertEqual(playback[0]["video_name"], "Masayume Chasing - BoA | wani")
            self.assertEqual(playback[0]["actual_play_at"], "2026.05.17 15:30:12")
            self.assertEqual(playback[0]["on_video_start_at"], "2026.05.17 15:30:12")
            self.assertIn("video_playback_resolve", playback[0]["parser_names"])

            with connect_db(db_path) as conn:
                rows = conn.execute("SELECT * FROM live_playback_events").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["dance_external_id"], "5437")
            self.assertEqual(rows[0]["video_name"], "Masayume Chasing - BoA | wani")

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

    def test_watcher_records_wanna_playing_synced_without_mid_play(self):
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
            self.assertEqual(stats.delay_metrics["count"], 1)
            playback = read_jsonl(stats.session_dir / "playback_events.jsonl")
            self.assertFalse(playback[0]["observed_mid_play"])
            self.assertEqual(playback[0]["synced_play_at"], "2026.05.17 15:30:00")
            self.assertEqual(playback[0]["delay_to_actual_seconds"], 2.0)
            self.assertIn("playback-sync", playback[0]["raw_event_types"])

    def test_watcher_settles_live_wanna_synced_event_on_graceful_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            db_path = root / "app.sqlite3"
            (log_dir / "output_log_0001.txt").write_text(
                '2026.05.17 15:30:00 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"http://api.udon.dance/Api/Songs/play?id=3823",0,114514,'
                '"$3823. Synced Title (Alice)"\n'
                "2026.05.17 15:30:00 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "Playing synced http://api.udon.dance/Api/Songs/play?id=3823\n"
                "2026.05.17 15:30:02 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "OnVideoStart: Started video: http://api.udon.dance/Api/Songs/play?id=3823\n",
                encoding="utf-8",
            )

            watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="wanna-synced-live",
                app_db_path=db_path,
                from_start=True,
                live_db=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            with connect_db(db_path) as conn:
                live_row = conn.execute("SELECT * FROM live_playback_events").fetchone()
            self.assertEqual(live_row["dance_external_id"], "3823")
            self.assertEqual(live_row["video_name"], "Synced Title")
            self.assertEqual(live_row["actual_play_at"], "2026.05.17 15:30:02")
            self.assertEqual(live_row["completion_status"], "interrupted")
            self.assertEqual(live_row["completion_reason"], "watcher_stopped")
            self.assertEqual(live_row["observed_mid_play"], 0)

    def test_watcher_keeps_active_song_when_preview_overlaps_pending_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            db_path = root / "app.sqlite3"
            (log_dir / "output_log_0001.txt").write_text(
                '2026.05.18 00:22:48 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"http://api.udon.dance/Api/Songs/play?node=cf&id=5723",0,114514,'
                '"$5723. First Random (Random)"\n'
                "2026.05.18 00:22:48 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "Started video load for URL: http://api.udon.dance/Api/Songs/play?id=5723, "
                "requested by Alice\n"
                "2026.05.18 00:22:48 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "LoadRoutedURL: http://api.udon.dance/Api/Songs/play?id=5723 "
                "routed to http://api.udon.dance/Api/Songs/play?node=cf&id=5723\n"
                "2026.05.18 00:22:49 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "Video loaded (1.0 seconds), but let's wait for 9.0 seconds before playing it\n"
                '2026.05.18 00:22:51 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"http://api.udon.dance/Api/Songs/play?node=cf&id=8619",0,114514,'
                '"$8619. Actual Random (Random)"\n'
                "2026.05.18 00:22:51 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "Started video load for URL: http://api.udon.dance/Api/Songs/play?id=8619, "
                "requested by Alice\n"
                "2026.05.18 00:22:55 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "LoadRoutedURL: http://api.udon.dance/Api/Songs/play?id=8619 "
                "routed to http://api.udon.dance/Api/Songs/play?node=cf&id=8619\n"
                "2026.05.18 00:22:57 Debug - [Video Playback] "
                "URL 'http://api.udon.dance/Api/Songs/play?node=cf&id=8619' resolved to "
                "'http://play.udon.dance/files/2411/8619-example.mp4'\n"
                "2026.05.18 00:22:57 Debug - [VideoListManager] "
                "PreviewVideo: 3768 http://api.udon.dance/Api/Songs/play?id=3768, time 30 - 279\n"
                "2026.05.18 00:22:57 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "PlayVideoInternal: Playing video http://api.udon.dance/Api/Songs/play?id=3768\n"
                "2026.05.18 00:22:57 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "Started video load for URL: http://api.udon.dance/Api/Songs/play?id=3768, "
                "requested by Alice\n"
                "2026.05.18 00:22:57 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "LoadRoutedURL: http://api.udon.dance/Api/Songs/play?id=3768 "
                "routed to http://api.udon.dance/Api/Songs/play?node=cf&id=3768\n"
                "2026.05.18 00:22:58 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "Video loaded (6.0 seconds), but let's wait for 4.0 seconds before playing it\n"
                "2026.05.18 00:22:59 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "DelayedVideoReady: Time's up, let's play\n"
                "2026.05.18 00:22:59 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "OnVideoStart: Started video: http://api.udon.dance/Api/Songs/play?id=8619, "
                "since I'm the owner\n",
                encoding="utf-8",
            )

            watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="preview-overlap-pending",
                app_db_path=db_path,
                from_start=True,
                live_db=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            with connect_db(db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT playback_event_key, dance_external_id, actual_play_at,
                           completion_status, completion_reason
                    FROM live_playback_events
                    ORDER BY first_seen_at, id
                    """
                ).fetchall()

            by_id = {row["dance_external_id"]: row for row in rows}
            self.assertNotIn("3768", by_id)
            self.assertEqual(by_id["5723"]["completion_status"], "interrupted")
            self.assertEqual(by_id["5723"]["completion_reason"], "superseded_before_completion")
            self.assertEqual(by_id["8619"]["completion_status"], "interrupted")
            self.assertEqual(by_id["8619"]["completion_reason"], "watcher_stopped")
            self.assertEqual(by_id["8619"]["actual_play_at"], "2026.05.18 00:22:59")

    def test_replay_vrc_log_files_replays_multiple_logs_in_name_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            (log_dir / "output_log_0002.txt").write_text(
                "2026.05.17 15:31:00 Debug - [Video Playback] "
                "Resolving URL 'https://api.udon.dance/Api/Songs/play?id=5038'\n",
                encoding="utf-8",
            )
            (log_dir / "output_log_0001.txt").write_text(
                "2026.05.17 15:30:00 Debug - [Video Playback] "
                "Resolving URL 'https://api.udon.dance/Api/Songs/play?id=3114'\n",
                encoding="utf-8",
            )

            stats = replay_vrc_log_files(
                log_files=list(log_dir.glob("output_log_*.txt")),
                output_dir=root / "replay",
                live_db=False,
            )

            playback = read_jsonl(stats.session_dir / "playback_events.jsonl")
            self.assertEqual([event["dance_external_id"] for event in playback], ["3114", "5038"])
            self.assertEqual(len(stats.replayed_files), 2)

    def test_watcher_does_not_create_playback_from_wanna_metadata_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            db_path = root / "app.sqlite3"
            (log_dir / "output_log_0001.txt").write_text(
                '2026.05.17 19:46:33 Debug - [VideoQueueManager] [19:46:33] : '
                'OnPreSerialization: queue info serialized: '
                '[{"playerNames":["Alice"],"title":"8385. Poker Face","songId":8385,'
                '"duration":254,"group":"Just Dance Solo"}]\n',
                encoding="utf-8",
            )

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="metadata-only",
                app_db_path=db_path,
                from_start=True,
                live_db=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            self.assertEqual(stats.parsed_events, 1)
            self.assertEqual(stats.playback_events, 0)
            with connect_db(db_path) as conn:
                live_count = conn.execute("SELECT count(*) FROM live_playback_events").fetchone()[0]
            self.assertEqual(live_count, 0)

    def test_watcher_accepts_wanna_after_duration_from_log_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            db_path = root / "app.sqlite3"
            (log_dir / "output_log_0001.txt").write_text(
                '2026.05.17 15:29:58 Debug - [VideoQueueManager] [15:29:58] : '
                'OnPreSerialization: queue info serialized: '
                '[{"playerNames":["Alice"],"title":"3114. First Song","songId":3114,'
                '"duration":2}]\n'
                '2026.05.17 15:30:00 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"https://api.udon.dance/Api/Songs/play?id=3114",0,114514,'
                '"$3114. First Song (Alice)"\n'
                "2026.05.17 15:30:00 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "DelayedVideoReady: Time's up, let's play\n"
                '2026.05.17 15:30:03 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"https://api.udon.dance/Api/Songs/play?id=5038",0,114514,'
                '"$5038. Next Song (Bob)"\n',
                encoding="utf-8",
            )

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="wanna-duration-promote",
                app_db_path=db_path,
                from_start=True,
                record_playback=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            self.assertGreaterEqual(stats.playback_record_updates, 2)
            playback = read_jsonl(stats.session_dir / "playback_events.jsonl")
            first = next(event for event in playback if event["dance_external_id"] == "3114")
            self.assertEqual(first["duration_seconds"], 2.0)
            self.assertEqual(first["duration_source"], "wanna_queue_json")
            with connect_db(db_path) as conn:
                event_count = conn.execute("SELECT count(*) FROM dance_events").fetchone()[0]
                playback_count = conn.execute("SELECT count(*) FROM playback_records").fetchone()[0]
                live_count = conn.execute("SELECT count(*) FROM live_playback_events").fetchone()[0]
                accepted_row = conn.execute(
                    "SELECT * FROM playback_records WHERE dance_external_id = '3114'"
                ).fetchone()
                attention_row = conn.execute(
                    "SELECT * FROM playback_records WHERE dance_external_id = '5038'"
                ).fetchone()
            self.assertEqual(event_count, 0)
            self.assertEqual(playback_count, 2)
            self.assertEqual(live_count, 0)
            self.assertEqual(accepted_row["playback_status"], "accepted")
            self.assertEqual(accepted_row["counts_in_history"], 1)
            self.assertEqual(accepted_row["completion_status"], "completed")
            self.assertEqual(accepted_row["status_reason"], "observed_completion_threshold")
            self.assertEqual(attention_row["playback_status"], "needs_attention")
            self.assertEqual(attention_row["status_reason"], "watcher_stopped")

    def test_watcher_uses_wanna_play_video_duration_for_live_overlay_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            db_path = root / "app.sqlite3"
            (log_dir / "output_log_0001.txt").write_text(
                '2026.05.17 15:23:30 Debug - [VideoQueueManager] [15:23:30] : '
                'OnPreSerialization: queue info serialized: '
                '[{"playerNames":[],"title":"2836. Random Song","songId":2836,'
                '"duration":155,"isRandom":true}]\n'
                '2026.05.17 15:23:33 Debug - [VideoQueueManager] [15:23:33] : '
                'PlayRandomVideo: randomIndex = 2836, infoString = 2836. Random Song, '
                'userData = {"songId":2836,"isRandom":true,"playerName":"",'
                '"videoUrl":"http://api.udon.dance/Api/Songs/play?id=2836",'
                '"videoTitle":"2836. Random Song"}, videoDuration = 155\n'
                '2026.05.17 15:23:33 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"http://api.udon.dance/Api/Songs/play?node=cf&id=2836",0,114514,'
                '"$2836. Random Song (Random)"\n'
                "2026.05.17 15:23:35 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "DelayedVideoReady: Time's up, let's play\n",
                encoding="utf-8",
            )

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="wanna-video-duration-live",
                app_db_path=db_path,
                from_start=True,
                live_db=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            playback = read_jsonl(stats.session_dir / "playback_events.jsonl")
            event = next(event for event in playback if event["dance_external_id"] == "2836")
            self.assertEqual(event["duration_seconds"], 155.0)
            self.assertEqual(event["duration_source"], "wanna_video_duration")
            with connect_db(db_path) as conn:
                live_row = conn.execute(
                    "SELECT * FROM live_playback_events WHERE dance_external_id = '2836'"
                ).fetchone()
            self.assertEqual(live_row["actual_play_at"], "2026.05.17 15:23:35")
            self.assertEqual(live_row["duration_seconds"], 155.0)
            self.assertEqual(live_row["duration_source"], "wanna_video_duration")
            self.assertEqual(live_row["source_type"], "random")

    def test_watcher_accepts_wanna_before_late_manual_cut(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            db_path = root / "app.sqlite3"
            (log_dir / "output_log_0001.txt").write_text(
                '2026.05.17 15:29:58 Debug - [VideoQueueManager] [15:29:58] : '
                'OnPreSerialization: queue info serialized: '
                '[{"playerNames":["Alice"],"title":"3919. First Song","songId":3919,'
                '"duration":10}]\n'
                '2026.05.17 15:30:00 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"https://api.udon.dance/Api/Songs/play?id=3919",0,114514,'
                '"$3919. First Song (Alice)"\n'
                "2026.05.17 15:30:00 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "DelayedVideoReady: Time's up, let's play\n"
                "2026.05.17 15:30:09 Debug - "
                "[VideoQueueManager] [15:30:09] : ForciblyPlayNextVideo: "
                "I am ready, but video owner Alice is not, wait 5 seconds\n"
                '2026.05.17 15:30:09 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"https://api.udon.dance/Api/Songs/play?id=5038",0,114514,'
                '"$5038. Next Song (Bob)"\n',
                encoding="utf-8",
            )

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="wanna-late-manual-cut",
                app_db_path=db_path,
                from_start=True,
                record_playback=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            self.assertGreaterEqual(stats.playback_record_updates, 2)
            with connect_db(db_path) as conn:
                accepted_row = conn.execute(
                    "SELECT * FROM playback_records WHERE dance_external_id = '3919'"
                ).fetchone()
                event_count = conn.execute("SELECT count(*) FROM dance_events").fetchone()[0]
                playback_count = conn.execute("SELECT count(*) FROM playback_records").fetchone()[0]
                live_count = conn.execute("SELECT count(*) FROM live_playback_events").fetchone()[0]
            self.assertEqual(event_count, 0)
            self.assertEqual(playback_count, 2)
            self.assertEqual(live_count, 0)
            self.assertEqual(accepted_row["playback_status"], "accepted")
            self.assertEqual(accepted_row["completion_status"], "completed")
            self.assertEqual(accepted_row["completion_reason"], "observed_completion_threshold")

    def test_watcher_does_not_promote_wanna_room_leave_before_metadata_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            db_path = root / "app.sqlite3"
            (log_dir / "output_log_0001.txt").write_text(
                '2026.05.17 15:29:58 Debug - [VideoQueueManager] [15:29:58] : '
                'OnPreSerialization: queue info serialized: '
                '[{"playerNames":["Alice"],"title":"3114. First Song","songId":3114,'
                '"duration":10}]\n'
                '2026.05.17 15:30:00 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"https://api.udon.dance/Api/Songs/play?id=3114",0,114514,'
                '"$3114. First Song (Alice)"\n'
                "2026.05.17 15:30:00 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "DelayedVideoReady: Time's up, let's play\n"
                "2026.05.17 15:30:05 Debug - [Behaviour] OnLeftRoom\n",
                encoding="utf-8",
            )

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="wanna-duration-room-left",
                app_db_path=db_path,
                from_start=True,
                record_playback=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            with connect_db(db_path) as conn:
                event_count = conn.execute("SELECT count(*) FROM dance_events").fetchone()[0]
                playback_count = conn.execute("SELECT count(*) FROM playback_records").fetchone()[0]
                playback_row = conn.execute("SELECT * FROM playback_records").fetchone()
                live_count = conn.execute("SELECT count(*) FROM live_playback_events").fetchone()[0]
            self.assertEqual(event_count, 0)
            self.assertEqual(playback_count, 1)
            self.assertEqual(live_count, 0)
            self.assertEqual(playback_row["playback_status"], "needs_attention")
            self.assertEqual(playback_row["counts_in_history"], 0)
            self.assertEqual(playback_row["completion_status"], "interrupted")
            self.assertEqual(playback_row["completion_reason"], "room_left")

    def test_watcher_live_db_updates_without_playback_records_when_experimental_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            db_path = root / "app.sqlite3"
            (log_dir / "output_log_0001.txt").write_text(
                "2026.05.17 15:30:00 Debug - [Video Playback] "
                "Resolving URL 'https://api.udon.dance/Api/Songs/play?id=3114'\n"
                "2026.05.17 15:30:10 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "DelayedVideoReady: Time's up, let's play\n",
                encoding="utf-8",
            )

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="live-db",
                app_db_path=db_path,
                from_start=True,
                live_db=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            self.assertGreaterEqual(stats.live_db_updates, 2)
            self.assertEqual(stats.live_promotions, 0)
            self.assertTrue((stats.session_dir / "playback_events.jsonl").exists())
            with connect_db(db_path) as conn:
                live_count = conn.execute("SELECT count(*) FROM live_playback_events").fetchone()[0]
                event_count = conn.execute("SELECT count(*) FROM dance_events").fetchone()[0]
                playback_count = conn.execute("SELECT count(*) FROM playback_records").fetchone()[0]
                row = conn.execute("SELECT * FROM live_playback_events").fetchone()
            self.assertEqual(live_count, 1)
            self.assertEqual(event_count, 0)
            self.assertEqual(playback_count, 0)
            self.assertEqual(row["dance_external_id"], "3114")
            self.assertEqual(row["actual_play_at"], "2026.05.17 15:30:10")
            self.assertEqual(row["completion_status"], "interrupted")
            self.assertEqual(row["completion_reason"], "watcher_stopped")

    def test_watcher_marks_incomplete_graceful_stop_needs_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            db_path = root / "app.sqlite3"
            (log_dir / "output_log_0001.txt").write_text(
                '2026.05.17 15:30:00 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"https://api.udon.dance/Api/Songs/play?id=3114",0,10,'
                '"$3114. Long Song (Alice)"\n'
                "2026.05.17 15:30:00 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "DelayedVideoReady: Time's up, let's play\n"
                "2026.05.17 15:30:05 Log - Leaving before the dance is done\n",
                encoding="utf-8",
            )

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="early-stop-no-promote",
                app_db_path=db_path,
                from_start=True,
                record_playback=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            with connect_db(db_path) as conn:
                event_count = conn.execute("SELECT count(*) FROM dance_events").fetchone()[0]
                playback_count = conn.execute("SELECT count(*) FROM playback_records").fetchone()[0]
                playback_row = conn.execute("SELECT * FROM playback_records").fetchone()
                live_count = conn.execute("SELECT count(*) FROM live_playback_events").fetchone()[0]
            self.assertEqual(event_count, 0)
            self.assertEqual(playback_count, 1)
            self.assertEqual(live_count, 0)
            self.assertEqual(playback_row["playback_status"], "needs_attention")
            self.assertEqual(playback_row["completion_status"], "interrupted")
            self.assertEqual(playback_row["completion_reason"], "watcher_stopped")

    def test_watcher_starts_new_occurrence_after_room_left_for_same_song(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            db_path = root / "app.sqlite3"
            (log_dir / "output_log_0001.txt").write_text(
                '2026.05.17 15:30:00 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"http://api.udon.dance/Api/Songs/play?id=2838",0,114514,'
                '"$2838. CH4NGE - Giga & 可不 | あきら (Alice)"\n'
                "2026.05.17 15:30:05 Debug - [Behaviour] OnLeftRoom\n"
                "2026.05.17 15:30:06 Debug - [Behaviour] Entering Room: WannaDance\n"
                "2026.05.17 15:30:10 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "Started video load for URL: http://api.udon.dance/Api/Songs/play?id=2838, "
                "requested by Alice\n"
                '2026.05.17 15:30:10 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"http://api.udon.dance/Api/Songs/play?id=2838",0,114514,'
                '"$2838. CH4NGE - Giga & 可不 | あきら (Alice)"\n'
                "2026.05.17 15:30:12 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "OnVideoStart: Started video: http://api.udon.dance/Api/Songs/play?id=2838\n",
                encoding="utf-8",
            )

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="same-song-after-room-left",
                app_db_path=db_path,
                from_start=True,
                live_db=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            self.assertEqual(stats.lifecycle_events, 2)
            with connect_db(db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT playback_event_key, dance_external_id, actual_play_at,
                           completion_status, completion_reason
                    FROM live_playback_events
                    ORDER BY first_seen_at, id
                    """
                ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["playback_event_key"], "wannadance:2838#1")
            self.assertEqual(rows[0]["completion_status"], "interrupted")
            self.assertEqual(rows[0]["completion_reason"], "room_left")
            self.assertEqual(rows[1]["playback_event_key"], "wannadance:2838#2")
            self.assertEqual(rows[1]["completion_status"], "interrupted")
            self.assertEqual(rows[1]["completion_reason"], "watcher_stopped")
            self.assertEqual(rows[1]["actual_play_at"], "2026.05.17 15:30:12")

    def test_watcher_marks_cut_song_needs_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            db_path = root / "app.sqlite3"
            (log_dir / "output_log_0001.txt").write_text(
                '2026.05.17 15:30:00 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"https://api.udon.dance/Api/Songs/play?id=3114",0,10,'
                '"$3114. First Song (Alice)"\n'
                "2026.05.17 15:30:00 Debug - "
                "[<color=#9C6994>USharpVideo (WannaDance)</color>] "
                "DelayedVideoReady: Time's up, let's play\n"
                '2026.05.17 15:30:05 Debug - [VRCX] VideoPlay(PyPyDance) '
                '"https://api.udon.dance/Api/Songs/play?id=5038",0,10,'
                '"$5038. Next Song (Bob)"\n',
                encoding="utf-8",
            )

            stats = watch_vrc_logs(
                log_dir=log_dir,
                output_dir=root / "capture",
                session_name="cut-song-no-promote",
                app_db_path=db_path,
                from_start=True,
                record_playback=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            with connect_db(db_path) as conn:
                event_count = conn.execute("SELECT count(*) FROM dance_events").fetchone()[0]
                playback_count = conn.execute("SELECT count(*) FROM playback_records").fetchone()[0]
                rows = conn.execute(
                    """
                    SELECT dance_external_id, playback_status, counts_in_history,
                           completion_status, completion_reason
                    FROM playback_records
                    ORDER BY dance_external_id
                    """
                ).fetchall()
                live_count = conn.execute("SELECT count(*) FROM live_playback_events").fetchone()[0]
            self.assertEqual(event_count, 0)
            self.assertEqual(playback_count, 2)
            self.assertEqual(live_count, 0)
            by_id = {row["dance_external_id"]: row for row in rows}
            self.assertEqual(by_id["3114"]["playback_status"], "needs_attention")
            self.assertEqual(by_id["3114"]["counts_in_history"], 0)
            self.assertEqual(by_id["3114"]["completion_status"], "interrupted")
            self.assertEqual(by_id["3114"]["completion_reason"], "superseded_before_completion")
            self.assertEqual(by_id["5038"]["playback_status"], "needs_attention")
            self.assertEqual(by_id["5038"]["completion_status"], "interrupted")
            self.assertEqual(by_id["5038"]["completion_reason"], "watcher_stopped")

    def test_watcher_marks_mid_play_needs_attention_on_graceful_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            db_path = root / "app.sqlite3"
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
                session_name="mid-play-no-promote",
                app_db_path=db_path,
                from_start=True,
                record_playback=True,
                poll_seconds=0.01,
                stop_after_idle_seconds=0.05,
            )

            with connect_db(db_path) as conn:
                event_count = conn.execute("SELECT count(*) FROM dance_events").fetchone()[0]
                playback_count = conn.execute("SELECT count(*) FROM playback_records").fetchone()[0]
                playback_row = conn.execute("SELECT * FROM playback_records").fetchone()
                live_count = conn.execute("SELECT count(*) FROM live_playback_events").fetchone()[0]
            self.assertEqual(event_count, 0)
            self.assertEqual(playback_count, 1)
            self.assertEqual(live_count, 0)
            self.assertEqual(playback_row["playback_status"], "needs_attention")
            self.assertEqual(playback_row["counts_in_history"], 0)
            self.assertEqual(playback_row["completion_status"], "interrupted")
            self.assertEqual(playback_row["completion_reason"], "observed_mid_play")


if __name__ == "__main__":
    unittest.main()
