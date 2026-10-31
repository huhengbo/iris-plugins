#!/usr/bin/env bash
# 对 plugins/ 下的每个插件执行 uv sync --frozen、ruff 和 pytest。
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

uv_bin="${UV:-uv}"
if ! command -v "$uv_bin" >/dev/null 2>&1; then
  echo "错误：找不到 uv，请先安装 https://docs.astral.sh/uv/" >&2
  exit 1
fi

shopt -s nullglob
manifests=("$root"/plugins/*/plugin.json)
if [ "${#manifests[@]}" -eq 0 ]; then
  echo "错误：$root/plugins 下没有插件" >&2
  exit 1
fi

for manifest in "${manifests[@]}"; do
  plugin_dir="$(dirname "$manifest")"
  plugin_name="$(basename "$plugin_dir")"
  echo "==> $plugin_name"
  (
    cd "$plugin_dir"
    "$uv_bin" sync --frozen --no-progress
    "$uv_bin" run --frozen --no-progress ruff check
    "$uv_bin" run --frozen --no-progress pytest -q
  )
done

echo "全部插件检查通过（${#manifests[@]} 个）"
