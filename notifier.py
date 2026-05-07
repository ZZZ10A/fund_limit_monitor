import base64
import hashlib
import hmac
import os
import time
from abc import ABC, abstractmethod
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests


class Notifier(ABC):
    @abstractmethod
    def send(self, title: str, message: str) -> bool:
        """Send a notification and return whether the request succeeded."""


class ConsoleNotifier(Notifier):
    def send(self, title: str, message: str) -> bool:
        print("Printing notification to console.")
        print(f"Title: {title}")
        print(message)
        return True


class MultiNotifier(Notifier):
    def __init__(self, notifiers):
        self.notifiers = notifiers

    def send(self, title: str, message: str) -> bool:
        results = []
        for notifier in self.notifiers:
            results.append(notifier.send(title, message))
        return all(results)


class WeChatNotifier(Notifier):
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, title: str, message: str) -> bool:
        data = {
            "msgtype": "markdown",
            "markdown": {"content": message},
        }
        return self._post(data)

    def _post(self, data):
        try:
            resp = requests.post(
                self.webhook_url,
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            print(f"WeChat notification sent. Status: {resp.status_code}")
            return 200 <= resp.status_code < 300
        except Exception as e:
            print(f"Failed to send WeChat notification: {e}")
            return False


class DingTalkNotifier(Notifier):
    def __init__(self, webhook_url: str, secret: str):
        self.webhook_url = webhook_url
        self.secret = secret

    def send(self, title: str, message: str) -> bool:
        data = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": message,
            },
        }
        return self._post(data)

    def _post(self, data):
        try:
            resp = requests.post(
                self._signed_webhook_url(),
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            print(f"DingTalk notification sent. Status: {resp.status_code}")
            return 200 <= resp.status_code < 300
        except Exception as e:
            print(f"Failed to send DingTalk notification: {e}")
            return False

    def _signed_webhook_url(self):
        timestamp = str(int(time.time() * 1000))
        sign = self._build_sign(timestamp)

        parsed = urlsplit(self.webhook_url)
        query_params = parse_qsl(parsed.query, keep_blank_values=True)
        query_params = [
            (key, value)
            for key, value in query_params
            if key not in ("timestamp", "sign")
        ]
        query_params.extend([("timestamp", timestamp), ("sign", sign)])

        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urlencode(query_params),
                parsed.fragment,
            )
        )

    def _build_sign(self, timestamp):
        string_to_sign = f"{timestamp}\n{self.secret}"
        digest = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")


def build_notifier(config: dict) -> Notifier:
    notifiers = []
    for notifier_config in _get_notifier_configs(config):
        notifier = _build_single_notifier(notifier_config)
        if notifier:
            notifiers.append(notifier)

    if not notifiers:
        print("Warning: No valid notifiers configured. Printing message instead.")
        return ConsoleNotifier()

    if len(notifiers) == 1:
        return notifiers[0]

    return MultiNotifier(notifiers)


def _get_notifier_configs(config):
    notifier_configs = config.get("notifiers")
    if notifier_configs is not None:
        if isinstance(notifier_configs, list):
            return notifier_configs
        print("Warning: 'notifiers' must be a list. Printing message instead.")
        return []

    notifier_config = config.get("notifier")
    if notifier_config is not None:
        return [notifier_config]

    return [{"type": "console"}]


def _build_single_notifier(notifier_config):
    if not isinstance(notifier_config, dict):
        print(f"Warning: Invalid notifier config '{notifier_config}'. Skipping notifier.")
        return None

    notifier_type = _normalize_notifier_type(notifier_config.get("type"))

    if notifier_type == "dingtalk":
        return _build_dingtalk_notifier(notifier_config)

    if notifier_type == "wechat":
        return _build_wechat_notifier(notifier_config)

    if notifier_type in ("console", ""):
        return ConsoleNotifier()

    print(
        f"Warning: Unsupported notifier type '{notifier_config.get('type')}'. "
        "Skipping notifier."
    )
    return None


def _build_dingtalk_notifier(notifier_config):
    webhook_url, webhook_url_env = _read_env(
        notifier_config,
        "webhook_url_env",
        "DINGTALK_WEBHOOK_URL",
    )
    secret, secret_env = _read_env(notifier_config, "secret_env", "DINGTALK_SECRET")

    if _is_configured(webhook_url) and _is_configured(secret):
        return DingTalkNotifier(webhook_url, secret)

    print(
        "Warning: DingTalk notifier requires environment variables "
        f"{webhook_url_env} and {secret_env}. "
        "Skipping notifier."
    )
    return None


def _build_wechat_notifier(notifier_config):
    webhook_url, webhook_url_env = _read_env(
        notifier_config,
        "webhook_url_env",
        "WEBHOOK_URL",
    )

    if _is_configured(webhook_url) and "YOUR_WECHAT" not in webhook_url:
        return WeChatNotifier(webhook_url)

    print(
        "Warning: WeChat notifier requires environment variable "
        f"{webhook_url_env}. Skipping notifier."
    )
    return None


def _normalize_notifier_type(value):
    if not value:
        return ""
    return str(value).strip().lower()


def _read_env(notifier_config, env_key, default_env_name):
    env_name = notifier_config.get(env_key) or default_env_name
    env_name = str(env_name).strip() or default_env_name
    return os.environ.get(env_name), env_name


def _is_configured(value):
    return bool(value and str(value).strip())
