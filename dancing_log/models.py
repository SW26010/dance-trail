"""
数据模型定义和推荐权重计算

数据文件:
- data/songs.csv        歌曲主数据 (以 wanna id 为主键)
- data/dance_log.csv    舞蹈记录
"""

import csv
import hashlib
import math
from datetime import datetime, date, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SONGS_FILE = DATA_DIR / "songs.csv"
DANCE_LOG_FILE = DATA_DIR / "dance_log.csv"

# === 歌曲主数据字段 ===
SONG_FIELDS = [
    "id",               # int, 主键, wanna dance id
    "name",             # str, 歌名
    "artist",           # str, 歌手
    "dancer",           # str, 舞者/系列名
    "player_count",     # int, 舞蹈人数 (1=Solo, 2=Duet, ...)
    "group",            # str, 子分组 (Just Dance Solo 等)
    "major",            # str, 大类 (Just Dance Series 等)
    "favorite",         # bool, 是否喜欢 (0/1)
    "want_to_learn",    # bool, 是否待练 (0/1)
    "netease_id",       # int|null, 网易云音乐 ID
    "popularity",       # float|null, 网易云热度 (0-100)
    "comment_count",    # int|null, 网易云评论数
]

# === 舞蹈记录字段 ===
DANCE_LOG_FIELDS = [
    "timestamp",        # str, ISO 8601 时间 (e.g. 2026-04-17T20:30:00+08:00)
    "song_id",          # int, 歌曲 ID (对应 songs.csv 的 id)
    "source",           # str, 点歌来源: self=主动点, recommend=系统推荐, other=别人点
    "note",             # str, 备注 (可选)
]

# 点歌来源
SOURCE_SELF = "self"            # 主动点
SOURCE_RECOMMEND = "recommend"  # 系统推荐
SOURCE_OTHER = "other"          # 别人点

SOURCE_LABELS = {
    SOURCE_SELF: "主动点",
    SOURCE_RECOMMEND: "系统推荐",
    SOURCE_OTHER: "别人点",
}


def load_songs() -> list[dict]:
    """加载歌曲主数据"""
    if not SONGS_FILE.exists():
        return []
    with open(SONGS_FILE, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_songs(songs: list[dict]):
    """保存歌曲主数据"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SONGS_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SONG_FIELDS)
        writer.writeheader()
        writer.writerows(songs)


def load_dance_log() -> list[dict]:
    """加载舞蹈记录"""
    if not DANCE_LOG_FILE.exists():
        return []
    with open(DANCE_LOG_FILE, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_dance_log(records: list[dict]):
    """保存舞蹈记录"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DANCE_LOG_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DANCE_LOG_FIELDS)
        writer.writeheader()
        writer.writerows(records)


def _playlist_seed(target_date: date) -> str:
    """生成基于日期的确定性种子字符串"""
    return f"dancing-log-{target_date.isoformat()}"


def _seeded_tiebreaker(seed: str, song_id: str) -> float:
    """基于种子和歌曲 ID 的确定性伪随机值 (0-1)"""
    h = hashlib.sha256(f"{seed}:{song_id}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def get_daily_playlist_ids(songs: list[dict], dance_log: list[dict],
                           target_date: date | None = None,
                           count: int = 20) -> set[str]:
    """获取指定日期推荐歌单的歌曲 ID 集合 (可复现)"""
    playlist = generate_daily_playlist(songs, dance_log, count=count,
                                       target_date=target_date)
    return {str(s["id"]) for s in playlist}


def add_dance_record(song_id: int, source: str = SOURCE_SELF, note: str = "",
                     timestamp: str | None = None, auto_detect: bool = True):
    """添加一条舞蹈记录

    auto_detect: 若 source 为 self，检查该歌曲是否在今日推荐歌单中，
                 若在则自动改为 recommend。
    """
    records = load_dance_log()
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).astimezone().isoformat()

    actual_source = source
    if auto_detect and source == SOURCE_SELF:
        songs = load_songs()
        if songs:
            today = datetime.fromisoformat(timestamp).date()
            playlist_ids = get_daily_playlist_ids(songs, records, target_date=today)
            if str(song_id) in playlist_ids:
                actual_source = SOURCE_RECOMMEND

    records.append({
        "timestamp": timestamp,
        "song_id": str(song_id),
        "source": actual_source,
        "note": note,
    })
    save_dance_log(records)
    return actual_source


def compute_recommendation(songs: list[dict], dance_log: list[dict],
                           now: datetime | None = None) -> list[dict]:
    """
    计算歌曲推荐权重

    权重公式:
        weight = W_fav * favorite_score
               + W_pop * popularity_score
               + W_freq * frequency_decay
               + W_recency * recency_decay
               + W_want * want_score

    设计思路:
    - favorite_score: 喜欢的歌 +1.0
    - popularity_score: 热度归一化 (popularity/100)
    - frequency_decay: 跳得越少权重越高 (1 / (1 + dance_count))
    - recency_decay: 越久没跳权重越高 (sigmoid of days since last dance)
    - want_score: 标记"待练"的 +1.0
    """
    if now is None:
        now = datetime.now(timezone.utc).astimezone()

    # 权重系数
    W_FAV = 2.0        # 喜欢
    W_POP = 1.0        # 热度
    W_FREQ = 3.0       # 频次衰减 (跳得少加分多)
    W_RECENCY = 2.5    # 时间衰减 (久没跳加分多)
    W_WANT = 2.5       # 待练

    # 统计每首歌的舞蹈记录
    dance_stats: dict[str, dict] = {}  # song_id -> {count, last_time}
    for record in dance_log:
        sid = record["song_id"]
        if sid not in dance_stats:
            dance_stats[sid] = {"count": 0, "last_time": None}
        dance_stats[sid]["count"] += 1
        try:
            t = datetime.fromisoformat(record["timestamp"])
            if dance_stats[sid]["last_time"] is None or t > dance_stats[sid]["last_time"]:
                dance_stats[sid]["last_time"] = t
        except (ValueError, TypeError):
            pass

    results = []
    for song in songs:
        sid = str(song.get("id", ""))

        # favorite_score
        fav = 1.0 if song.get("favorite") in ("1", "true", True) else 0.0

        # popularity_score (0-1)
        try:
            pop = float(song.get("popularity", 0) or 0) / 100.0
        except (ValueError, TypeError):
            pop = 0.0

        # want_score
        want = 1.0 if song.get("want_to_learn") in ("1", "true", True) else 0.0

        # frequency_decay: 没跳过和跳得少的歌分更高
        stats = dance_stats.get(sid, {"count": 0, "last_time": None})
        dance_count = stats["count"]
        freq_score = 1.0 / (1.0 + dance_count)

        # recency_decay: 越久没跳分越高, 没跳过的满分
        if stats["last_time"] is not None:
            days_since = (now - stats["last_time"]).total_seconds() / 86400
            # sigmoid: 映射到 0-1, 7天半衰期
            recency_score = 1.0 / (1.0 + math.exp(-0.1 * (days_since - 7)))
        else:
            recency_score = 1.0  # 从没跳过

        weight = (
            W_FAV * fav
            + W_POP * pop
            + W_FREQ * freq_score
            + W_RECENCY * recency_score
            + W_WANT * want
        )

        results.append({
            **song,
            "_weight": round(weight, 3),
            "_dance_count": dance_count,
            "_days_since_last": round(
                (now - stats["last_time"]).total_seconds() / 86400, 1
            ) if stats["last_time"] else None,
        })

    results.sort(key=lambda x: x["_weight"], reverse=True)
    return results


def generate_daily_playlist(songs: list[dict], dance_log: list[dict],
                            count: int = 20,
                            target_date: date | None = None) -> list[dict]:
    """生成每日推荐歌单

    使用 target_date 作为随机种子，相同日期 + 相同数据 = 相同歌单。
    默认为今天。
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc).astimezone().date()

    ranked = compute_recommendation(songs, dance_log)

    # 对同权重歌曲使用日期种子做确定性排序
    seed = _playlist_seed(target_date)
    ranked.sort(
        key=lambda x: (-x["_weight"], _seeded_tiebreaker(seed, str(x["id"]))),
    )
    return ranked[:count]
