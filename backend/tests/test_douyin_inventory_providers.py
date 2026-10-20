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


class TestPlaywrightAnonymousFirst(unittest.TestCase):
    def _provider(self):
        return PlaywrightDouyinInventoryProvider()

    def test_empty_cookies_returns_empty_list_without_raise(self):
        import app.douyin_inventory_providers as providers

        original = providers.settings.douyin_cookies_b64
        providers.settings.douyin_cookies_b64 = ""
        try:
            # Cookies are OPTIONAL: no raise just because env is empty.
            self.assertEqual(providers.load_cookies_optional(), [])
            self.assertFalse(providers.cookies_configured())
        finally:
            providers.settings.douyin_cookies_b64 = original

    def test_anonymous_videos_pass_without_cookie(self):
        import app.douyin_inventory_providers as providers
        from unittest.mock import patch

        original = providers.settings.douyin_cookies_b64
        providers.settings.douyin_cookies_b64 = ""
        try:
            provider = self._provider()
            videos = [{"video_id": "1", "title": "t", "description": "",
                       "url": "https://www.douyin.com/video/1",
                       "douyin_created_at": None}]
            with patch.object(
                provider, "_attempt",
                return_value=(videos, {"auth_wall_hit": False, "payloads_seen": 2}),
            ) as mock_attempt:
                result = provider.fetch_all(
                    "https://www.douyin.com/user/SEC123", "SEC123", "src"
                )
            self.assertEqual(result, videos)
            # Only the anonymous attempt ran (cookies=None).
            self.assertEqual(mock_attempt.call_count, 1)
            self.assertIsNone(mock_attempt.call_args[1].get("cookies"))
            probe = providers.get_last_access_probe()
            self.assertEqual(
                probe, {"anonymous_ok": True, "cookie_required": False,
                        "at": probe["at"]}
            )
        finally:
            providers.settings.douyin_cookies_b64 = original

    def test_anonymous_auth_wall_without_cookie_raises_auth_required(self):
        import app.douyin_inventory_providers as providers
        from unittest.mock import patch

        original = providers.settings.douyin_cookies_b64
        providers.settings.douyin_cookies_b64 = ""
        try:
            provider = self._provider()
            with patch.object(
                provider, "_attempt",
                return_value=([], {"auth_wall_hit": True, "payloads_seen": 0}),
            ):
                with self.assertRaises(DouyinAuthRequiredError) as ctx:
                    provider.fetch_all(
                        "https://www.douyin.com/user/SEC123", "SEC123", "src"
                    )
            self.assertEqual(str(ctx.exception), AUTH_REQUIRED_MESSAGE)
            probe = providers.get_last_access_probe()
            self.assertFalse(probe["anonymous_ok"])
            self.assertTrue(probe["cookie_required"])
        finally:
            providers.settings.douyin_cookies_b64 = original

    def test_anonymous_auth_wall_retries_with_cookies(self):
        import base64

        import app.douyin_inventory_providers as providers
        from unittest.mock import patch

        netscape = ".douyin.com\tTRUE\t/\tTRUE\t1893456000\tsessionid\tabc123\n"
        original = providers.settings.douyin_cookies_b64
        providers.settings.douyin_cookies_b64 = base64.b64encode(
            netscape.encode()
        ).decode()
        try:
            provider = self._provider()
            cookie_videos = [{"video_id": "9", "title": "t", "description": "",
                              "url": "https://www.douyin.com/video/9",
                              "douyin_created_at": None}]

            def fake_attempt(target, cookies=None, full=True, max_pages=200):
                if cookies is None:
                    return [], {"auth_wall_hit": True, "payloads_seen": 0}
                self.assertTrue(len(cookies) > 0)
                return cookie_videos, {"auth_wall_hit": False, "payloads_seen": 3}

            with patch.object(provider, "_attempt", side_effect=fake_attempt):
                result = provider.fetch_all(
                    "https://www.douyin.com/user/SEC123", "SEC123", "src"
                )
            self.assertEqual(result, cookie_videos)
            probe = providers.get_last_access_probe()
            self.assertFalse(probe["anonymous_ok"])
            self.assertTrue(probe["cookie_required"])
        finally:
            providers.settings.douyin_cookies_b64 = original

    def test_anonymous_empty_without_wall_returns_empty(self):
        import app.douyin_inventory_providers as providers
        from unittest.mock import patch

        original = providers.settings.douyin_cookies_b64
        providers.settings.douyin_cookies_b64 = ""
        try:
            provider = self._provider()
            with patch.object(
                provider, "_attempt",
                return_value=([], {"auth_wall_hit": False, "payloads_seen": 2}),
            ):
                # Genuine empty (payloads seen, terminal page): no raise.
                self.assertEqual(
                    provider.fetch_all(
                        "https://www.douyin.com/user/SEC123", "SEC123", "src"
                    ),
                    [],
                )
        finally:
            providers.settings.douyin_cookies_b64 = original

    def test_auth_wall_content_detection(self):
        import app.douyin_inventory_providers as providers

        self.assertTrue(
            providers.page_content_looks_like_auth_wall(
                "请登录后查看 login verify challenge"
            )
        )
        self.assertTrue(providers.page_content_looks_like_auth_wall("请验证身份 验证"))
        self.assertFalse(
            providers.page_content_looks_like_auth_wall(
                "<html><body>video list aweme content</body></html>"
            )
        )
        self.assertTrue(providers.response_status_looks_like_auth_wall(403))
        self.assertFalse(providers.response_status_looks_like_auth_wall(200))

    def test_challenge_after_cookie_retry_is_hard_fail(self):
        import app.douyin_inventory_providers as providers
        from unittest.mock import patch

        import base64

        netscape = ".douyin.com\tTRUE\t/\tTRUE\t1893456000\tsessionid\tabc123\n"
        original = providers.settings.douyin_cookies_b64
        providers.settings.douyin_cookies_b64 = base64.b64encode(
            netscape.encode()
        ).decode()
        try:
            provider = PlaywrightDouyinInventoryProvider()
            with patch.object(
                provider, "_attempt",
                return_value=([], {"auth_wall_hit": True, "payloads_seen": 0,
                                   "challenge_hit": True}),
            ):
                with self.assertRaises(providers.DouyinInventoryError) as ctx:
                    provider.fetch_all(
                        "https://www.douyin.com/user/SEC123", "SEC123", "src"
                    )
            # Hard FAIL (not auth_required): cookies existed but challenge persists.
            self.assertNotIsInstance(ctx.exception, DouyinAuthRequiredError)
            self.assertIn("challenge", str(ctx.exception).lower())
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
