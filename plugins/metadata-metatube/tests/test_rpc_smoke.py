"""真实子进程 RPC 冒烟：握手、provider 能力和设置页。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from iris_plugin_sdk import PluginRequest, PluginResponse, load_manifest
from iris_plugin_sdk.testing import RpcClient

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _admin(client: RpcClient, method: str, path: str, body: Any = None) -> dict[str, Any]:
    response = client.request(
        "admin.request", {"request": PluginRequest(method, path, {}, body, 1)}
    )
    assert isinstance(response, PluginResponse)
    return cast(dict[str, Any], response.body)


def test_manifest_declares_metatube_contract() -> None:
    manifest = load_manifest(PLUGIN_ROOT)

    assert manifest.id == "metatube"
    assert manifest.version == "1.0.1"
    assert manifest.sdk == ">=1.0,<2.0"
    assert set(manifest.provides) == {
        "metadata.search",
        "metadata.details",
        "metadata.images",
        "metadata.people",
        "admin.ui",
    }
    assert manifest.capabilities == ("logger",)
    assert (PLUGIN_ROOT / "ui" / manifest.pages[0].entry).is_file()


def test_real_process_serves_settings_and_reports_unavailable(tmp_path: Path) -> None:
    client = RpcClient(PLUGIN_ROOT, module="iris_plugin_metatube")
    try:
        initialized = client.initialize(tmp_path / "data")
        assert initialized["manifest"]["id"] == "metatube"

        reason = client.request("provider.unavailable_reason", {"capability": "metadata.details"})
        assert isinstance(reason, str) and "服务器" in reason

        page = _admin(client, "GET", "settings")
        names = {field["name"] for field in page["fields"]}
        assert {"server", "token", "name_template", "title_substitution_table"} <= names
        assert page["testable"] is True
        assert page["values"]["token"] == {"set": False}
        assert page["values"]["enable_directors"] is True
        assert page["values"]["image_quality"] == 90

        saved = _admin(
            client,
            "PUT",
            "settings",
            {"server": "https://metatube.example", "token": "t0ken", "translation_mode": "both"},
        )
        assert saved["values"]["server"] == "https://metatube.example"
        assert saved["values"]["token"] == {"set": True}
        assert saved["values"]["translation_mode"] == "both"

        status = _admin(client, "GET", "status")
        assert status == {
            "server": "https://metatube.example",
            "token_set": True,
            "translation": "both",
        }
        assert (
            client.request("provider.unavailable_reason", {"capability": "metadata.details"})
            is None
        )
        assert (
            client.request("metadata.page_url", {"kind": "movie", "remote_id": "FANZA:abc"})
            == "https://metatube.example?redirect=FANZA:abc"
        )
    finally:
        client.close()
