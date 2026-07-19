"""
爬取 https://wanna.kiva.moe/ 上的全部歌曲信息
数据来源: https://x.kiva.moe/api/v2/wanna/songs

输出字段: 歌名, 歌手, 舞者/系列名, id, 人数, 分组(group), 大类(major)
"""

import csv
import json
import subprocess
import sys
from pathlib import Path

API_URL = "https://x.kiva.moe/api/v2/wanna/songs"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_JSON = DATA_DIR / "wanna_songs.json"
OUTPUT_CSV = DATA_DIR / "wanna_songs.csv"


def fetch_data() -> dict:
    """通过 curl 拉取 API 数据（绕过 Python SSL 兼容性问题）"""
    result = subprocess.run(
        ["curl", "-s", API_URL, "--max-time", "60"],
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        print(f"curl 失败: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def extract_songs(data: dict) -> list[dict]:
    """从 API 响应中提取歌曲列表"""
    groups = data.get("data", {}).get("groups", [])
    songs = []
    seen_ids = set()

    for group in groups:
        group_title = group.get("title", "")
        major = group.get("major", "")

        for entry in group.get("entries", []):
            song_id = entry.get("id")
            # 跳过隐藏分组和重复 id
            if entry.get("disablePublic"):
                continue
            if song_id in seen_ids:
                continue
            seen_ids.add(song_id)

            songs.append({
                "id": song_id,
                "name": entry.get("name", ""),
                "artist": entry.get("artist", ""),
                "dancer": entry.get("dancer", ""),
                "playerCount": entry.get("playerCount", 0),
                "group": group_title,
                "major": major,
            })

    songs.sort(key=lambda s: s["id"])
    return songs


def save_json(songs: list[dict], path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(songs, f, ensure_ascii=False, indent=2)


def save_csv(songs: list[dict], path: Path):
    fieldnames = ["id", "name", "artist", "dancer", "playerCount", "group", "major"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(songs)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"正在从 {API_URL} 获取数据...")
    data = fetch_data()

    print("正在提取歌曲信息...")
    songs = extract_songs(data)

    print(f"共提取 {len(songs)} 首歌曲（已去重，已排除隐藏曲目）")

    save_json(songs, OUTPUT_JSON)
    print(f"已保存 JSON: {OUTPUT_JSON}")

    save_csv(songs, OUTPUT_CSV)
    print(f"已保存 CSV:  {OUTPUT_CSV}")

    # 打印示例
    print("\n--- 示例数据 (前10条) ---")
    for s in songs[:10]:
        print(f"{s['name']} - {s['artist']} | {s['dancer']}")
        print(f"  id: {s['id']}  人数：{s['playerCount']}  分组: [{s['major']}] {s['group']}")

    # 统计
    print("\n--- 统计 ---")
    groups = {}
    for s in songs:
        key = s["major"] or s["group"]
        groups[key] = groups.get(key, 0) + 1
    for k, v in sorted(groups.items(), key=lambda x: -x[1])[:10]:
        print(f"  {k}: {v} 首")


if __name__ == "__main__":
    main()
