"""翻译：串行调用服务器的 /v1/translate，引擎之间按各自的限速间隔，失败重试 5 次。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from iris_plugin_sdk import MetadataError

from iris_plugin_metatube.client import MetaTubeClient
from iris_plugin_metatube.settings import Config

# 与 jellyfin-plugin-metatube 一致：百度 1 次/秒，OpenAI 1 次/秒，其他 10 次/秒
_DELAYS = {"baidu": 1.0, "openai": 1.0}
_DEFAULT_DELAY = 0.1
_ATTEMPTS = 5
_JAPANESE = "ja"


class Translator:
    def __init__(
        self,
        client: MetaTubeClient,
        logger: Any,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._logger = logger
        self._sleep = sleep
        self._lock = threading.Lock()

    def translate_movie(self, cfg: Config, title: str, summary: str) -> tuple[str, str]:
        """按翻译模式翻译标题和简介；失败时保留原文，已翻译好的部分照常使用。"""
        translation = cfg.translation
        if translation.mode == "disabled":
            return title, summary
        target = translation.language
        if target.casefold().split("-")[0] == _JAPANESE:
            self._logger.warning("翻译目标语言不能是日语：%s", target)
            return title, summary
        try:
            if translation.mode in ("title", "both") and title.strip():
                title = self._translate(cfg, title, target)
            if translation.mode in ("summary", "both") and summary.strip():
                summary = self._translate(cfg, summary, target)
        except MetadataError as exc:
            self._logger.warning("翻译失败：%s", exc.message)
        return title, summary

    def _translate(self, cfg: Config, text: str, target: str) -> str:
        delay = _DELAYS.get(cfg.translation.engine.casefold(), _DEFAULT_DELAY)
        with self._lock:
            for attempt in range(1, _ATTEMPTS + 1):
                self._sleep(delay)
                try:
                    return self._client.translate(cfg, text, target)
                except MetadataError:
                    if attempt == _ATTEMPTS:
                        raise
        raise AssertionError("unreachable")
