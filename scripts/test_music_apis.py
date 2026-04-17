"""测试各个音乐 API 获取歌曲热度信息"""

import urllib.request
import urllib.parse
import json
import ssl

# 忽略 SSL 验证问题（仅测试用）
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

TEST_SONG = "Shape of You"
TEST_ARTIST = "Ed Sheeran"
TEST_SONG_CN = "晴天"
TEST_ARTIST_CN = "周杰伦"


def fetch_json(url, headers=None):
    """发起 GET 请求并返回 JSON"""
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.loads(resp.read().decode())


def test_deezer(song, artist):
    """Deezer API - 无需认证"""
    print("\n" + "=" * 60)
    print("🎵 Deezer API")
    print("=" * 60)
    try:
        query = urllib.parse.quote(f"{artist} {song}")
        url = f"https://api.deezer.com/search/track?q={query}&limit=3"
        data = fetch_json(url)
        if data.get("data"):
            for i, track in enumerate(data["data"]):
                print(f"\n  [{i+1}] {track['artist']['name']} - {track['title']}")
                print(f"      rank (热度): {track.get('rank', 'N/A')}")
                print(f"      duration: {track.get('duration', 'N/A')}s")
                print(f"      album: {track.get('album', {}).get('title', 'N/A')}")
        else:
            print("  未找到结果")
    except Exception as e:
        print(f"  ❌ 错误: {e}")


def test_lastfm(song, artist, api_key=None):
    """Last.fm API - 需要 API Key"""
    print("\n" + "=" * 60)
    print("🎵 Last.fm API")
    print("=" * 60)
    if not api_key:
        print("  ⚠️  需要 API Key，请到 https://www.last.fm/api/account/create 申请")
        print("  申请后设置环境变量 LASTFM_API_KEY 或直接传入")
        # 尝试从环境变量读取
        import os
        api_key = os.environ.get("LASTFM_API_KEY")
        if not api_key:
            print("  ⏭️  跳过 (未设置 LASTFM_API_KEY)")
            return
    try:
        params = urllib.parse.urlencode({
            "method": "track.getInfo",
            "api_key": api_key,
            "artist": artist,
            "track": song,
            "format": "json",
        })
        url = f"https://ws.audioscrobbler.com/2.0/?{params}"
        data = fetch_json(url)
        if "track" in data:
            track = data["track"]
            print(f"\n  {track.get('artist', {}).get('name', '')} - {track.get('name', '')}")
            print(f"      listeners (独立听众): {track.get('listeners', 'N/A')}")
            print(f"      playcount (播放次数): {track.get('playcount', 'N/A')}")
            tags = [t["name"] for t in track.get("toptags", {}).get("tag", [])]
            print(f"      tags: {', '.join(tags) if tags else 'N/A'}")
        else:
            print(f"  未找到结果: {data.get('message', '')}")
    except Exception as e:
        print(f"  ❌ 错误: {e}")


def test_spotify(song, artist, token=None):
    """Spotify API - 需要 OAuth Token"""
    print("\n" + "=" * 60)
    print("🎵 Spotify API")
    print("=" * 60)
    import os
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")

    if not token and client_id and client_secret:
        # 用 Client Credentials 获取 token
        try:
            import base64
            auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            req = urllib.request.Request(
                "https://accounts.spotify.com/api/token",
                data=b"grant_type=client_credentials",
                headers={
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                token_data = json.loads(resp.read().decode())
                token = token_data["access_token"]
        except Exception as e:
            print(f"  ❌ 获取 token 失败: {e}")
            return

    if not token:
        print("  ⚠️  需要设置环境变量 SPOTIFY_CLIENT_ID 和 SPOTIFY_CLIENT_SECRET")
        print("  或者设置 SPOTIFY_TOKEN")
        token = os.environ.get("SPOTIFY_TOKEN")
        if not token:
            print("  ⏭️  跳过")
            return

    try:
        query = urllib.parse.quote(f"track:{song} artist:{artist}")
        url = f"https://api.spotify.com/v1/search?q={query}&type=track&limit=3"
        data = fetch_json(url, headers={"Authorization": f"Bearer {token}"})
        tracks = data.get("tracks", {}).get("items", [])
        if tracks:
            for i, track in enumerate(tracks):
                artists = ", ".join(a["name"] for a in track["artists"])
                print(f"\n  [{i+1}] {artists} - {track['name']}")
                print(f"      popularity (0-100): {track.get('popularity', 'N/A')}")
                print(f"      album: {track.get('album', {}).get('name', 'N/A')}")
                print(f"      release_date: {track.get('album', {}).get('release_date', 'N/A')}")
                print(f"      duration_ms: {track.get('duration_ms', 'N/A')}")
        else:
            print("  未找到结果")
    except Exception as e:
        print(f"  ❌ 错误: {e}")


def test_youtube(song, artist, api_key=None):
    """YouTube Data API v3 - 需要 API Key"""
    print("\n" + "=" * 60)
    print("🎵 YouTube Data API v3")
    print("=" * 60)
    import os
    api_key = api_key or os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("  ⚠️  需要 API Key，请到 Google Cloud Console 开通 YouTube Data API v3")
        print("  设置环境变量 YOUTUBE_API_KEY")
        print("  ⏭️  跳过")
        return
    try:
        query = urllib.parse.quote(f"{artist} {song} official")
        url = (
            f"https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet&q={query}&type=video&maxResults=3&key={api_key}"
        )
        data = fetch_json(url)
        video_ids = [item["id"]["videoId"] for item in data.get("items", [])]
        if video_ids:
            stats_url = (
                f"https://www.googleapis.com/youtube/v3/videos"
                f"?part=statistics,snippet&id={','.join(video_ids)}&key={api_key}"
            )
            stats_data = fetch_json(stats_url)
            for i, item in enumerate(stats_data.get("items", [])):
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                print(f"\n  [{i+1}] {snippet.get('title', 'N/A')}")
                print(f"      viewCount (观看次数): {stats.get('viewCount', 'N/A')}")
                print(f"      likeCount (点赞数): {stats.get('likeCount', 'N/A')}")
                print(f"      commentCount (评论数): {stats.get('commentCount', 'N/A')}")
                print(f"      channel: {snippet.get('channelTitle', 'N/A')}")
        else:
            print("  未找到结果")
    except Exception as e:
        print(f"  ❌ 错误: {e}")


def test_netease(song, artist):
    """网易云音乐（公开接口，不保证稳定）"""
    print("\n" + "=" * 60)
    print("🎵 网易云音乐 API")
    print("=" * 60)
    try:
        query = urllib.parse.quote(f"{artist} {song}")
        url = f"https://music.163.com/api/search/get?s={query}&type=1&limit=3"
        headers = {
            "Referer": "https://music.163.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        data = fetch_json(url, headers=headers)
        songs = data.get("result", {}).get("songs", [])
        if songs:
            for i, s in enumerate(songs):
                artists_str = ", ".join(a["name"] for a in s.get("artists", []))
                print(f"\n  [{i+1}] {artists_str} - {s['name']}")
                print(f"      id: {s.get('id', 'N/A')}")
                print(f"      album: {s.get('album', {}).get('name', 'N/A')}")
                # 尝试获取详细信息
                song_id = s.get("id")
                if song_id:
                    detail_url = f"https://music.163.com/api/song/detail?ids=[{song_id}]"
                    detail = fetch_json(detail_url, headers=headers)
                    detail_songs = detail.get("songs", [])
                    if detail_songs:
                        ds = detail_songs[0]
                        print(f"      popularity (热度): {ds.get('popularity', 'N/A')}")
                        print(f"      score (评分): {ds.get('score', 'N/A')}")

                # 尝试获取评论数
                if song_id:
                    try:
                        comment_url = f"https://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}?limit=1"
                        comment_data = fetch_json(comment_url, headers=headers)
                        print(f"      total comments (评论数): {comment_data.get('total', 'N/A')}")
                    except Exception:
                        print(f"      total comments: 获取失败")
        else:
            print(f"  未找到结果")
    except Exception as e:
        print(f"  ❌ 错误: {e}")


def main():
    print("🔍 测试各 API 获取歌曲热度数据")
    print(f"   英文测试曲: {TEST_ARTIST} - {TEST_SONG}")
    print(f"   中文测试曲: {TEST_ARTIST_CN} - {TEST_SONG_CN}")

    # === Deezer (无需认证) ===
    test_deezer(TEST_SONG, TEST_ARTIST)
    test_deezer(TEST_SONG_CN, TEST_ARTIST_CN)

    # === Last.fm ===
    test_lastfm(TEST_SONG, TEST_ARTIST)
    test_lastfm(TEST_SONG_CN, TEST_ARTIST_CN)

    # === Spotify ===
    test_spotify(TEST_SONG, TEST_ARTIST)
    test_spotify(TEST_SONG_CN, TEST_ARTIST_CN)

    # === YouTube ===
    test_youtube(TEST_SONG, TEST_ARTIST)
    test_youtube(TEST_SONG_CN, TEST_ARTIST_CN)

    # === 网易云 ===
    test_netease(TEST_SONG_CN, TEST_ARTIST_CN)
    test_netease(TEST_SONG, TEST_ARTIST)


if __name__ == "__main__":
    main()
