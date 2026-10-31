"""用 SDK 的 manifest 与真实子进程 RPC 客户端做握手测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from iris_plugin_sdk import PluginRequest, PluginResponse, load_manifest
from iris_plugin_sdk.testing import RpcClient

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def test_manifest_declares_example_contract() -> None:
    manifest = load_manifest(PLUGIN_ROOT)

    assert manifest.id == "example.hello"
    assert manifest.version == "1.0.0"
    assert manifest.sdk == ">=1.0,<2.0"
    assert manifest.provides == ("admin.ui",)
    assert manifest.capabilities == ("logger",)
    assert manifest.ui == "ui"
    assert manifest.pages[0].entry == "index.html"
    assert (PLUGIN_ROOT / "ui" / "index.html").is_file()


def test_real_process_handshake_and_admin_page(tmp_path: Path) -> None:
    client = RpcClient(PLUGIN_ROOT, module="iris_plugin_example_hello")
    try:
        initialized = client.initialize(tmp_path / "data")

        manifest = initialized["manifest"]
        assert manifest["id"] == "example.hello"
        assert manifest["version"] == "1.0.0"
        assert manifest["provides"] == ["admin.ui"]

        response = client.request(
            "admin.request",
            {"request": PluginRequest("GET", "status", {}, None, 1)},
        )
        assert isinstance(response, PluginResponse)
        body = cast(dict[str, Any], response.body)
        assert body == {"message": "hello from example.hello"}
    finally:
        client.close()
