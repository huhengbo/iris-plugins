#!/usr/bin/env python3
"""根据已经构建好的 zip 生成 index.json。

sha256 和 size 一律取自 --dist 下的实际文件；条目元数据取自 zip 内的 plugin.json。
--base-url 适合本地目录或 Pages 同目录；--release-repo 按每个插件的
<id>-v<version> tag 生成 GitHub Release 下载地址。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

SCHEMA_VERSION = 1
PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+){0,3}$")
BUILTIN_PREFIX = "builtin."
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 1000
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class IndexBuildError(RuntimeError):
    """无法从 dist 生成索引。"""


def _read_manifest(zip_path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            if "plugin.json" not in names:
                raise IndexBuildError(f"{zip_path.name} 根目录缺少 plugin.json")
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or "\\" in name:
                    raise IndexBuildError(f"{zip_path.name} 含非法条目：{name!r}")
            data = json.loads(archive.read("plugin.json"))
    except (zipfile.BadZipFile, OSError) as exc:
        raise IndexBuildError(f"{zip_path.name} 不是可读的 zip：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise IndexBuildError(f"{zip_path.name} 的 plugin.json 不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise IndexBuildError(f"{zip_path.name} 的 plugin.json 必须是对象")
    for key in ("id", "name", "version", "sdk", "entry", "provides"):
        if key not in data:
            raise IndexBuildError(f"{zip_path.name} 的 plugin.json 缺少 {key}")
    plugin_id = data.get("id")
    version = data.get("version")
    if not isinstance(plugin_id, str) or not PLUGIN_ID_RE.fullmatch(plugin_id):
        raise IndexBuildError(f"{zip_path.name} 的插件 id 不合法：{plugin_id!r}")
    if plugin_id.startswith(BUILTIN_PREFIX):
        raise IndexBuildError(f"{zip_path.name} 使用了保留前缀 builtin.：{plugin_id}")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise IndexBuildError(f"{zip_path.name} 的版本不合法：{version!r}")
    expected = f"{plugin_id}-{version}.zip"
    if zip_path.name != expected:
        raise IndexBuildError(f"{zip_path.name} 与 manifest 的 {expected} 不一致")

    provides = data.get("provides")
    capabilities = data.get("capabilities", [])
    if not isinstance(provides, list) or not provides or any(
        not isinstance(item, str) or not item for item in provides
    ):
        raise IndexBuildError(f"{zip_path.name} 的 provides 必须是非空文本数组")
    if not isinstance(capabilities, list) or any(
        not isinstance(item, str) or not item for item in capabilities
    ):
        raise IndexBuildError(f"{zip_path.name} 的 capabilities 必须是文本数组")
    description = data.get("description", "")
    if not isinstance(description, str) or len(description) > 200:
        raise IndexBuildError(f"{zip_path.name} 的 description 必须是 200 字以内的文本")
    if not isinstance(data.get("name"), str) or not data["name"]:
        raise IndexBuildError(f"{zip_path.name} 的 name 必须是非空文本")
    if not isinstance(data.get("sdk"), str) or not data["sdk"]:
        raise IndexBuildError(f"{zip_path.name} 的 sdk 必须是非空文本")

    return {
        "id": plugin_id,
        "name": data["name"],
        "description": description,
        "version": version,
        "sdk": data["sdk"],
        "provides": provides,
        "capabilities": capabilities,
        "entry": data["entry"],
    }


def _plugin_dirs(plugins_dir: Path) -> dict[str, str]:
    """id -> 源码目录名，用于生成 homepage；目录不存在时允许为空。"""
    if not plugins_dir.is_dir():
        return {}
    mapping: dict[str, str] = {}
    for child in sorted(plugins_dir.iterdir()):
        manifest_path = child / "plugin.json"
        if not child.is_dir() or not manifest_path.is_file():
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IndexBuildError(f"读取 {manifest_path} 失败：{exc}") from exc
        plugin_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(plugin_id, str):
            raise IndexBuildError(f"{manifest_path} 缺少文本 id")
        if plugin_id in mapping:
            raise IndexBuildError(f"plugins/ 下 id 重复：{plugin_id}")
        mapping[plugin_id] = child.name
    return mapping


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _url_for(entry: dict[str, Any], *, base_url: str | None, release_repo: str | None) -> str:
    filename = f"{entry['id']}-{entry['version']}.zip"
    if release_repo is not None:
        tag = f"{entry['id']}-v{entry['version']}"
        return (
            f"https://github.com/{release_repo}/releases/download/"
            f"{quote(tag, safe='')}/{quote(filename, safe='')}"
        )
    assert base_url is not None
    if not base_url:
        return quote(filename, safe="")
    prefix = base_url if base_url.endswith("/") else base_url + "/"
    return prefix + quote(filename, safe="")


def _generated_at(value: str | None) -> str:
    if value:
        return value
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, data: dict[str, Any]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    size = len(payload.encode("utf-8"))
    if size > MAX_INDEX_BYTES:
        raise IndexBuildError(f"index.json 超过 {MAX_INDEX_BYTES} 字节")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        Path(temporary).replace(path)
        path.chmod(0o644)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return size


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 zip 生成 Iris 插件仓库 index.json")
    parser.add_argument("--dist", type=Path, default=Path("dist"), help="zip 所在目录")
    parser.add_argument("--out", type=Path, required=True, help="index.json 输出路径")
    parser.add_argument("--name", default="Iris 官方插件仓库", help="仓库显示名")
    parser.add_argument(
        "--base-url",
        default=None,
        help="zip 的 URL 前缀；传空字符串生成相对 index 的文件名",
    )
    parser.add_argument(
        "--release-repo",
        default=None,
        metavar="OWNER/REPO",
        help="release 模式：按 <id>-v<version> tag 生成 Release 下载地址",
    )
    parser.add_argument("--homepage-base", default=None, help="插件主页前缀；传空字符串则不输出主页")
    parser.add_argument("--generated-at", default=None, help="固定 generated_at（测试用）")
    parser.add_argument("--plugins", type=Path, default=None, help="源码插件目录，用于 homepage")
    args = parser.parse_args(argv)

    if (args.base_url is None) == (args.release_repo is None):
        parser.error("--base-url 与 --release-repo 必须且只能提供一个")
    if args.release_repo is not None and not REPO_RE.fullmatch(args.release_repo):
        parser.error("--release-repo 必须是 OWNER/REPO")
    if not args.name.strip():
        parser.error("--name 不能为空")

    repo_root = Path(__file__).resolve().parents[1]
    dist = args.dist if args.dist.is_absolute() else (Path.cwd() / args.dist)
    out = args.out if args.out.is_absolute() else (Path.cwd() / args.out)
    plugins_dir = args.plugins or repo_root / "plugins"
    if not plugins_dir.is_absolute():
        plugins_dir = Path.cwd() / plugins_dir

    if not dist.is_dir():
        print(f"错误：dist 目录不存在：{dist}", file=sys.stderr)
        return 1
    zips = sorted(dist.glob("*.zip"))
    if not zips:
        print(f"错误：{dist} 下没有 .zip", file=sys.stderr)
        return 1
    if len(zips) > MAX_ENTRIES:
        print(f"错误：zip 数量超过 {MAX_ENTRIES}", file=sys.stderr)
        return 1

    if args.homepage_base is not None:
        homepage_base = args.homepage_base.strip()
    elif args.release_repo is not None:
        homepage_base = f"https://github.com/{args.release_repo}/tree/main/plugins"
    else:
        homepage_base = "https://github.com/huhengbo/iris-plugins/tree/main/plugins"

    plugin_dirs = _plugin_dirs(plugins_dir)
    entries: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], Path] = {}
    try:
        for zip_path in zips:
            if zip_path.is_symlink():
                raise IndexBuildError(f"不允许符号链接：{zip_path}")
            source = _read_manifest(zip_path)
            key = (source["id"], source["version"])
            if key in seen:
                raise IndexBuildError(f"({key[0]}, {key[1]}) 重复：{seen[key]} 与 {zip_path}")
            seen[key] = zip_path
            data = zip_path.read_bytes()
            directory = plugin_dirs.get(source["id"])
            homepage = (
                f"{homepage_base.rstrip('/')}/{directory}"
                if homepage_base and directory is not None
                else None
            )
            entries.append(
                {
                    "id": source["id"],
                    "name": source["name"],
                    "description": source["description"],
                    "version": source["version"],
                    "sdk": source["sdk"],
                    "provides": source["provides"],
                    "capabilities": source["capabilities"],
                    "url": _url_for(
                        source,
                        base_url=args.base_url,
                        release_repo=args.release_repo,
                    ),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                    "homepage": homepage,
                    "signature": None,
                }
            )
        entries.sort(key=lambda item: (item["id"], _version_key(item["version"])))
        index = {
            "schema": SCHEMA_VERSION,
            "name": args.name,
            "generated_at": _generated_at(args.generated_at),
            "plugins": entries,
        }
        size = _write_json(out, index)
    except (IndexBuildError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    print(f"生成 {out}：{len(entries)} 个插件，{size} 字节")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
