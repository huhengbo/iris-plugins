"""MetaTube 插件入口。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from iris_plugin_sdk import (
    DirectHttpClient,
    JsonSettingsStore,
    PluginContext,
    SettingsAdminUi,
    SettingsEndpoint,
)

from iris_plugin_metatube.client import TIMEOUT_SECONDS, MetaTubeClient
from iris_plugin_metatube.provider import MetaTubeProvider
from iris_plugin_metatube.settings import Config, metatube_settings
from iris_plugin_metatube.translation import Translator

PLUGIN_DIR = Path(__file__).resolve().parents[2]
USER_AGENT = "MetaTube/iris-plugin"


class MetaTubePlugin:
    def __init__(self) -> None:
        self._http: DirectHttpClient | None = None
        self._provider: MetaTubeProvider | None = None
        self._admin: SettingsAdminUi | None = None

    def start(self, context: PluginContext) -> None:
        # 不走宿主 http 能力：它拒绝内网地址，而 MetaTube 服务器通常部署在内网或同一台机器上
        self._http = DirectHttpClient(context.proxy, timeout=TIMEOUT_SECONDS)
        client = MetaTubeClient(self._http, USER_AGENT)
        settings = metatube_settings(JsonSettingsStore(context.data_dir))
        provider = MetaTubeProvider(
            client,
            lambda: Config.from_values(settings.values()),
            context.plugin_id,
            context.logger,
            Translator(client, context.logger),
        )
        settings.bind_tester(provider.test_connection)
        self._provider = provider
        self._admin = SettingsAdminUi(settings, PLUGIN_DIR / "ui", status=lambda: _status(settings))
        context.logger.info("MetaTube 插件已准备")

    def stop(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None
        self._provider = None
        self._admin = None

    def config_changed(self, *, proxy: str | None, host_url: str | None) -> None:
        if self._http is not None:
            self._http.config_changed(proxy=proxy)

    def providers(self) -> Mapping[str, object]:
        if self._provider is None or self._admin is None:
            return {}
        return {
            "metadata.search": self._provider,
            "metadata.details": self._provider,
            "metadata.images": self._provider,
            "metadata.people": self._provider,
            "admin.ui": self._admin,
        }


def _status(settings: SettingsEndpoint) -> dict[str, Any]:
    cfg = Config.from_values(settings.values())
    return {
        "server": cfg.server or None,
        "token_set": bool(cfg.token),
        "translation": cfg.translation.mode,
    }
