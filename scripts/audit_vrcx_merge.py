"""Read-only VRCX/log audit; private artifacts stay in a new workspace directory.

Capture uses the real replay entry point and observes the builder's return value
without changing parser, folding, settlement, or persistence behavior. Analyze
can be rerun on the frozen artifacts without reopening any external source.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_OUTPUT_ROOT = (ROOT / "analysis").resolve()
sys.path.insert(0, str(ROOT))

from dance_trail.live_playback_folding import PlaybackEventBuilder  # noqa: E402
from dance_trail.time_utils import parse_timestamp  # noqa: E402
from dance_trail.vrc_log_parser import parse_vrc_log_line  # noqa: E402
from dance_trail.vrcx_importer import parse_dance_url  # noqa: E402
from scripts.replay_vrc_logs import _run_replay  # noqa: E402

MARKER = re.compile(r"\[VRCX\]\s+VideoPlay\(([^)]+)\)\s*(.*)")
JOIN = re.compile(r"\[Behaviour\] Joining (wrld_\S+)")
STAMP = re.compile(r"^\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?")


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_line(handle, value):
    handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def read_lines(path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def fingerprint(path):
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest}


def readonly(path):
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    return conn


def audit_output(path):
    output = path.resolve()
    if not output.is_relative_to(PRIVATE_OUTPUT_ROOT) or output == PRIVATE_OUTPUT_ROOT:
        raise SystemExit("Audit output must be a new directory below the git-ignored analysis/ directory.")
    return output


def instant(value, offset):
    if not value:
        return None
    return parse_timestamp(value, local_tz=timezone(timedelta(hours=offset))).astimezone(timezone.utc).isoformat()


def dance(url):
    result = parse_dance_url(url)
    return f"{result.system_key}:{result.external_id}" if result.system_key and result.external_id else None


def scan_logs(files, output, offset):
    """Independently retain the unnormalized CSV URL and full instance context."""
    markers = []
    census = Counter()
    with (output / "markers.jsonl").open("w", encoding="utf-8") as destination, (output / "rooms.jsonl").open("w", encoding="utf-8") as rooms:
        for path in files:
            location = None
            room_line = None
            byte_offset = 0
            write_line(rooms, {"source_file": str(path), "line_number": 0, "location": None})
            with path.open("rb") as handle:
                for number, raw in enumerate(handle, 1):
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    joining = JOIN.search(line)
                    if joining:
                        location, room_line = joining[1], number
                        write_line(rooms, {"source_file": str(path), "line_number": number, "location": location, "raw_line": line})
                    # A stale preceding instance must not cross an explicit leave.
                    if "[Behaviour] OnLeftRoom" in line or "[Behaviour] OnApplicationQuit" in line:
                        location = None
                        room_line = None
                        write_line(rooms, {"source_file": str(path), "line_number": number, "location": None, "raw_line": line})
                    for tag in re.findall(r"\[VRCX\]\s+([^ (]+)", line):
                        census[tag] += 1
                    match = MARKER.search(line)
                    if match:
                        fields = next(csv.reader([match[2]], skipinitialspace=True))
                        timestamp = STAMP.match(line)
                        parsed = [e.to_capture_record(source_file=path, line_number=number, byte_offset=byte_offset)
                                  for e in parse_vrc_log_line(line) if e.parser_name == "vrcx_video_play"]
                        marker = {
                            "source_file": str(path), "line_number": number, "byte_offset": byte_offset,
                            "raw_line": line, "world_parser": match[1], "raw_payload": match[2],
                            "csv_fields": fields, "raw_url": fields[0] if fields else None,
                            "timestamp": timestamp[0] if timestamp else None,
                            "utc": instant(timestamp[0], offset) if timestamp else None,
                            "location": location, "joining_line": room_line, "parsed": parsed,
                        }
                        markers.append(marker)
                        write_line(destination, marker)
                    byte_offset += len(raw)
    dump(output / "raw_census.json", dict(census))
    return markers


def refresh_context(output):
    """Rescan only sources still equal to the capture's SHA-256 manifest."""
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    for name, dataset in manifest["datasets"].items():
        files = [Path(item["path"]) for item in dataset["before"]]
        if [fingerprint(p) for p in files] != dataset["before"]:
            raise SystemExit(f"Source changed since capture: {name}")
        scan_logs(files, output / name, manifest["utc_offset_hours"])
        if [fingerprint(p) for p in files] != dataset["before"]:
            raise SystemExit(f"Source changed during rescan: {name}")
        print(f"{name}: context refreshed; source hashes unchanged")


def capture(args):
    output = audit_output(args.output)
    # Never overwrite a source, existing audit, or trackable repository directory.
    sources = []
    for item in args.log_dir:
        name, path = item.split("=", 1)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or name in {n for n, _ in sources}:
            raise SystemExit("Use unique simple names in --log-dir NAME=PATH.")
        source = Path(path).resolve()
        if output == source or output.is_relative_to(source) or source.is_relative_to(output):
            raise SystemExit("Source and output directories must be disjoint.")
        sources.append((name, source))
    output.mkdir(parents=True, exist_ok=False)
    original = args.vrcx_db.resolve()
    before = fingerprint(original)
    snapshot = output / "VRCX.snapshot.sqlite3"
    # SQLite's online backup API supplies a consistent snapshot even if VRCX is running.
    # Only the destination is writable; the external connection is mode=ro/query_only.
    with closing(readonly(original)) as source, closing(sqlite3.connect(snapshot)) as destination:
        source.backup(destination)
    manifest = {
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "utc_offset_hours": args.utc_offset_hours,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "database_before": before, "database_after_snapshot": fingerprint(original),
        "snapshot": fingerprint(snapshot), "datasets": {},
    }
    dump(output / "manifest.json", manifest)
    for name, source in sources:
        dataset = output / name
        dataset.mkdir()
        files = sorted(source.glob("output_log_*.txt"), key=lambda p: p.name)
        if not files:
            raise SystemExit(f"No logs found in {source}")
        fingerprints = [fingerprint(p) for p in files]
        scan_logs(files, dataset, args.utc_offset_hours)
        original_observe = PlaybackEventBuilder.observe
        with (dataset / "consumption.jsonl").open("w", encoding="utf-8") as trace:
            def observe(builder, record):
                result = original_observe(builder, record)
                write_line(trace, {
                    "source_file": record.get("source_file"), "line_number": record.get("line_number"),
                    "byte_offset": record.get("byte_offset"), "timestamp": record.get("timestamp"),
                    "parser_name": record.get("parser_name"), "event_type": record.get("event_type"),
                    "video_url": record.get("video_url"),
                    "event_key": result.get("event_key") if result else None,
                })
                return result
            with patch.object(PlaybackEventBuilder, "observe", observe):
                stats = _run_replay(log_dir=source, pattern="output_log_*.txt", output=dataset)
        after = [fingerprint(p) for p in files]
        manifest["datasets"][name] = {
            "source": str(source), "before": fingerprints, "after": after,
            "unchanged": fingerprints == after,
            "raw_lines": stats.raw_lines, "parsed_events": stats.parsed_events,
            "playback_events": stats.playback_events,
        }
        dump(output / "manifest.json", manifest)
        print(json.dumps({"dataset": name, "playback_events": stats.playback_events,
                          "sources_unchanged": fingerprints == after}), flush=True)
    manifest["database_at_finish"] = fingerprint(original)
    dump(output / "manifest.json", manifest)


def comparison(pairs):
    counts = Counter()
    for left, right in pairs:
        if left in (None, "") and right in (None, ""):
            counts["both_missing"] += 1
        elif left in (None, "") or right in (None, ""):
            counts["one_missing"] += 1
        else:
            counts["equal" if left == right else "different"] += 1
    return dict(counts)


def upstream_pypy_fields(marker):
    """Reproduce v2026.07.18 mediaParsers.js, including its colon assumptions.

    This is an audit comparison, not a replacement for the product title parser.
    """
    match = re.search(r'VideoPlay\(PyPyDance\) "(.+?)",([\d.]+),([\d.]+),"(.*)"', marker["raw_line"])
    if not match:
        return None
    pieces = match[4].split("(")
    requester = pieces.pop()[:-1]
    prefix = "(".join(pieces)
    colon = prefix.find(":")
    if prefix == "Custom URL":
        return None  # The upstream YouTube enrichment branch is asynchronous.
    video_id = prefix[:max(0, colon - 1)]
    video_name = prefix[colon + 2:][:-1]
    return {"video_name": video_name, "video_id": video_id,
            "display_name": "" if requester == "Random" else requester}


def other_shared_inputs(dataset, rows, offset, known_ids):
    """Probe the upstream non-VideoPlay branches; these are diagnostic candidates.

    Generic video-play uses decodeURI and RPC-world gating upstream. Exact raw
    equality here is deliberately a subset, not an emulation of that state machine.
    """
    from bisect import bisect_right

    if not (dataset / "rooms.jsonl").exists():
        return {"context_missing": True}, []
    rooms = defaultdict(list)
    for room in read_lines(dataset / "rooms.jsonl"):
        rooms[room["source_file"]].append(room)
    room_numbers = {k: [r["line_number"] for r in v] for k, v in rooms.items()}
    index = {(r["utc"], r["video_url"], r["location"]): r for r in rows}
    trace = {(r["source_file"], r["line_number"], r["parser_name"]): r for r in read_lines(dataset / "consumption.jsonl")}
    patterns = (
        re.compile(r"\[Video Playback\] (?:Attempting to resolve URL|Resolving URL) '(.+)'$"),
        re.compile(r"\bUser .+ added URL (https?://\S+)$"),
        re.compile(r"\[USharpVideo\] Started video load for URL: (.+), requested by .+$"),
    )
    matches = []
    versions = defaultdict(set)
    for record in read_lines(dataset / "parsed_events.jsonl"):
        raw = record["raw_line"]
        if '"version"' in raw:
            match = re.search(r'"version"\s*:\s*"([^\"]+)"', raw)
            if match:
                t = trace.get((record["source_file"], record["line_number"], record["parser_name"]))
                if t and t["event_key"]:
                    versions[match[1]].add(t["event_key"])
        if record["parser_name"] == "vrcx_video_play":
            continue
        url = next((m[1] for p in patterns if (m := p.search(raw))), None)
        if not url:
            continue
        file = record["source_file"]
        position = bisect_right(room_numbers[file], record["line_number"]) - 1
        location = rooms[file][position]["location"]
        row = index.get((instant(record["timestamp"], offset), url, location))
        if row:
            t = trace.get((file, record["line_number"], record["parser_name"]))
            matches.append({"row_id": row["id"], "event_key": t["event_key"] if t else None,
                            "source_file": file, "line_number": record["line_number"],
                            "parser_name": record["parser_name"], "dance": row["dance"],
                            "already_has_vrcx_marker": row["id"] in known_ids})
    extras = [m for m in matches if not m["already_has_vrcx_marker"]]
    return {
        "exact_rows": len({m["row_id"] for m in matches}),
        "extra_rows_without_vrcx_marker": len({m["row_id"] for m in extras}),
        "extra_supported_rows": len({m["row_id"] for m in extras if m["dance"]}),
        "extra_rows_with_consuming_event": len({m["row_id"] for m in extras if m["event_key"]}),
        "by_parser": dict(Counter(m["parser_name"] for m in extras)),
        "metadata_version_values": len(versions),
        "metadata_versions_reused_across_events": sum(len(v) > 1 for v in versions.values()),
        "max_events_per_metadata_version": max((len(v) for v in versions.values()), default=0),
    }, matches


def analyze(output):
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    offset = manifest["utc_offset_hours"]
    with closing(readonly(output / "VRCX.snapshot.sqlite3")) as conn:
        rows = [dict(r) for r in conn.execute("SELECT rowid AS sqlite_rowid, * FROM gamelog_video_play ORDER BY id")]
        schema = [dict(r) for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")]
        config = [dict(r) for r in conn.execute("SELECT * FROM configs WHERE key IN ('config:vrcx_databaseversion', 'config:vrcx_lastvrcxversion')")]
        pragmas = {k: conn.execute(f"PRAGMA {k}").fetchone()[0] for k in ("user_version", "application_id", "integrity_check")}
        context_tables = {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                          for name in ("gamelog_location", "gamelog_join_leave", "gamelog_event", "gamelog_resource_load", "gamelog_external")}
    dump(output / "schema.json", schema)
    dump(output / "vrcx_rows.json", rows)
    by_anchor = defaultdict(list)
    by_dance_time = defaultdict(list)
    by_dance_location = defaultdict(list)
    for row in rows:
        row["utc"] = instant(row["created_at"], offset)
        row["dance"] = dance(row["video_url"])
        by_anchor[row["utc"], row["video_url"]].append(row)
        if row["dance"]:
            by_dance_time[row["dance"], row["utc"]].append(row)
            by_dance_location[row["dance"], row["location"]].append(row)
    gaps = []
    for group in by_dance_location.values():
        group.sort(key=lambda r: r["utc"])
        gaps.extend((datetime.fromisoformat(b["utc"]) - datetime.fromisoformat(a["utc"])).total_seconds()
                    for a, b in zip(group, group[1:]))
    report = {"git_head": manifest["git_head"], "database": {
        "rows": len(rows), "id_min": min(r["id"] for r in rows), "id_max": max(r["id"] for r in rows),
        "id_equals_rowid": sum(r["id"] == r["sqlite_rowid"] for r in rows),
        "created_at_min": min(r["created_at"] for r in rows), "created_at_max": max(r["created_at"] for r in rows),
        "milliseconds_zero": sum(r["created_at"].endswith(".000Z") for r in rows),
        "missing": {k: sum(r[k] in (None, "") for r in rows) for k in ("created_at", "video_url", "video_name", "video_id", "location", "display_name", "user_id")},
        "hosts": dict(Counter(urlsplit(r["video_url"]).netloc for r in rows).most_common()),
        "dance_systems": dict(Counter((r["dance"] or "unsupported").split(":")[0] for r in rows)),
        "duplicate_anchor_keys": sum(len(v) > 1 for v in by_anchor.values()),
        "duplicate_dance_time_keys": sum(len(v) > 1 for v in by_dance_time.values()),
        "same_created_at_groups": sum(n > 1 for n in Counter(r["created_at"] for r in rows).values()),
        "same_created_at_extra_rows": sum(n - 1 for n in Counter(r["created_at"] for r in rows).values() if n > 1),
        "adjacent_min_seconds": min(gaps), "adjacent_within_seconds": {w: sum(g <= w for g in gaps) for w in (5, 10, 20, 30, 60, 90)},
        "config": config, "pragmas": pragmas, "context_tables": context_tables,
    }, "datasets": {}}
    for name in manifest["datasets"]:
        dataset = output / name
        markers = read_lines(dataset / "markers.jsonl")
        events = read_lines(dataset / "playback_events.jsonl")
        trace = read_lines(dataset / "consumption.jsonl")
        if len(trace) != manifest["datasets"][name]["parsed_events"]:
            raise SystemExit(f"Incomplete consumption trace: {name}")
        marker_records = {(r["source_file"], r["line_number"]): r
                          for r in read_lines(dataset / "parsed_events.jsonl") if r["parser_name"] == "vrcx_video_play"}
        event_by_key = {e["event_key"]: e for e in events}
        by_position = {(m["source_file"], m["line_number"]): m for m in markers}
        direct = defaultdict(list)
        for item in trace:
            if item["parser_name"] == "vrcx_video_play" and item["event_key"]:
                marker = by_position[item["source_file"], item["line_number"]]
                if marker not in direct[item["event_key"]]:
                    direct[item["event_key"]].append(marker)
        exact = []
        for marker in markers:
            marker["rows"] = by_anchor.get((marker["utc"], marker["raw_url"]), [])
            if len(marker["rows"]) == 1:
                exact.append((marker, marker["rows"][0]))
        marker_by_dance_time = defaultdict(list)
        for marker in markers:
            if dance(marker["raw_url"]):
                marker_by_dance_time[dance(marker["raw_url"]), marker["utc"]].append(marker)
        # Reproduce the document's indirect lookup independently of the consumed trace.
        proxy = {}
        proxy_multi = []
        for event in events:
            key = dance(event.get("routed_url") or event.get("video_url"))
            key = f"{event['dance_system_key']}:{event['dance_external_id']}" if event.get("dance_system_key") and event.get("dance_external_id") else key
            found = {}
            for field in ("request_at", "first_seen_at"):
                for marker in marker_by_dance_time.get((key, instant(event.get(field), offset)), []):
                    for row in marker["rows"]:
                        found[row["id"]] = (marker, row)
            if len(found) == 1:
                proxy[event["event_key"]] = next(iter(found.values()))
            elif found:
                proxy_multi.append({"event_key": event["event_key"], "row_ids": list(found)})
        direct_matches = {}
        for key, group in direct.items():
            direct_matches[key] = [(m, r) for m in group for r in m["rows"] if m["location"] == r["location"]]
        supported_keys = {e["event_key"] for e in events if e.get("dance_system_key") and e.get("dance_external_id")}
        unique_direct = {key: pairs[0] for key, pairs in direct_matches.items() if len(pairs) == 1 and key in supported_keys}
        multi_direct = {key: pairs for key, pairs in direct_matches.items() if len(pairs) > 1 and key in supported_keys}
        contention = defaultdict(list)
        for key, pairs in direct_matches.items():
            for _, row in pairs:
                contention[row["id"]].append(key)
        with closing(readonly(dataset / "live.sqlite3")) as conn:
            persisted = [dict(r) for r in conn.execute("SELECT * FROM playback_records")]
            origin_rows = [dict(r) for r in conn.execute("SELECT pr.*, o.origin_json FROM playback_records pr JOIN playback_record_origins o ON o.playback_record_id=pr.id")]
        persisted_by_event = {json.loads(r["origin_json"])["watcher_playback_event"]["event_key"]: r for r in origin_rows}
        origin_event_by_key = {key: json.loads(r["origin_json"])["watcher_playback_event"] for key, r in persisted_by_event.items()}
        windows = []
        nearest_wrong = []
        for basis, window in ((b, w) for b in ("persisted", "summary") for w in (10, 20, 30, 90)):
            counts = Counter()
            for key, (marker, row) in proxy.items():
                event = event_by_key[key]
                played = instant(persisted_by_event.get(key, {}).get("played_at") if basis == "persisted"
                                 else event.get("actual_play_at") or event.get("first_seen_at"), offset)
                if not played:
                    continue
                candidates = [(r, (datetime.fromisoformat(played) - datetime.fromisoformat(r["utc"])).total_seconds())
                              for r in by_dance_location[row["dance"], row["location"]]]
                candidates = [(r, gap) for r, gap in candidates if 0 <= gap <= window]
                counts["truth"] += 1
                truth_in_window = any(r["id"] == row["id"] for r, _ in candidates)
                if truth_in_window:
                    counts["truth_in_window"] += 1
                if len(candidates) == 1:
                    counts["unique"] += 1
                    if truth_in_window:
                        counts["unique_when_truth_in_window"] += 1
                if len(candidates) > 1:
                    counts["multiple"] += 1
                if candidates:
                    nearest, gap = min(candidates, key=lambda pair: pair[1])
                    if nearest["id"] == row["id"]:
                        counts["nearest_correct"] += 1
                    else:
                        counts["nearest_wrong"] += 1
                        if len(candidates) == 1:
                            counts["unique_wrong"] += 1
                        nearest_wrong.append({"basis": basis, "window": window, "event_key": key, "truth_id": row["id"],
                                              "chosen_id": nearest["id"], "played_utc": played,
                                              "marker_file": marker["source_file"], "marker_line": marker["line_number"]})
            windows.append({"basis": basis, "window": window, **counts})
        proxy_trace_errors = [{"event_key": k, "row_id": r["id"], "marker": [m["source_file"], m["line_number"]]}
                              for k, (m, r) in proxy.items() if m not in direct.get(k, [])]
        proxy_ids = {r["id"] for _, r in proxy.values()}
        exact_unmatched = [{"row_id": r["id"], "source_file": m["source_file"], "line_number": m["line_number"],
                            "dance": r["dance"], "timestamp": m["timestamp"]} for m, r in exact if r["id"] not in proxy_ids]
        extra = [{"event_key": k, "row_id": r["id"], "source_file": m["source_file"], "line_number": m["line_number"]}
                 for k, (m, r) in unique_direct.items() if r["id"] not in proxy_ids]
        detail = {
            "proxy_not_consumed": proxy_trace_errors, "proxy_multi": proxy_multi,
            "multiple_consumed_anchors": {k: [{"row_id": r["id"], "source_file": m["source_file"],
                                                "line_number": m["line_number"], "timestamp": m["timestamp"]}
                                               for m, r in pairs] for k, pairs in multi_direct.items()},
            "extra_direct_matches": extra, "unmatched_by_proxy": exact_unmatched,
            "nearest_wrong": nearest_wrong,
            "row_contention": {k: v for k, v in contention.items() if len(set(v)) > 1},
        }
        other_stats, other_details = other_shared_inputs(dataset, rows, offset, {r["id"] for _, r in exact})
        detail["other_shared_inputs"] = other_details
        all_rows_by_event = defaultdict(set)
        for key, pairs in direct_matches.items():
            for _, row in pairs:
                all_rows_by_event[key].add(row["id"])
        for item in other_details:
            if item["event_key"]:
                all_rows_by_event[item["event_key"]].add(item["row_id"])
        all_events_by_row = defaultdict(set)
        for key, ids in all_rows_by_event.items():
            for row_id in ids:
                all_events_by_row[row_id].add(key)
        eligible = {key: next(iter(ids)) for key, ids in all_rows_by_event.items()
                    if key in supported_keys and len(ids) == 1 and len(all_events_by_row[next(iter(ids))]) == 1}
        detail["all_shared_input_multiple_rows"] = {k: sorted(ids) for k, ids in all_rows_by_event.items() if len(ids) > 1 and k in supported_keys}
        other_stats["all_shared_input_unique_supported_events"] = len(eligible)
        other_stats["all_shared_input_multiple_supported_events"] = len(detail["all_shared_input_multiple_rows"])
        other_stats["all_shared_input_row_contention"] = sum(len(v) > 1 for v in all_events_by_row.values())
        other_stats["extra_unique_supported_events"] = sum(k not in direct_matches or not direct_matches[k] for k in eligible)
        dump(dataset / "diagnostics.json", detail)
        dataset_report = {
            "files": len(manifest["datasets"][name]["before"]),
            "bytes": sum(f["bytes"] for f in manifest["datasets"][name]["before"]),
            "marker_files": len({m["source_file"] for m in markers}), "markers": len(markers),
            "exact_log_db": len(exact), "log_only": len(markers) - len(exact),
            "vrcx_in_marker_range": sum(min(m["utc"] for m in markers) <= r["utc"] <= max(m["utc"] for m in markers) for r in rows),
            "location_equal": sum(m["location"] == r["location"] for m, r in exact),
            "raw_title": comparison((m["csv_fields"][3] if len(m["csv_fields"]) > 3 else None, r["video_name"]) for m, r in exact),
            "parsed_title": comparison((m["parsed"][0].get("video_name") if m["parsed"] else None, r["video_name"]) for m, r in exact),
            "parsed_video_id": comparison((m["parsed"][0].get("video_id") if m["parsed"] else None, r["video_id"]) for m, r in exact),
            "parsed_requester": comparison((m["parsed"][0].get("display_name") if m["parsed"] else None, r["display_name"]) for m, r in exact),
            "marker_enriched_requester_id": comparison((marker_records.get((m["source_file"], m["line_number"]), {}).get("requester_user_id"), r["user_id"]) for m, r in exact),
            "upstream_pypy_title": comparison((p["video_name"], r["video_name"]) for m, r in exact if (p := upstream_pypy_fields(m)) is not None),
            "upstream_pypy_video_id": comparison((p["video_id"], r["video_id"]) for m, r in exact if (p := upstream_pypy_fields(m)) is not None),
            "raw_url_preserved_by_parser": sum(len(m["parsed"]) == 1 and m["parsed"][0]["video_url"] == m["raw_url"] for m in markers),
            "world_parsers": dict(Counter(m["world_parser"] for m in markers)),
            "marker_positive_position": sum(len(m["csv_fields"]) > 1 and float(m["csv_fields"][1]) > 0 for m, _ in exact),
            "raw_lines": manifest["datasets"][name]["raw_lines"], "parsed_events": manifest["datasets"][name]["parsed_events"],
            "playback_events": len(events), "persisted": len(persisted),
            "persisted_status": dict(Counter(f"{r['default_acceptance_status']}/{r['observation_status']}" for r in persisted)),
            "proxy_unique": len(proxy), "proxy_distinct_rows": len(proxy_ids), "proxy_multi": len(proxy_multi),
            "proxy_not_consumed": len(proxy_trace_errors),
            "proxy_routed_url_equal": sum(event_by_key[k].get("routed_url") == r["video_url"] for k, (_, r) in proxy.items()),
            "proxy_video_url_equal": sum(event_by_key[k].get("video_url") == r["video_url"] for k, (_, r) in proxy.items()),
            "proxy_origin_routed_url_equal": sum(origin_event_by_key.get(k, {}).get("routed_url") == r["video_url"] for k, (_, r) in proxy.items()),
            "proxy_origin_video_url_equal": sum(origin_event_by_key.get(k, {}).get("video_url") == r["video_url"] for k, (_, r) in proxy.items()),
            "proxy_requester_name": comparison((event_by_key[k].get("source_display_name") or event_by_key[k].get("display_name"), r["display_name"]) for k, (_, r) in proxy.items()),
            "proxy_raw_display_name": comparison((event_by_key[k].get("display_name"), r["display_name"]) for k, (_, r) in proxy.items()),
            "proxy_persisted_requester_name": comparison((persisted_by_event.get(k, {}).get("requester_display_name"), r["display_name"]) for k, (_, r) in proxy.items()),
            "proxy_requester_id": comparison((event_by_key[k].get("requester_user_id"), r["user_id"]) for k, (_, r) in proxy.items()),
            "proxy_stale_source_file": sum(event_by_key[k].get("source_file") != m["source_file"] for k, (m, _) in proxy.items()),
            "direct_unique_supported_events": len(unique_direct),
            "direct_multiple_supported_events": len(multi_direct),
            "direct_covered_supported_rows": len({r["id"] for k, pairs in direct_matches.items() if k in supported_keys for _, r in pairs}),
            "extra_direct_unique_rows": len(extra),
            "direct_marker_count_distribution": dict(Counter(len(group) for k, group in direct.items() if k in supported_keys)),
            "other_shared_inputs": other_stats,
            "windows": windows,
        }
        report["datasets"][name] = dataset_report
    dump(output / "report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--vrcx-db", type=Path, required=True)
    cap.add_argument("--log-dir", action="append", required=True, metavar="NAME=PATH")
    cap.add_argument("--output", type=Path, required=True)
    cap.add_argument("--utc-offset-hours", type=float, required=True)
    analyze_parser = sub.add_parser("analyze")
    analyze_parser.add_argument("--output", type=Path, required=True)
    context_parser = sub.add_parser("refresh-context")
    context_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = audit_output(args.output)
    if args.command == "capture":
        capture(args)
    elif args.command == "refresh-context":
        refresh_context(args.output.resolve())
    else:
        analyze(args.output.resolve())


if __name__ == "__main__":
    main()
