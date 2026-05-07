import base64
import hashlib
import hmac
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, quote_plus, urlsplit

from notifier import (
    ConsoleNotifier,
    DingTalkNotifier,
    MultiNotifier,
    WeChatNotifier,
    build_notifier,
)


class DingTalkNotifierTest(unittest.TestCase):
    def test_signed_webhook_url_contains_timestamp_and_encoded_sign(self):
        notifier = DingTalkNotifier(
            "https://oapi.dingtalk.com/robot/send?access_token=TOKEN",
            "SECRET",
        )

        with patch("notifier.time.time", return_value=1710000000.123):
            signed_url = notifier._signed_webhook_url()

        query = urlsplit(signed_url).query
        params = parse_qs(query)
        timestamp = "1710000000123"
        expected_sign = base64.b64encode(
            hmac.new(
                b"SECRET",
                f"{timestamp}\nSECRET".encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
        ).decode("utf-8")

        self.assertEqual(params["access_token"], ["TOKEN"])
        self.assertEqual(params["timestamp"], [timestamp])
        self.assertEqual(params["sign"], [expected_sign])
        self.assertIn(f"sign={quote_plus(expected_sign)}", query)

    @patch("notifier.requests.post")
    def test_sends_dingtalk_markdown_payload(self, post):
        post.return_value = Mock(status_code=200)
        notifier = DingTalkNotifier("https://example.com/send?access_token=TOKEN", "SECRET")

        with patch("builtins.print"):
            result = notifier.send("日报", "# 内容")

        self.assertTrue(result)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["msgtype"], "markdown")
        self.assertEqual(payload["markdown"]["title"], "日报")
        self.assertEqual(payload["markdown"]["text"], "# 内容")

    @patch("notifier.requests.post")
    def test_sends_dingtalk_image_payload_when_image_url_is_provided(self, post):
        post.return_value = Mock(status_code=200)
        notifier = DingTalkNotifier("https://example.com/send?access_token=TOKEN", "SECRET")
        image_url = "https://example.com/reports/fund-limit.png"

        with patch("builtins.print"):
            result = notifier.send("日报", "# 内容", image_url=image_url)

        self.assertTrue(result)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["msgtype"], "markdown")
        self.assertEqual(payload["markdown"]["title"], "日报")
        self.assertEqual(
            payload["markdown"]["text"],
            "## 日报\n\n"
            "![日报](https://example.com/reports/fund-limit.png)\n\n"
            "[查看原图](https://example.com/reports/fund-limit.png)",
        )


class WeChatNotifierTest(unittest.TestCase):
    @patch("notifier.requests.post")
    def test_sends_wechat_markdown_payload(self, post):
        post.return_value = Mock(status_code=200)
        notifier = WeChatNotifier("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY")

        with patch("builtins.print"):
            result = notifier.send("日报", "# 内容")

        self.assertTrue(result)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["msgtype"], "markdown")
        self.assertEqual(payload["markdown"]["content"], "# 内容")


class MultiNotifierTest(unittest.TestCase):
    def test_sends_to_all_notifiers_and_returns_false_when_any_fails(self):
        first = Mock()
        first.send.return_value = True
        second = Mock()
        second.send.return_value = False
        notifier = MultiNotifier([first, second])

        result = notifier.send("日报", "# 内容")

        self.assertFalse(result)
        first.send.assert_called_once_with("日报", "# 内容", image_url=None)
        second.send.assert_called_once_with("日报", "# 内容", image_url=None)

    def test_passes_image_url_to_all_notifiers(self):
        first = Mock()
        first.send.return_value = True
        second = Mock()
        second.send.return_value = True
        notifier = MultiNotifier([first, second])

        result = notifier.send("日报", "# 内容", image_url="https://example.com/a.png")

        self.assertTrue(result)
        first.send.assert_called_once_with(
            "日报",
            "# 内容",
            image_url="https://example.com/a.png",
        )
        second.send.assert_called_once_with(
            "日报",
            "# 内容",
            image_url="https://example.com/a.png",
        )


class BuildNotifierTest(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {
            "DINGTALK_WEBHOOK_URL": "https://env.example.com/send?access_token=TOKEN",
            "DINGTALK_SECRET": "ENV_SECRET",
        },
        clear=True,
    )
    def test_default_environment_values_are_used_for_configured_dingtalk_notifier(self):
        notifier = build_notifier(
            {
                "notifier": {
                    "type": "dingtalk",
                }
            }
        )

        self.assertIsInstance(notifier, DingTalkNotifier)
        self.assertEqual(
            notifier.webhook_url,
            "https://env.example.com/send?access_token=TOKEN",
        )
        self.assertEqual(notifier.secret, "ENV_SECRET")

    @patch.dict(
        "os.environ",
        {
            "DINGTALK_WEBHOOK_URL_1": "https://example.com/send?access_token=TOKEN",
            "DINGTALK_SECRET_1": "SECRET",
        },
        clear=True,
    )
    def test_custom_environment_variable_names_are_used_for_dingtalk_notifier(self):
        notifier = build_notifier(
            {
                "notifier": {
                    "type": "dingtalk",
                    "webhook_url_env": "DINGTALK_WEBHOOK_URL_1",
                    "secret_env": "DINGTALK_SECRET_1",
                }
            }
        )

        self.assertIsInstance(notifier, DingTalkNotifier)
        self.assertEqual(
            notifier.webhook_url,
            "https://example.com/send?access_token=TOKEN",
        )
        self.assertEqual(notifier.secret, "SECRET")

    @patch.dict(
        "os.environ",
        {
            "DINGTALK_WEBHOOK_URL": "https://example.com/send?access_token=TOKEN",
            "DINGTALK_SECRET": "SECRET",
        },
        clear=True,
    )
    def test_returns_dingtalk_notifier_when_selected_and_config_complete(self):
        notifier = build_notifier(
            {
                "notifier": {
                    "type": "dingtalk",
                },
            }
        )

        self.assertIsInstance(notifier, DingTalkNotifier)

    @patch.dict("os.environ", {}, clear=True)
    @patch("builtins.print")
    def test_returns_console_when_selected_dingtalk_config_incomplete(self, _print):
        notifier = build_notifier(
            {
                "notifier": {
                    "type": "dingtalk",
                },
            }
        )

        self.assertIsInstance(notifier, ConsoleNotifier)

    @patch.dict("os.environ", {}, clear=True)
    @patch("builtins.print")
    def test_does_not_read_dingtalk_secret_values_from_config(self, _print):
        notifier = build_notifier(
            {
                "notifier": {
                    "type": "dingtalk",
                    "webhook_url": "https://example.com/send?access_token=TOKEN",
                    "secret": "SECRET",
                },
            }
        )

        self.assertIsInstance(notifier, ConsoleNotifier)

    @patch.dict(
        "os.environ",
        {
            "DINGTALK_WEBHOOK_URL_1": "https://example.com/send?access_token=TOKEN",
            "DINGTALK_SECRET_1": "SECRET",
            "WECHAT_WEBHOOK_URL_1": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY",
        },
        clear=True,
    )
    def test_returns_multi_notifier_when_multiple_notifiers_configured(self):
        notifier = build_notifier(
            {
                "notifiers": [
                    {
                        "type": "dingtalk",
                        "webhook_url_env": "DINGTALK_WEBHOOK_URL_1",
                        "secret_env": "DINGTALK_SECRET_1",
                    },
                    {
                        "type": "wechat",
                        "webhook_url_env": "WECHAT_WEBHOOK_URL_1",
                    },
                ],
            }
        )

        self.assertIsInstance(notifier, MultiNotifier)
        self.assertIsInstance(notifier.notifiers[0], DingTalkNotifier)
        self.assertIsInstance(notifier.notifiers[1], WeChatNotifier)

    @patch.dict(
        "os.environ",
        {
            "WECHAT_WEBHOOK_URL_1": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY",
        },
        clear=True,
    )
    @patch("builtins.print")
    def test_skips_invalid_notifier_in_multiple_config(self, _print):
        notifier = build_notifier(
            {
                "notifiers": [
                    {
                        "type": "dingtalk",
                        "webhook_url_env": "MISSING_DINGTALK_WEBHOOK_URL",
                        "secret_env": "MISSING_DINGTALK_SECRET",
                    },
                    {
                        "type": "wechat",
                        "webhook_url_env": "WECHAT_WEBHOOK_URL_1",
                    },
                ],
            }
        )

        self.assertIsInstance(notifier, WeChatNotifier)

    @patch.dict(
        "os.environ",
        {
            "WEBHOOK_URL": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY",
        },
        clear=True,
    )
    def test_returns_wechat_notifier_when_selected_and_config_complete(self):
        notifier = build_notifier(
            {
                "notifier": {
                    "type": "wechat",
                },
            }
        )

        self.assertIsInstance(notifier, WeChatNotifier)

    @patch.dict("os.environ", {}, clear=True)
    @patch("builtins.print")
    def test_does_not_read_wechat_webhook_url_from_config(self, _print):
        notifier = build_notifier(
            {
                "notifier": {
                    "type": "wechat",
                    "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY",
                },
            }
        )

        self.assertIsInstance(notifier, ConsoleNotifier)

    @patch.dict("os.environ", {}, clear=True)
    def test_returns_console_notifier_when_selected(self):
        notifier = build_notifier({"notifier": {"type": "console"}})

        self.assertIsInstance(notifier, ConsoleNotifier)

    @patch.dict("os.environ", {}, clear=True)
    @patch("builtins.print")
    def test_returns_console_notifier_when_type_unknown(self, _print):
        notifier = build_notifier({"notifier": {"type": "email"}})

        self.assertIsInstance(notifier, ConsoleNotifier)

    @patch.dict("os.environ", {}, clear=True)
    @patch("builtins.print")
    def test_returns_console_notifier_when_notifiers_is_not_list(self, _print):
        notifier = build_notifier({"notifiers": {"type": "console"}})

        self.assertIsInstance(notifier, ConsoleNotifier)


if __name__ == "__main__":
    unittest.main()
