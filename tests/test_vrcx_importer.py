import unittest

from dancing_log.vrcx_importer import parse_wanna_song_id, parse_wanna_url


class WannaUrlParsingTest(unittest.TestCase):
    def test_parses_documented_wanna_api_urls(self):
        self.assertEqual(
            parse_wanna_song_id("https://api.udon.dance/Api/Songs/play?id=3114"),
            3114,
        )
        self.assertEqual(
            parse_wanna_song_id("http://api.udon.dance/Api/Songs/play?node=nya&id=3114"),
            3114,
        )

    def test_parses_observed_wanna_api_compatible_urls(self):
        self.assertEqual(
            parse_wanna_song_id("http://api.wannadance.online/Api/Songs/play?node=cf&id=5671"),
            5671,
        )
        self.assertEqual(
            parse_wanna_song_id("https://139.196.46.195:51886/Api/Songs/play?id=2588"),
            2588,
        )

    def test_parses_wanna_cdn_file_urls(self):
        self.assertEqual(
            parse_wanna_song_id(
                "http://play.udon.dance/files/2502/3114-67a5b9397e62d.mp4?e=x&s=y"
            ),
            3114,
        )
        result = parse_wanna_url("http://nya.xin.moe/files/2502/3114-67a5b9397e62d.mp4")
        self.assertEqual(result.song_id, 3114)
        self.assertEqual(result.url_kind, "wanna_cdn")
        self.assertEqual(result.method, "cdn_file_path")

    def test_does_not_parse_other_dance_systems_as_wanna(self):
        self.assertIsNone(parse_wanna_song_id("http://jd.pypy.moe/api/v1/videos/4051.mp4"))
        self.assertIsNone(
            parse_wanna_song_id("https://api.dudufit.dance/api/v1/videos/1321?cdn=jpn")
        )

    def test_rejects_non_wanna_numeric_urls(self):
        self.assertIsNone(parse_wanna_song_id("https://v.dm5.vrchat.org.cn/play/4164"))
        self.assertIsNone(parse_wanna_song_id("https://www.youtube.com/watch?v=3114"))


if __name__ == "__main__":
    unittest.main()
