"""示例插件入口：只有 admin.ui 和一个静态设置页。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from iris_plugin_sdk import (
    PluginContext,
    PluginRequest,
    PluginRequestError,
    PluginResponse,
)

PLUGIN_ROOT = Path(__file__).resolve().parents[2]


class HelloAdminUi:
    """admin.ui 能力：ui_root 由宿主提供静态文件，handle 只实现一个状态接口。"""

    @property
    def ui_root(self) -> Path:
        return PLUGIN_ROOT / "ui"

    def handle(self, request: PluginRequest) -> PluginResponse:
        if request.method == "GET" and request.path == "status":
            return PluginResponse(body={"message": "hello from example.hello"})
        raise PluginRequestError("接口不存在", status=404, code="not_found")


class ExampleHelloPlugin:
    def __init__(self) -> None:
        self._admin = HelloAdminUi()

    def start(self, context: PluginContext) -> None:
        context.logger.info("example.hello 已启动")

    def stop(self) -> None:
        return None

    def providers(self) -> Mapping[str, object]:
        return {"admin.ui": self._admin}
