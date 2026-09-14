import base64
import unittest

from app.douyin_inventory_providers import (
    AUTH_REQUIRED_MESSAGE,
    DouyinAuthRequiredError,
    netscape_to_playwright_cookies,
    parse_aweme_post_response,
    parse_netscape_cookies,
    PlaywrightDouyinInventoryProvider,
)


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class TestNetscapeCookieConversion(unittest.TestCase):
    def test_parse_netscape_and_convert(self):
        text = (
            "# Netscape HTTP Cookie File\n"
            ".douyin.com\tTRUE\t/\tTRUE\t1893456000\tsessionid\tabc123\n"
            ".douyin.com\tTRUE\t/\tFALSE\t1893456000\ttt_webid\txyz\n"
        )
        parsed = parse_netscape_cookies(text)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["name"], "sessionid")
        self.assertEqual(parsed[0]["value"], "abc123")
        self.assertTrue(parsed[0]["secure"])

        converted = netscape_to_playwright_cookies(parsed)
        self.assertEqual(len(converted), 2)
        for cookie in converted:
            for key in ("name", "value", "domain", "path", "expires", "secure"):
                self.assertIn(key, cookie)
            self.assertIn("douyin.com", cookie["domain"])

    def test_no_hardcoded_cookie_values(self):
        import inspect

        from app import douyin_inventory_providers as providers

        source = inspect.getsource(providers)
        self.assertNotIn("sessionid\t", source)
        # Module must not contain real cookie values.
        self.assertNotIn("abc123", source)


class TestAwemePostParsing(unittest.TestCase):
    def test_parse_aweme_list_with_pagination(self):
        payload = {
            "aweme_list": [
                {
                    "aweme_id": "7467752268393530654",
                    "desc": "Test video 一",
                    "create_time": 1700000000,
                    "author": {"nickname": "creator"},
                    "share_url": "https://www.douyin.com/video/7467752268393530654",
                    "video": {"cover": {"url_list": ["https://cover/1.jpg"]}},
                    "duration": 15000,
                    "statistics": {"digg_count": 10},
                },
                {
                    "aweme_id": "7467752268393530655",
                    "desc": "Test video 二",
                    "create_time": 1700001000,
                    "author": {"nickname": "creator"},
                    "video": {},
                    "statistics": {},
                },
            ],
            "has_more": 1,
            "max_cursor": "100",
        }
        videos, has_more, max_cursor = parse_aweme_post_response(payload)
        self.assertEqual(len(videos), 2)
        self.assertEqual(has_more, 1)
        self.assertEqual(max_cursor, "100")
        self.assertEqual(videos[0]["video_id"], "7467752268393530654")
        self.assertEqual(videos[0]["author"], "creator")
        self.assertEqual(videos[0]["cover"], "https://cover/1.jpg")
        self.assertEqual(videos[0]["duration"], 15000)
        self.assertIsNotNone(videos[0]["douyin_created_at"])
        # Fallback URL when share_url missing.
        self.assertTrue(videos[1]["url"].endswith("7467752268393530655"))

    def test_parse_terminal_page(self):
        videos, has_more, _ = parse_aweme_post_response(
            {"aweme_list": [], "has_more": 0, "max_cursor": "0"}
        )
        self.assertEqual(videos, [])
        self.assertEqual(has_more, 0)

    def test_parse_invalid_payload(self):
        videos, has_more, cursor = parse_aweme_post_response(None)
        self.assertEqual(videos, [])
        self.assertEqual(has_more, 0)
        self.assertEqual(cursor, "")


class TestPlaywrightAuthRequired(unittest.TestCase):
    def test_missing_cookies_raises_clear_error(self):
        import app.douyin_inventory_providers as providers

        original = providers.settings.douyin_cookies_b64
        providers.settings.douyin_cookies_b64 = ""
        try:
            with self.assertRaises(DouyinAuthRequiredError) as ctx:
                PlaywrightDouyinInventoryProvider().fetch_all(
                    "https://www.douyin.com/user/SEC123", "SEC123", "src"
                )
            self.assertIn("cookies are required", str(ctx.exception).lower())
            self.assertEqual(str(ctx.exception), AUTH_REQUIRED_MESSAGE)
        finally:
            providers.settings.douyin_cookies_b64 = original

    def test_sec_uid_resolution(self):
        resolve = PlaywrightDouyinInventoryProvider._resolve_sec_uid
        self.assertEqual(resolve("SEC123"), "SEC123")
        self.assertEqual(
            resolve("https://m.douyin.com/share/user/SEC123"), "SEC123"
        )
        self.assertEqual(
            resolve("https://www.douyin.com/user/SEC123?x=1"), "SEC123"
        )


if __name__ == "__main__":
    unittest.main()
