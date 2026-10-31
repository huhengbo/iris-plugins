# iris-plugins

Iris 官方插件仓库的脚手架。宿主按 ADR 0029（`iris` 仓库的 `docs/adr/0029-plugin-repositories.md`）从本仓库的 `index.json` 浏览、安装和升级插件；插件包放在 GitHub Release，索引部署到 GitHub Pages。

当前仓库只有一个仅用于端到端验证的示例插件 `example.hello`，**尚未正式发布**。系统插件（`builtin.*`）仍随 Iris 镜像发布，不在本仓库中。

## 目录结构

```
.
├── LICENSE                         Apache-2.0
├── README.md
├── schema/
│   └── index.v1.schema.json        index.json（schema 1）的 JSON Schema
├── scripts/
│   ├── build_packages.py           校验并生成确定性 zip
│   ├── build_index.py              根据 zip 生成 index.json
│   ├── validate_index.py           用 JSON Schema 校验 index.json
│   └── check.sh                    每个插件：uv sync --frozen + ruff + pytest
├── plugins/
│   └── example-hello/
│       ├── plugin.json
│       ├── pyproject.toml
│       ├── uv.lock                 必须是纯 registry 源
│       ├── README.md
│       ├── src/iris_plugin_example_hello/
│       ├── ui/index.html
│       └── tests/
└── .github/workflows/
    ├── ci.yml                      pull_request：检查、构建、schema 校验
    └── release.yml                 push main：Release、索引、Pages
```

`dist/`、`site/`、`.venv/` 和缓存目录由 `.gitignore` 忽略，不要提交。

## 插件目录规范

每个插件是 `plugins/<目录名>/` 下的一个独立 Python 项目：

- `plugin.json`：唯一的静态清单。字段由 `iris_plugin_sdk.load_manifest` 校验，未知字段会被拒绝。
- `pyproject.toml`：普通 Python 项目；依赖 `iris-plugin-sdk>=1.0,<2`，**不要**写 `[tool.uv.sources]`。
- `uv.lock`：必须由 `uv lock` 生成，且只包含 registry（或 HTTPS url）源（允许项目自身的 `editable = "."`）。不能出现项目自身之外的 `git`、`path` 或其他 `editable` 源。
- `src/<包名>/`：插件代码；入口模块由 `plugin.json` 的 `entry` 指定。
- `ui/`：可选；声明 `admin.ui` 时必须有页面，且 `plugin.json` 的 `pages[].entry` 指向 `ui/` 内真实存在的文件。
- `tests/`：不进入发布包；握手测试建议使用 `iris_plugin_sdk.testing.RpcClient`。
- `README.md`、`LICENSE`：可选，会随包发布。

### id、版本和 SDK 范围

- `id` 必须匹配 `^[a-z0-9][a-z0-9._-]{0,63}$`，不能以保留前缀 `builtin.` 开头。
- `version` 必须匹配 `^[0-9]+(\.[0-9]+){0,3}$`，例如 `1.0.0`；同一 `(id, version)` 只能对应一份内容。
- `sdk` 必须是 SDK 能解析的比较式，例如 `>=1.0,<2.0`；不能使用 `~=` 或通配符。
- `provides` 至少一项；声明 `admin.ui` 时必须同时声明 `ui` 和 `pages`，反之亦然。
- `capabilities` 目前可申请 `logger` 和 `http`；示例只申请 `logger`。

### 压缩包内容

`build_packages.py` 只把以下白名单放进 zip 根目录（不套一层 `<id>/`）：

```
plugin.json  pyproject.toml  uv.lock  src/...  ui/...  README.md  LICENSE
```

不会包含 `.venv/`、`tests/`、`__pycache__/`、`*.egg-info/`、`uv.toml`、符号链接、缓存或本机文件。zip 条目按路径排序，mtime 固定为 1980-01-01，文件权限固定为 `0644`，因此相同输入连续构建的 sha256 相同。

## 如何新增插件

1. 复制 `plugins/example-hello` 为 `plugins/<新目录名>`。
2. 修改 `plugin.json` 的 `id`、`name`、`version`、`description`、`entry`，以及需要的能力；同步修改 `pyproject.toml` 的 `project.name`、`project.version` 和 Python 包名。
3. 在 `src/` 下实现插件入口（通常继承/实现 `Plugin`，提供 `start`、`stop`、`providers`）；需要页面时修改 `ui/`。
4. 在插件目录重新生成锁文件：

   ```bash
   cd plugins/<新目录名>
   uv lock
   uv sync --frozen
   ```

5. 补测试，至少覆盖 manifest 和真实子进程握手：

   ```bash
   uv run --frozen pytest -q
   ```

6. 回到仓库根目录跑完整检查：

   ```bash
   bash scripts/check.sh
   ```

7. 构建并本地校验索引（见下一节），然后提交 PR。CI 会重复检查并验证 schema。

## 版本不可变规则

发布由 `.github/workflows/release.yml` 在 push 到 `main` 时执行，每个插件对应一个 tag：

```
<id>-v<version>        例如 example.hello-v1.0.0
```

- tag 不存在：创建 GitHub Release，上传 `dist/<id>-<version>.zip`。
- tag 已存在：下载已发布资产，解压后与本次源码构建结果比较。
  - 内容相同：允许重跑，继续用已发布资产生成索引。
  - 内容不同：**失败**。必须提升 `plugin.json` 和 `pyproject.toml` 的版本，不能复用旧版本号。
- 不要手工移动或删除已发布的 tag，也不要手工替换 Release 资产；索引的 sha256 来自实际发布资产。
- 宿主按 `(id, version)` 识别包；索引允许同一 id 有多个版本，但当前 CI 只发布每个插件的最新版本。
- 已安装的插件 id 全局唯一；`builtin.` 前缀保留给系统插件，仓库插件使用该前缀会被拒绝。

## 本地构建与验证

前置条件：Python 3.13+、[uv](https://docs.astral.sh/uv/)。`build_packages.py` 使用 PEP 723 内联依赖，`uv run` 会自动准备包含 `iris-plugin-sdk` 的临时环境。

### 1. 检查所有插件

```bash
bash scripts/check.sh
```

等价于对每个插件执行 `uv sync --frozen`、`uv run ruff check`、`uv run pytest`。

### 2. 构建确定性 zip

```bash
rm -rf dist
uv run scripts/build_packages.py --out dist
```

连续构建两次并比较 sha256：

```bash
shasum -a 256 dist/*.zip | sort > /tmp/iris-plugins-first.sha256
uv run scripts/build_packages.py --out dist
shasum -a 256 dist/*.zip | sort > /tmp/iris-plugins-second.sha256
diff -u /tmp/iris-plugins-first.sha256 /tmp/iris-plugins-second.sha256
```

`diff` 无输出即一致。

### 3. 生成并校验 index.json

本地静态服务器场景：

```bash
uv run scripts/build_index.py \
  --dist dist \
  --base-url http://127.0.0.1:8765/ \
  --out dist/index.json
```

用仓库内的 JSON Schema 校验：

```bash
uv run --with jsonschema python scripts/validate_index.py dist/index.json
```

`--base-url` 也可以是相对前缀；CI 用 `--base-url ""` 生成相对文件名。发布到 Release 时用：

```bash
uv run scripts/build_index.py \
  --dist dist \
  --release-repo huhengbo/iris-plugins \
  --out site/index.json
```

### 4. 本地浏览

```bash
python3 -m http.server 8765 --directory dist
```

然后访问 `http://127.0.0.1:8765/index.json`。宿主添加仓库时填这个地址即可。

### 5. 检查 zip 内容和 SDK 加载

```bash
unzip -l dist/example.hello-1.0.0.zip

tmp="$(mktemp -d)"
unzip -q dist/example.hello-1.0.0.zip -d "$tmp"
uv run --with 'iris-plugin-sdk>=1.0,<2' python - "$tmp" <<'PY'
import sys
from pathlib import Path
from iris_plugin_sdk import load_manifest

manifest = load_manifest(Path(sys.argv[1]))
print(manifest.id, manifest.version, manifest.provides)
PY
rm -rf "$tmp"
```

检查 zip 内 `uv.lock` 的源（项目自身 `editable = "."` 是 `uv.lock` 的正常表示，允许；其他 path/git/editable 源不允许）：

```bash
unzip -p dist/example.hello-1.0.0.zip uv.lock | python3 -c '
import sys, tomllib

packages = tomllib.loads(sys.stdin.read()).get("package", [])
bad = []
for package in packages:
    source = package.get("source", {})
    if "git" in source or "path" in source:
        bad.append((package.get("name"), source))
    elif "editable" in source and source["editable"] != ".":
        bad.append((package.get("name"), source))
if bad:
    print("非法源：", bad)
    raise SystemExit(1)
print("OK：uv.lock 不含 git/path/editable 源（项目自身 editable = \".\" 除外）")
'
```

### 6. 校验 workflow YAML

```bash
uv run --with pyyaml python - <<'PY'
import pathlib
import yaml

for path in sorted(pathlib.Path(".github/workflows").glob("*.yml")):
    yaml.safe_load(path.read_text(encoding="utf-8"))
    print(f"OK: {path}")
PY
```

如果本机装了 `actionlint`，再依次运行：

```bash
actionlint .github/workflows/ci.yml
actionlint .github/workflows/release.yml
```

## index.json（schema 1）

```json
{
  "schema": 1,
  "name": "Iris 官方插件仓库",
  "generated_at": "2026-10-31T00:00:00Z",
  "plugins": [
    {
      "id": "example.hello",
      "name": "示例插件",
      "description": "端到端验证用",
      "version": "1.0.0",
      "sdk": ">=1.0,<2.0",
      "provides": ["admin.ui"],
      "capabilities": ["logger"],
      "url": "https://github.com/huhengbo/iris-plugins/releases/download/example.hello-v1.0.0/example.hello-1.0.0.zip",
      "sha256": "<64 位小写十六进制>",
      "size": 12345,
      "homepage": "https://github.com/huhengbo/iris-plugins/tree/main/plugins/example-hello",
      "signature": null
    }
  ]
}
```

约定（与宿主解析规则一致）：

- `schema` 不是 `1` 时，宿主把仓库标记为 `unsupported`，不展示条目。
- 顶层和条目的未知字段一律忽略，便于向前兼容。
- `id` 匹配 `^[a-z0-9][a-z0-9._-]{0,63}$`，且不以 `builtin.` 开头；`version` 匹配 `^[0-9]+(\.[0-9]+){0,3}$`。
- `sdk` 必须能被 SDK 解析；`provides` 非空。
- `url` 可以是绝对地址，也可以是相对 `index.json` 的地址；宿主用 `urljoin` 解析，并执行 HTTPS 规则（本机 `localhost` 除外）。
- `sha256` 为 64 位小写十六进制；`size` 是实际 zip 字节数且不超过 50 MiB。
- `signature` 是预留字段，本次只透传，不做签名校验。
- `(id, version)` 唯一；索引最多 2 MiB、1000 个条目。
- 生成器 `build_index.py` 从实际 zip 读取 `sha256` 和 `size`，不信任其他来源。

## 把仓库添加到 Iris

发布后，Pages 上的索引地址形如：

```
https://huhengbo.github.io/iris-plugins/index.json
```

两种方式：

1. **管理员界面**：插件页 →「目录」→「添加仓库」，填入索引地址。添加非官方仓库时宿主会弹出风险确认；安装前会展示插件声明的 `provides` 和 `capabilities`。
2. **默认仓库环境变量**：`APP_DEFAULT_PLUGIN_REPOS` 接受逗号分隔的 `index.json` 地址，去空白、去重。每个地址必须是 HTTPS（本机 `localhost` 除外）。设为空字符串表示没有默认仓库；未设置时使用宿主内置的官方仓库地址。

本地开发时把地址换成：

```
http://127.0.0.1:8765/index.json
```

宿主只依赖索引和 zip，不依赖 git；安装时校验索引里的 sha256，然后用 `uv` 按插件自带的 `uv.lock` 安装依赖。因此：

- 插件依赖必须能从 PyPI 或配置的镜像获取；不要使用 git 依赖（运行时镜像没有 git）。
- `uv.lock` 不能包含项目自身之外的 path/editable/git 源；`build_packages.py` 会拒绝这样的包。
- 索引里的 SDK 范围不匹配时，宿主显示为不兼容、不可安装；`builtin.*` 冲突会被忽略。

## CI 与发布

### `ci.yml`（pull_request / 手动触发）

1. `scripts/check.sh`：每个插件 `uv sync --frozen`、ruff、pytest。
2. `build_packages.py`：构建一次，再构建一次并比较 sha256，防止不可复现的包。
3. `build_index.py --base-url ""`：生成相对 URL 的索引。
4. `validate_index.py`：用 `schema/index.v1.schema.json` 校验。
5. 上传 `dist/` 作为构建产物。

### `release.yml`（push main / 手动触发）

1. 检查、构建所有插件。
2. 对每个 zip 计算 tag `<id>-v<version>`：
   - 不存在：`gh release create` 并上传 zip；
   - 已存在：下载资产，解压后 `diff -r` 比较内容；内容变了但版本没变则失败。
3. 从**已发布资产**重新生成 `site/index.json`（sha256/size 取自已发布文件），并用 schema 校验。
4. 生成一个极简 Pages 落地页，`actions/upload-pages-artifact` + `actions/deploy-pages` 部署。

权限：`contents: write`、`pages: write`、`id-token: write`。仓库需要在 GitHub 设置里启用 Pages（Build and deployment → GitHub Actions），本仓库的 workflow 不会自动开启 Pages。

> 当前脚手架只写了 workflow 文件，没有触发、推送、创建 Release 或开启 Pages。

## 安全边界

- 宿主用索引里的 sha256 校验下载的 zip；sha256 只能发现传输中的篡改，不能防止仓库本身被污染。
- 本次不做签名校验（`signature` 为 `null`），也不做沙箱；插件仍是管理员信任的代码，可读写自己的 state。
- 仓库地址和下载地址一律 HTTPS（本机开发可用 `localhost`）。
- `builtin.` 前缀保留；仓库插件不得覆盖、升级或卸载系统插件。

## License

Apache-2.0，见 [LICENSE](LICENSE)。
