"""dancing-log: 舞蹈歌曲记录与数据分析工具"""

import subprocess
import sys


def cmd_recommend():
    """生成每日推荐歌单"""
    import argparse
    parser = argparse.ArgumentParser(description="生成每日推荐歌单")
    parser.add_argument("-n", "--count", type=int, default=20, help="推荐数量 (默认 20)")
    args = parser.parse_args(sys.argv[2:])

    from dancing_log.models import load_songs, load_dance_log, generate_daily_playlist

    songs = load_songs()
    if not songs:
        print("错误: 歌曲数据为空，请先运行 `uv run python main.py init`")
        sys.exit(1)

    dance_log = load_dance_log()
    playlist = generate_daily_playlist(songs, dance_log, count=args.count)

    print(f"每日推荐歌单 (Top {args.count}):\n")
    for i, s in enumerate(playlist, 1):
        fav = "❤" if s.get("favorite") in ("1", "true", True) else " "
        want = "📝" if s.get("want_to_learn") in ("1", "true", True) else " "
        pop = s.get("popularity", "")
        pop_str = f"pop={pop}" if pop else ""
        count = s.get("_dance_count", 0)
        days = s.get("_days_since_last")
        days_str = f"{days}d前" if days is not None else "从未"

        print(
            f"  {i:>3}. [{s['id']:>5}] {fav}{want} {s['name']} - {s['artist']}"
            f"  w={s['_weight']:.1f}  {pop_str}  跳过{count}次  {days_str}"
        )


def cmd_log():
    """添加舞蹈记录"""
    import argparse
    parser = argparse.ArgumentParser(description="添加舞蹈记录")
    parser.add_argument("song_id", type=int, help="歌曲 ID")
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--other", action="store_true", help="别人点的")
    source_group.add_argument(
        "--source",
        type=str,
        choices=["queued_self", "recommend", "self", "other", "random", "unknown"],
                              default=None, help="点歌来源 (默认自动判断)")
    parser.add_argument("--time", type=str, default=None, help="时间 (ISO 8601, 默认当前)")
    parser.add_argument("--note", type=str, default="", help="备注")
    args = parser.parse_args(sys.argv[2:])

    from dancing_log.models import (
        add_dance_record, load_songs, SOURCE_SELF, SOURCE_OTHER, SOURCE_LABELS,
    )

    songs = load_songs()
    song = next((s for s in songs if str(s.get("id")) == str(args.song_id)), None)
    if song:
        print(f"记录: {song['name']} - {song['artist']}")
    else:
        print(f"警告: ID {args.song_id} 不在歌曲库中，仍然记录")

    if args.other:
        source = SOURCE_OTHER
        auto_detect = False
    elif args.source:
        source = args.source
        auto_detect = False
    else:
        source = SOURCE_SELF
        auto_detect = True

    actual_source = add_dance_record(
        song_id=args.song_id,
        source=source,
        note=args.note,
        timestamp=args.time,
        auto_detect=auto_detect,
    )
    print(f"已添加舞蹈记录 (id={args.song_id}, {SOURCE_LABELS.get(actual_source, actual_source)})")


def cmd_import_vrcx():
    """从 VRCX SQLite 导入历史播放事件"""
    import argparse

    parser = argparse.ArgumentParser(description="从 VRCX SQLite 导入历史播放事件")
    parser.add_argument("vrcx_db", help="VRCX.sqlite3 路径，建议使用复制后的快照")
    parser.add_argument("--app-db", default=None, help="输出 SQLite 路径，默认 data/dancing_log.sqlite3")
    parser.add_argument("--self-user-id", default=None, help="自己的 VRChat user_id，用于推断 self/other")
    parser.add_argument("--limit", type=int, default=None, help="最多导入多少条候选事件")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写入本地数据库")
    args = parser.parse_args(sys.argv[2:])

    from dancing_log.vrcx_importer import import_vrcx_database

    stats = import_vrcx_database(
        vrcx_db_path=args.vrcx_db,
        app_db_path=args.app_db,
        self_user_id=args.self_user_id,
        limit=args.limit,
        dry_run=args.dry_run,
    )

    print("VRCX 导入完成" if not args.dry_run else "VRCX 导入预检查完成")
    print(f"  扫描候选行: {stats.scanned}")
    print(f"  候选播放事件: {stats.candidate_events}")
    print(f"  跳过无 song id: {stats.skipped_without_song_id}")
    if not args.dry_run:
        print(f"  staging 写入/更新: {stats.staging_changed}")
        print(f"  dance_events 写入/更新: {stats.dance_events_changed}")


def cmd_sample_recording_frames():
    """从录像抽取顶部区域帧，用于 OCR/人工校验 overlay"""
    import argparse

    parser = argparse.ArgumentParser(description="从录像抽取顶部区域帧")
    parser.add_argument("recording", help="录像文件路径")
    parser.add_argument("--output-dir", default="analysis/recording_frames", help="输出目录")
    parser.add_argument(
        "--at",
        nargs="+",
        type=float,
        default=[60.0, 300.0, 600.0],
        help="抽帧时间点，单位秒，可传多个",
    )
    parser.add_argument("--top-ratio", type=float, default=0.22, help="保留顶部高度比例")
    parser.add_argument("--width", type=int, default=1920, help="输出宽度，默认 1920")
    args = parser.parse_args(sys.argv[2:])

    from dancing_log.recordings import sample_top_frames

    outputs = sample_top_frames(
        recording_path=args.recording,
        output_dir=args.output_dir,
        timestamps=args.at,
        top_ratio=args.top_ratio,
        width=args.width,
    )

    print("已抽取顶部帧:")
    for path in outputs:
        print(f"  {path}")


def main():
    script_commands = {
        "scrape": ("scripts/scrape_wanna.py", "爬取 Wanna Dance 歌曲数据库"),
        "match": ("scripts/match_netease.py", "批量查询网易云音乐热度"),
        "init": ("scripts/init_songs.py", "从爬取数据初始化 songs.csv"),
        "test-apis": ("scripts/test_music_apis.py", "测试各音乐平台 API"),
    }
    builtin_commands = {
        "recommend": ("生成每日推荐歌单", cmd_recommend),
        "log": ("添加舞蹈记录", cmd_log),
        "import-vrcx": ("从 VRCX SQLite 导入历史播放事件", cmd_import_vrcx),
        "sample-frames": ("从录像抽取顶部区域帧", cmd_sample_recording_frames),
    }

    all_names = list(script_commands) + list(builtin_commands)

    if len(sys.argv) < 2 or sys.argv[1] not in all_names:
        print("dancing-log - 舞蹈歌曲记录与数据分析工具\n")
        print("用法: uv run python main.py <command> [args...]\n")
        print("数据采集:")
        for name, (_, desc) in script_commands.items():
            print(f"  {name:<12} {desc}")
        print("\n日常使用:")
        for name, (desc, _) in builtin_commands.items():
            print(f"  {name:<12} {desc}")
        print("\n示例:")
        print("  uv run python main.py scrape              # 更新歌曲库")
        print("  uv run python main.py init                # 初始化主数据")
        print("  uv run python main.py log 5038            # 记录跳了 id=5038")
        print("  uv run python main.py log 5038 --other     # 别人点的")
        print("  uv run python main.py recommend           # 生成推荐歌单")
        print("  uv run python main.py recommend -n 10     # 推荐10首")
        print("  uv run python main.py import-vrcx path/to/vrcx-snapshot/VRCX.sqlite3")
        print("  uv run python main.py sample-frames path/to/recordings/example.mkv --at 60 300")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd in script_commands:
        script, _ = script_commands[cmd]
        subprocess.run([sys.executable, script] + sys.argv[2:])
    elif cmd in builtin_commands:
        _, func = builtin_commands[cmd]
        func()


if __name__ == "__main__":
    main()
