#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = ["iris-plugin-sdk>=1.0,<2"]
# ///
"""校验 plugins/ 下的插件并生成可复现的 zip。

每个插件先通过 SDK 的 load_manifest、id/version 正则、builtin. 前缀、uv lock --check、
pyproject/uv.lock 源检查，再按 §4.2 的白名单打包。zip 条目排序，mtime 固定为
1980-01-01，权限固定为 0644，因此相同输入连续构建的 sha256 相同。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from iris_plugin_sdk import PluginManifest, PluginManifestError, load_manifest

PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+){0,3}$")
BUILTIN_PREFIX = "builtin."

ROOT_FILES = ("plugin.json", "pyproject.toml", "uv.lock", "README.md", "LICENSE")
TREE_DIRS = ("src", "ui")
SKIP_DIRS = frozenset(
    {"__pycache__", ".venv", ".git", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
)
SKIP_FILES = frozenset({".DS_Store"})

ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)
ZIP_FILE_MODE = 0o100644
MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_ENTRIES = 5000


class BuildError(RuntimeError):
    """插件不满足构建条件。"""


def _resolve(path: Path | None, default: Path, base: Path) -> Path:
    if path is None:
        return default
    return path if path.is_absolute() else (base / path)


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise BuildError(f"缺少 {path.name}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise BuildError(f"{path.name} 不是合法的 TOML：{exc}") from exc
    if not isinstance(data, dict):
        raise BuildError(f"{path.name} 必须是一个 TOML 表")
    return data


def _check_pyproject(plugin_dir: Path, manifest: PluginManifest) -> str:
    data = _read_toml(plugin_dir / "pyproject.toml")
    project = data.get("project")
    if not isinstance(project, dict):
        raise BuildError("pyproject.toml 缺少 [project]")
    name = project.get("name")
    if not isinstance(name, str) or not name:
        raise BuildError("pyproject.toml 的 [project].name 必须是非空文本")
    version = project.get("version")
    if not isinstance(version, str) or version != manifest.version:
        raise BuildError(
            f"pyproject.toml 的 version（{version!r}）与 plugin.json 的 "
            f"{manifest.version!r} 不一致"
        )
    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list) or not any(
        isinstance(item, str)
        and re.match(r"^iris-plugin-sdk(?:\s|\[|$|>=|<=|==|>|<|~=)", item)
        for item in dependencies
    ):
        raise BuildError("pyproject.toml 的 dependencies 必须包含 iris-plugin-sdk")

    tool = data.get("tool", {})
    uv = tool.get("uv", {}) if isinstance(tool, dict) else {}
    sources = uv.get("sources", {}) if isinstance(uv, dict) else {}
    if sources is not None and not isinstance(sources, dict):
        raise BuildError("[tool.uv.sources] 必须是表")
    for dependency, source in (sources or {}).items():
        if not isinstance(source, dict):
            raise BuildError(f"[tool.uv.sources].{dependency} 必须是表")
        forbidden = sorted({"path", "git", "editable"} & set(source))
        if forbidden:
            raise BuildError(
                f"[tool.uv.sources].{dependency} 含不允许的源：{', '.join(forbidden)}"
            )
    return name


def _lock_source_error(package: dict[str, Any]) -> str | None:
    """返回不允许的 uv.lock 源；允许 registry、HTTPS url 和项目自身的 "." 源。"""
    source = package.get("source")
    if not isinstance(source, dict):
        return f"source 缺失或不是表：{source!r}"
    if "git" in source:
        return "git 源（运行时镜像没有 git）"
    if "path" in source:
        return f"path 源：{source['path']!r}"
    if "editable" in source:
        if source["editable"] == ".":
            return None
        return f"editable 源：{source['editable']!r}"
    if "directory" in source:
        if source["directory"] == ".":
            return None
        return f"directory 源：{source['directory']!r}"
    if "virtual" in source:
        if source["virtual"] == ".":
            return None
        return f"virtual 源：{source['virtual']!r}"
    if "registry" in source:
        registry = source["registry"]
        if not isinstance(registry, str) or not registry.startswith(("https://", "http://")):
            return f"registry 地址不合法：{registry!r}"
        return None
    if "url" in source:
        url = source["url"]
        if not isinstance(url, str) or not url.startswith("https://"):
            return f"url 源必须是 HTTPS：{url!r}"
        return None
    return f"未知的 source：{source!r}"


def _check_uv_lock(plugin_dir: Path, project_name: str) -> None:
    lock = _read_toml(plugin_dir / "uv.lock")
    packages = lock.get("package", [])
    if not isinstance(packages, list) or not packages:
        raise BuildError("uv.lock 缺少 [[package]]")
    for package in packages:
        if not isinstance(package, dict):
            raise BuildError("uv.lock 的 [[package]] 必须是表")
        name = package.get("name", "?")
        problem = _lock_source_error(package)
        if problem is not None:
            raise BuildError(f"uv.lock 中 {name} 的源不允许：{problem}")

    root_sources = [
        package.get("source")
        for package in packages
        if isinstance(package, dict) and package.get("name") == project_name
    ]
    if not root_sources:
        raise BuildError(f"uv.lock 中找不到项目自身：{project_name}")


def _run_uv_lock_check(plugin_dir: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise BuildError("找不到 uv；请先安装 https://docs.astral.sh/uv/")
    try:
        result = subprocess.run(
            [uv, "lock", "--check", "--no-progress"],
            cwd=plugin_dir,
            check=False,
            text=True,
            capture_output=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        raise BuildError("uv lock --check 超过 180 秒") from exc
    if result.returncode != 0:
        output = "\n".join((result.stdout + "\n" + result.stderr).strip().splitlines()[-20:])
        raise BuildError(f"uv lock --check 失败：\n{output}")


def _collect_files(plugin_dir: Path) -> list[Path]:
    if not (plugin_dir / "src").is_dir():
        raise BuildError("缺少 src/ 目录")

    files: list[Path] = []
    for name in ROOT_FILES:
        path = plugin_dir / name
        if path.is_symlink():
            raise BuildError(f"不允许符号链接：{name}")
        if not path.exists():
            continue
        if not path.is_file():
            raise BuildError(f"{name} 必须是普通文件")
        files.append(path.relative_to(plugin_dir))

    for dirname in TREE_DIRS:
        root = plugin_dir / dirname
        if not root.exists():
            continue
        if root.is_symlink() or not root.is_dir():
            raise BuildError(f"{dirname}/ 必须是普通目录，不能是符号链接")
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            current = Path(dirpath)
            for name in list(dirnames):
                child = current / name
                relative = child.relative_to(plugin_dir)
                if child.is_symlink():
                    raise BuildError(f"不允许符号链接：{relative.as_posix()}")
                if name in SKIP_DIRS or name.endswith(".egg-info"):
                    dirnames.remove(name)
            for name in filenames:
                child = current / name
                relative = child.relative_to(plugin_dir)
                if child.is_symlink():
                    raise BuildError(f"不允许符号链接：{relative.as_posix()}")
                if name in SKIP_FILES or name.endswith(".pyc"):
                    continue
                if not child.is_file():
                    raise BuildError(f"不是普通文件：{relative.as_posix()}")
                files.append(relative)

    names = [path.as_posix() for path in files]
    if len(set(names)) != len(names):
        raise BuildError("打包文件列表有重复")
    for required in ("plugin.json", "pyproject.toml", "uv.lock"):
        if required not in names:
            raise BuildError(f"打包文件缺少 {required}")
    for relative in files:
        parts = PurePosixPath(relative.as_posix()).parts
        if not parts or ".." in parts or any("\\" in part for part in parts):
            raise BuildError(f"非法路径：{relative}")
    if len(files) > MAX_ENTRIES:
        raise BuildError(f"文件条目超过 {MAX_ENTRIES} 个")
    total = sum((plugin_dir / relative).stat().st_size for relative in files)
    if total > MAX_ZIP_BYTES:
        raise BuildError(f"插件内容超过 {MAX_ZIP_BYTES} 字节")
    return sorted(files, key=lambda path: path.as_posix())


def _validate_plugin(plugin_dir: Path) -> tuple[PluginManifest, list[Path]]:
    for required in ("plugin.json", "pyproject.toml", "uv.lock"):
        if not (plugin_dir / required).is_file():
            raise BuildError(f"缺少 {required}")
    if (plugin_dir / "uv.toml").exists():
        raise BuildError("不允许插件自带 uv.toml")

    try:
        manifest = load_manifest(plugin_dir)
    except PluginManifestError as exc:
        raise BuildError(f"plugin.json 校验失败：{exc}") from exc

    if not PLUGIN_ID_RE.fullmatch(manifest.id):
        raise BuildError(f"插件 id 不合法：{manifest.id!r}")
    if manifest.id.startswith(BUILTIN_PREFIX):
        raise BuildError(f"插件 id 不得使用保留前缀 builtin.：{manifest.id}")
    if not VERSION_RE.fullmatch(manifest.version):
        raise BuildError(f"插件版本不合法：{manifest.version!r}")

    project_name = _check_pyproject(plugin_dir, manifest)
    _check_uv_lock(plugin_dir, project_name)
    _run_uv_lock_check(plugin_dir)
    return manifest, _collect_files(plugin_dir)


def _write_zip(plugin_dir: Path, files: list[Path], out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{out.name}.", suffix=".tmp", dir=out.parent)
    os.close(descriptor)
    temporary_path = Path(temporary)
    try:
        with zipfile.ZipFile(
            temporary_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for relative in files:
                arcname = relative.as_posix()
                info = zipfile.ZipInfo(arcname, date_time=ZIP_DATE_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.create_version = 20
                info.extract_version = 20
                info.external_attr = ZIP_FILE_MODE << 16
                info.internal_attr = 0
                archive.writestr(
                    info,
                    (plugin_dir / relative).read_bytes(),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
        size = temporary_path.stat().st_size
        if size > MAX_ZIP_BYTES:
            raise BuildError(f"生成的 zip 超过 {MAX_ZIP_BYTES} 字节")
        temporary_path.replace(out)
        out.chmod(0o644)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    return digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验插件并生成确定性 zip")
    parser.add_argument("--plugins", type=Path, help="插件根目录，默认 <repo>/plugins")
    parser.add_argument("--out", type=Path, default=Path("dist"), help="输出目录，默认 dist")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    plugins_dir = _resolve(args.plugins, repo_root / "plugins", Path.cwd()).resolve()
    out_dir = _resolve(args.out, Path.cwd() / "dist", Path.cwd()).resolve()

    if not plugins_dir.is_dir():
        print(f"错误：插件目录不存在：{plugins_dir}", file=sys.stderr)
        return 1
    plugin_dirs = sorted(
        path
        for path in plugins_dir.iterdir()
        if path.is_dir() and (path / "plugin.json").is_file()
    )
    if not plugin_dirs:
        print(f"错误：{plugins_dir} 下没有插件", file=sys.stderr)
        return 1

    prepared: list[tuple[Path, PluginManifest, list[Path]]] = []
    errors: list[str] = []
    for plugin_dir in plugin_dirs:
        try:
            manifest, files = _validate_plugin(plugin_dir)
            prepared.append((plugin_dir, manifest, files))
        except (BuildError, OSError) as exc:
            errors.append(f"{plugin_dir.name}: {exc}")
    if errors:
        for error in errors:
            print(f"错误：{error}", file=sys.stderr)
        return 1

    seen: dict[tuple[str, str], Path] = {}
    for plugin_dir, manifest, _ in prepared:
        key = (manifest.id, manifest.version)
        if key in seen:
            errors.append(
                f"{plugin_dir.name}: ({manifest.id}, {manifest.version}) 与 "
                f"{seen[key].name} 重复"
            )
        else:
            seen[key] = plugin_dir
    if errors:
        for error in errors:
            print(f"错误：{error}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    for plugin_dir, manifest, files in prepared:
        out = out_dir / f"{manifest.id}-{manifest.version}.zip"
        try:
            digest = _write_zip(plugin_dir, files, out)
        except (BuildError, OSError) as exc:
            print(f"错误：{plugin_dir.name}: {exc}", file=sys.stderr)
            return 1
        print(
            f"{manifest.id} {manifest.version} -> {out} "
            f"({out.stat().st_size} bytes, sha256={digest})"
        )
    print(f"完成：{len(prepared)} 个插件 -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
