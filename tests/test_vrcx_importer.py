import unittest

from dance_trail.storage import DUDU_SYSTEM_KEY, WANNA_SYSTEM_KEY
from dance_trail.vrcx_importer import parse_dance_url, parse_wanna_song_id


class DanceUrlParsingTest(unittest.TestCase):
    def test_parses_documented_wanna_api_urls(self):
        result = parse_dance_url("https://api.udon.dance/Api/Songs/play?id=3114")
        self.assertEqual(result.system_key, WANNA_SYSTEM_KEY)
        self.assertEqual(result.external_id, "3114")
        self.assertEqual(result.url_kind, "wanna_api")
        self.assertEqual(parse_wanna_song_id("https://api.udon.dance/Api/Songs/play?id=3114"), 3114)

        result = parse_dance_url("http://api.udon.dance/Api/Songs/play?node=nya&id=3114")
        self.assertEqual(result.system_key, WANNA_SYSTEM_KEY)
        self.assertEqual(result.external_id, "3114")

    def test_parses_observed_wanna_api_compatible_urls(self):
        self.assertEqual(
            parse_dance_url("http://api.wannadance.online/Api/Songs/play?node=cf&id=5671").external_id,
            "5671",
        )
        self.assertEqual(
            parse_dance_url("https://139.196.46.195:51886/Api/Songs/play?id=2588").external_id,
            "2588",
        )

    def test_parses_wanna_cdn_file_urls(self):
        result = parse_dance_url(
            "http://play.udon.dance/files/2502/3114-67a5b9397e62d.mp4?e=x&s=y"
        )
        self.assertEqual(result.system_key, WANNA_SYSTEM_KEY)
        self.assertEqual(result.external_id, "3114")
        self.assertEqual(result.url_kind, "wanna_cdn")
        self.assertEqual(result.method, "cdn_file_path")

    def test_parses_pypydance_and_dudu_urls(self):
        pypy = parse_dance_url("http://jd.pypy.moe/api/v1/videos/4051.mp4")
        self.assertEqual(pypy.system_key, "pypydance")
        self.assertEqual(pypy.external_id, "4051")
        self.assertEqual(pypy.url_kind, "pypydance_api")
        self.assertEqual(pypy.method, "api_video_file_path")

        pypy = parse_dance_url("http://api.pypy.dance/video?id=4666")
        self.assertEqual(pypy.system_key, "pypydance")
        self.assertEqual(pypy.external_id, "4666")
        self.assertEqual(pypy.url_kind, "pypydance_api")
        self.assertEqual(pypy.method, "api_query_id")

        dudu = parse_dance_url("https://api.dudufit.dance/api/v1/videos/1321?cdn=jpn")
        self.assertEqual(dudu.system_key, DUDU_SYSTEM_KEY)
        self.assertEqual(dudu.external_id, "1321")
        self.assertEqual(dudu.url_kind, "dudu")
        self.assertEqual(dudu.method, "api_video_path")

        dudu_cdn = parse_dance_url(
            "https://global-cdn.dudufit.dance/videos/2074-057e.mp4?etag=057e"
        )
        self.assertEqual(dudu_cdn.system_key, DUDU_SYSTEM_KEY)
        self.assertEqual(dudu_cdn.external_id, "2074")
        self.assertEqual(dudu_cdn.method, "cdn_file_path")

        dudu_web = parse_dance_url("https://www.dudufit.dance/zh/videos/2074")
        self.assertEqual(dudu_web.system_key, DUDU_SYSTEM_KEY)
        self.assertEqual(dudu_web.external_id, "2074")
        self.assertEqual(dudu_web.method, "web_video_path")

    def test_rejects_non_wanna_numeric_urls(self):
        self.assertIsNone(parse_wanna_song_id("https://v.dm5.vrchat.org.cn/play/4164"))
        self.assertIsNone(parse_wanna_song_id("https://www.youtube.com/watch?v=3114"))


if __name__ == "__main__":
    unittest.main()
