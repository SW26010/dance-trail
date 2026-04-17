"""dancing-log: 舞蹈歌曲记录与数据分析工具"""

import subprocess
import sys


def main():
    commands = {
        "scrape": ("scripts/scrape_wanna.py", "爬取 Wanna Dance 歌曲数据库"),
        "match": ("scripts/match_netease.py", "批量查询网易云音乐热度"),
        "test-apis": ("scripts/test_music_apis.py", "测试各音乐平台 API"),
    }

    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print("dancing-log - 舞蹈歌曲记录与数据分析工具\n")
        print("用法: uv run python main.py <command> [args...]\n")
        print("命令:")
        for name, (_, desc) in commands.items():
            print(f"  {name:<12} {desc}")
        print("\n示例:")
        print("  uv run python main.py scrape")
        print("  uv run python main.py match --limit 100")
        print("  uv run python main.py match --resume")
        sys.exit(0)

    cmd = sys.argv[1]
    script, _ = commands[cmd]
    subprocess.run([sys.executable, script] + sys.argv[2:])


if __name__ == "__main__":
    main()
