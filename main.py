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
    source_group.add_argument("--source", type=str, choices=["self", "recommend", "other"],
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
