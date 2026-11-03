# MetaTube

参照 [jellyfin-plugin-metatube](https://github.com/metatube-community/jellyfin-plugin-metatube) 实现的 Iris 元数据插件：向你自己部署的 [MetaTube 服务器](https://github.com/metatube-community/metatube-sdk-go) 搜索并取回番号类影片的资料、演员头像和图片。

- id：`metatube`
- 提供：`metadata.search`、`metadata.details`、`metadata.images`、`metadata.people`、`admin.ui`
- 申请宿主能力：`logger`。请求 MetaTube 服务器用 SDK 的直连 HTTP（遵循插件代理设置），不用宿主 `http` 能力——后者拒绝内网地址，而 MetaTube 服务器通常部署在内网。

## 使用

1. 在「插件 › MetaTube › 设置」填写服务器地址（和令牌，服务器未设置令牌时留空），点「测试连接」。
2. 在资料库的元数据下载器里选用 MetaTube。搜索框可以直接填番号，也可以粘贴详情页地址（服务器支持按地址取条目）。

## 设置项

与 Jellyfin/Emby 插件的设置页同名同义，分组也一致：

| 分组 | 设置 | 说明 |
| --- | --- | --- |
| 常规 | 服务器、令牌 | 影片、演员接口带 `Authorization: Bearer <令牌>`；图片和翻译接口不带 |
| 常规 | 启用导演、启用评分、启用真实演员名 | 评分为服务器评分 ×2（满分 10）；真实演员名只对 DUGA/FANZA/Getchu/MGS 的影片生效，到 AVBASE 查找，标题相似度 ≥ 80% 才采用 |
| 图片 | 封面图比例、默认图片质量 | 传给服务器的图片接口（`ratio`、`quality`），负数比例用服务器默认值 |
| 图片 | 启用角标、字幕 / 无码 / 无码字幕角标 | 默认关闭。按文件名标记选一个角标作为 `badge` 参数传给服务器，由服务器画在封面左上角；默认用服务器内置的 `zimu.png`（中文字幕）、`u.png`（无码破解）、`uc.png`（中文无码），也可以填 PNG 图片地址。只加在封面上 |
| 来源 | 启用影片来源过滤、影片来源过滤 | 逗号分隔、不区分大小写，只保留列出的来源，并按从左到右排序 |
| 模板 | 启用模板、标题模板、标语模板 | 默认标题 `{number} {title}`、标语 `配信開始日 {date}`；变量 `{provider} {id} {number} {title} {series} {maker} {label} {director} {actors} {first_actor} {year} {month} {date}` |
| 翻译 | 翻译模式、引擎、目标语言及各引擎的 Key | 引擎：百度、Google、Google（免费）、DeepL、OpenAI；串行调用服务器的 `/v1/translate`，失败重试 5 次，仍失败则保留原文 |
| 替换 | 标题 / 演员 / 类别替换表 | 每行 `原文=目标`，目标留空表示删除；标题按子串替换，演员和类别整项匹配（不区分大小写） |

翻译引擎的 Key 和接口地址会作为查询参数随请求发给你配置的 MetaTube 服务器（服务器协议如此，与 Jellyfin/Emby 插件一致），请只连接自己信任的服务器，并尽量使用 HTTPS。

处理顺序：真实演员名 → 标题/演员/类别替换 → 翻译 → 去重 → 套用模板。

文件名里番号后的 `-C`、`-U`、`-UC`、`-LTX` 等标记在搜索前去掉，并记在条目 ID 末尾（如 `FANZA:abc00123:C:LTX`），因为取详情时只拿得到条目 ID：

- `-C` 记为 `C`（字幕），`-U` 记为 `U`（无码），`-UC` 两者都记，`-LTX` 记为 `LTX`。
- 带 `LTX` 的详情里多一个「LTX 破解」类别；类别替换表不作用于它。
- 角标：同时有字幕和无码（`U` 或 `LTX`）用无码字幕角标，否则只有无码用无码角标，只有字幕用字幕角标。服务器一张图只能画一个角标。
- 已经匹配过的条目要重新识别才会带上标记。

## 与 Jellyfin/Emby 插件的差异

Iris 的插件接口按「元数据来源」设计，下列功能没有对应能力，未实现：

- 自动合集（按系列）：宿主只对 TMDB 系列建合集；系列、片商、厂牌也不会写成标签。
- 预告片（strm）、「中文字幕」类别：依赖媒体库里的文件名和文件操作的计划任务。
- 自动更新插件：由 Iris 的插件仓库升级负责。

另有两处按 Iris 接口调整：

- 元数据接口没有语言参数，所以翻译的目标语言单独设置（默认 `zh-CN`，不能是日语）。
- 日期无效（服务器给出 `0001-01-01`）时，默认标语不输出，而不是显示「配信開始日 0001-01-01」。

## 开发

```bash
uv sync --frozen
uv run ruff check
uv run pytest -q
```

测试用 `httpx2.MockTransport` 模拟服务器，另有真实子进程握手。
