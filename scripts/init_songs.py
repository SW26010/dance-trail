"""
从 wanna_songs.json 和 wanna_netease_matched.json 初始化 songs.csv

用法:
    uv run python scripts/init_songs.py
"""

import csv
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WANNA_FILE = DATA_DIR / "wanna_songs.json"
NETEASE_FILE = DATA_DIR / "wanna_netease_matched.json"
OUTPUT_FILE = DATA_DIR / "songs.csv"

FIELDS = [
    "id", "name", "artist", "dancer", "player_count",
    "group", "major", "favorite", "want_to_learn",
    "netease_id", "popularity", "comment_count",
]


def main():
    if not WANNA_FILE.exists():
        print(f"错误: {WANNA_FILE} 不存在, 请先运行 scripts/scrape_wanna.py")
        return

    with open(WANNA_FILE, encoding="utf-8") as f:
        wanna_songs = json.load(f)

    # 加载网易云匹配数据 (如果有)
    netease_map = {}
    if NETEASE_FILE.exists():
        with open(NETEASE_FILE, encoding="utf-8") as f:
            matched = json.load(f)
        for m in matched:
            wid = m.get("wanna_id")
            if wid and m.get("netease_id"):
                netease_map[wid] = m
        print(f"已加载 {len(netease_map)} 条网易云匹配数据")

    rows = []
    for s in wanna_songs:
        sid = s["id"]
        nm = netease_map.get(sid, {})
        rows.append({
            "id": sid,
            "name": s["name"],
            "artist": s["artist"],
            "dancer": s["dancer"],
            "player_count": s["playerCount"],
            "group": s["group"],
            "major": s["major"],
            "favorite": 0,
            "want_to_learn": 0,
            "netease_id": nm.get("netease_id", ""),
            "popularity": nm.get("popularity", ""),
            "comment_count": nm.get("comment_count", ""),
        })

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    matched_count = sum(1 for r in rows if r["netease_id"])
    print(f"已生成 {OUTPUT_FILE}")
    print(f"  总歌曲数: {len(rows)}")
    print(f"  有网易云数据: {matched_count}")
    print(f"  无网易云数据: {len(rows) - matched_count}")


if __name__ == "__main__":
    main()
