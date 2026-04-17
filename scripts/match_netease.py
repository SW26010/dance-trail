"""
批量查询 wanna songs 在网易云音乐的热度数据
使用网易云公开 API 搜索歌名+歌手，获取 popularity、score、评论数

用法:
    uv run python scripts/match_netease.py                # 完整运行 (约需数小时)
    uv run python scripts/match_netease.py --limit 100    # 只查前100首测试
    uv run python scripts/match_netease.py --resume       # 从上次中断处继续
"""

import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import ssl
from pathlib import Path

# --- 配置 ---
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INPUT_FILE = DATA_DIR / "wanna_songs.json"
OUTPUT_FILE = DATA_DIR / "wanna_netease_matched.json"
OUTPUT_CSV = DATA_DIR / "wanna_netease_matched.csv"
PROGRESS_FILE = DATA_DIR / ".match_progress.json"

NETEASE_SEARCH_URL = "https://music.163.com/api/search/get"
NETEASE_DETAIL_URL = "https://music.163.com/api/song/detail"
NETEASE_COMMENT_URL = "https://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}"
HEADERS = {
    "Referer": "https://music.163.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

REQUEST_DELAY = 0.5  # 每次请求间隔(秒)，避免被限速

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def fetch_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.loads(resp.read().decode())


def clean_song_name(name: str) -> str:
    """从歌名中提取最有意义的搜索词
    例: '江南 River South' -> '江南'
        'オドループ, Oddloop' -> 'Oddloop'
        'Shape of You (Remix)' -> 'Shape of You'
    """
    # 去掉括号内容
    name = re.sub(r"\s*[\(（].*?[\)）]", "", name)
    # 如果包含逗号分隔的中英文，取有意义的部分
    if ", " in name:
        parts = [p.strip() for p in name.split(", ")]
        # 优先取英文部分（网易云搜索英文歌名更精确）
        for p in parts:
            if re.search(r"[a-zA-Z]", p):
                return p
        return parts[0]
    # 如果是 "中文 English" 格式，取中文部分（通常更短更精确）
    parts = name.strip().split()
    if len(parts) >= 2:
        has_cjk = any("\u4e00" <= c <= "\u9fff" for c in parts[0])
        has_latin = any(c.isascii() and c.isalpha() for c in parts[-1])
        if has_cjk and has_latin:
            # 取中文部分
            cjk_parts = []
            for p in parts:
                if any("\u4e00" <= c <= "\u9fff" for c in p):
                    cjk_parts.append(p)
                else:
                    break
            if cjk_parts:
                return " ".join(cjk_parts)
    return name.strip()


def clean_artist(artist: str) -> str:
    """从歌手字段提取第一个歌手名"""
    # 按 & , / 分割取第一个
    for sep in ["&", ",", "/", "、"]:
        if sep in artist:
            artist = artist.split(sep)[0]
    return artist.strip()


def search_netease(song_name: str, artist: str) -> dict | None:
    """在网易云搜索歌曲，返回最佳匹配结果"""
    query = f"{artist} {song_name}"
    params = urllib.parse.urlencode({"s": query, "type": 1, "limit": 5})
    url = f"{NETEASE_SEARCH_URL}?{params}"

    try:
        data = fetch_json(url, headers=HEADERS)
        songs = data.get("result", {}).get("songs", [])
        if not songs:
            return None

        # 简单匹配：取第一个结果（搜索相关性排序）
        best = songs[0]
        return {
            "netease_id": best.get("id"),
            "netease_name": best.get("name", ""),
            "netease_artist": ", ".join(a["name"] for a in best.get("artists", [])),
            "netease_album": best.get("album", {}).get("name", ""),
        }
    except Exception:
        return None


def get_song_detail(song_id: int) -> dict:
    """获取歌曲详情（popularity, score）"""
    url = f"{NETEASE_DETAIL_URL}?ids=[{song_id}]"
    try:
        data = fetch_json(url, headers=HEADERS)
        songs = data.get("songs", [])
        if songs:
            s = songs[0]
            return {
                "popularity": s.get("popularity"),
                "score": s.get("score"),
            }
    except Exception:
        pass
    return {"popularity": None, "score": None}


def get_comment_count(song_id: int) -> int | None:
    """获取评论总数"""
    url = NETEASE_COMMENT_URL.format(song_id=song_id) + "?limit=1"
    try:
        data = fetch_json(url, headers=HEADERS)
        return data.get("total")
    except Exception:
        return None


def load_progress() -> dict:
    """加载进度"""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"completed": {}, "failed": []}


def save_progress(progress: dict):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="批量查询 wanna songs 的网易云音乐热度")
    parser.add_argument("--limit", type=int, default=0, help="只查询前 N 首 (0=全部)")
    parser.add_argument("--resume", action="store_true", help="从上次中断处继续")
    args = parser.parse_args()

    # 加载 wanna songs
    with open(INPUT_FILE, encoding="utf-8") as f:
        wanna_songs = json.load(f)

    # 去重: 按 (name, artist) 只查一次
    unique_songs = {}
    for s in wanna_songs:
        key = (s["name"], s["artist"])
        if key not in unique_songs:
            unique_songs[key] = s

    songs_to_query = list(unique_songs.values())
    if args.limit > 0:
        songs_to_query = songs_to_query[:args.limit]

    print(f"总歌曲数: {len(wanna_songs)}")
    print(f"去重后唯一 (name, artist): {len(unique_songs)}")
    print(f"本次查询数: {len(songs_to_query)}")

    # 加载进度
    progress = load_progress() if args.resume else {"completed": {}, "failed": []}
    results = progress["completed"]

    matched = sum(1 for v in results.values() if v.get("netease_id"))
    failed_count = sum(1 for v in results.values() if not v.get("netease_id"))
    skipped = 0

    print(f"已完成: {len(results)} (匹配: {matched}, 未匹配: {failed_count})")
    print(f"开始查询...\n")

    try:
        for i, song in enumerate(songs_to_query):
            key = f"{song['name']}|||{song['artist']}"

            if key in results:
                skipped += 1
                continue

            clean_name = clean_song_name(song["name"])
            clean_art = clean_artist(song["artist"])

            # 搜索
            match = search_netease(clean_name, clean_art)
            time.sleep(REQUEST_DELAY)

            result = {
                "wanna_id": song["id"],
                "wanna_name": song["name"],
                "wanna_artist": song["artist"],
                "search_query_name": clean_name,
                "search_query_artist": clean_art,
            }

            if match:
                result.update(match)
                # 获取详情
                detail = get_song_detail(match["netease_id"])
                time.sleep(REQUEST_DELAY * 0.5)
                result.update(detail)
                # 获取评论数
                comments = get_comment_count(match["netease_id"])
                time.sleep(REQUEST_DELAY * 0.5)
                result["comment_count"] = comments
                matched += 1
            else:
                result.update({
                    "netease_id": None,
                    "netease_name": None,
                    "netease_artist": None,
                    "netease_album": None,
                    "popularity": None,
                    "score": None,
                    "comment_count": None,
                })
                failed_count += 1

            results[key] = result
            done = len(results)
            total = len(songs_to_query)
            status = "✅" if match else "❌"
            pop = result.get("popularity", "")
            pop_str = f" pop={pop}" if pop is not None else ""

            if done % 10 == 0 or not match:
                print(
                    f"[{done}/{total}] {status} {song['name']} - {clean_art}"
                    f"{pop_str}"
                )

            # 每50条保存一次进度
            if done % 50 == 0:
                progress["completed"] = results
                save_progress(progress)

    except KeyboardInterrupt:
        print("\n\n⚠️  中断！保存进度...")
    finally:
        progress["completed"] = results
        save_progress(progress)

    # 保存最终结果
    all_results = list(results.values())
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    # 保存 CSV
    if all_results:
        fieldnames = list(all_results[0].keys())
        with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_results)

    # 统计
    total_done = len(all_results)
    total_matched = sum(1 for r in all_results if r.get("netease_id"))
    total_failed = total_done - total_matched

    print(f"\n{'=' * 50}")
    print(f"查询完成!")
    print(f"  总查询: {total_done}")
    print(f"  匹配成功: {total_matched} ({total_matched/total_done*100:.1f}%)" if total_done else "")
    print(f"  匹配失败: {total_failed} ({total_failed/total_done*100:.1f}%)" if total_done else "")
    print(f"  跳过(已完成): {skipped}")
    print(f"\n输出文件:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {OUTPUT_CSV}")

    if total_matched:
        pops = [r["popularity"] for r in all_results if r.get("popularity") is not None]
        if pops:
            print(f"\n热度分布:")
            print(f"  平均 popularity: {sum(pops)/len(pops):.1f}")
            print(f"  最高: {max(pops)}")
            print(f"  最低: {min(pops)}")

            # 分段统计
            buckets = {"0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0}
            for p in pops:
                if p <= 20:
                    buckets["0-20"] += 1
                elif p <= 40:
                    buckets["21-40"] += 1
                elif p <= 60:
                    buckets["41-60"] += 1
                elif p <= 80:
                    buckets["61-80"] += 1
                else:
                    buckets["81-100"] += 1
            for k, v in buckets.items():
                bar = "█" * (v * 40 // max(buckets.values())) if max(buckets.values()) > 0 else ""
                print(f"  {k}: {bar} {v}")


if __name__ == "__main__":
    main()
