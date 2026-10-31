"""设置页字段和运行时配置。

字段与 jellyfin-plugin-metatube 的 PluginConfiguration 一一对应；Iris 的元数据接口没有语言参数，
所以额外增加了翻译目标语言。徽章、预告片、合集和计划任务依赖 Jellyfin/Emby 的媒体库对象，
Iris 的插件接口没有对应能力，不提供。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from iris_plugin_sdk import SettingField, SettingsEndpoint, SettingsStore

from iris_plugin_metatube.substitution import SubstitutionTable

DEFAULT_NAME_TEMPLATE = "{number} {title}"
DEFAULT_TAGLINE_TEMPLATE = "配信開始日 {date}"
DEFAULT_IMAGE_QUALITY = 90
DEFAULT_TRANSLATION_LANGUAGE = "zh-CN"

TRANSLATION_MODES = ("disabled", "title", "summary", "both")
# 值是 MetaTube 服务器 /v1/translate 的 engine 参数（服务端按名称不区分大小写匹配）
TRANSLATION_ENGINES = ("Baidu", "Google", "GoogleFree", "DeepL", "OpenAI")

TABLE_LIMIT = 20000


def metatube_settings(store: SettingsStore) -> SettingsEndpoint:
    return SettingsEndpoint(
        (
            SettingField(
                "server",
                "服务器",
                "url",
                help="MetaTube 服务器的完整地址，建议使用 HTTPS。",
                required=True,
                max_length=512,
            ),
            SettingField(
                "token",
                "令牌",
                "secret",
                help="MetaTube 服务器的访问令牌；服务器没有设置令牌时留空。",
                max_length=512,
            ),
            SettingField(
                "enable_directors",
                "启用导演",
                "bool",
                help="把导演写入影片资料。",
                default=True,
            ),
            SettingField(
                "enable_ratings",
                "启用评分",
                "bool",
                help="显示原站点的社区评分。",
                default=True,
            ),
            SettingField(
                "enable_real_actor_names",
                "启用真实演员名",
                "bool",
                help="从 AVBASE 查找并替换为真实的演员名。",
                default=False,
            ),
            SettingField(
                "primary_image_ratio",
                "封面图比例",
                "number",
                help="封面图的宽高比，填负数使用服务器默认值。",
                default=-1,
                min=-1,
                max=10,
            ),
            SettingField(
                "image_quality",
                "默认图片质量",
                "number",
                help="JPEG 图片的压缩质量，0 到 100，默认 90。",
                default=DEFAULT_IMAGE_QUALITY,
                min=0,
                max=100,
            ),
            SettingField(
                "enable_provider_filter",
                "启用影片来源过滤",
                "bool",
                help="过滤并重新排序影片来源的搜索结果。",
                default=False,
            ),
            SettingField(
                "provider_filter",
                "影片来源过滤",
                "text",
                help="来源名称不区分大小写，从左到右优先级递减，用英文逗号分隔。",
                max_length=512,
            ),
            SettingField(
                "enable_template",
                "启用模板",
                "bool",
                help="可用变量：{provider} {id} {number} {title} {series} {maker} {label}"
                " {director} {actors} {first_actor} {year} {month} {date}。",
                default=False,
            ),
            SettingField(
                "name_template",
                "标题模板",
                "text",
                default=DEFAULT_NAME_TEMPLATE,
                max_length=512,
            ),
            SettingField(
                "tagline_template",
                "标语模板",
                "text",
                default=DEFAULT_TAGLINE_TEMPLATE,
                max_length=512,
            ),
            SettingField(
                "translation_mode",
                "翻译模式",
                "select",
                help="翻译成目标语言的内容。",
                default="disabled",
                options=TRANSLATION_MODES,
            ),
            SettingField(
                "translation_engine",
                "翻译引擎",
                "select",
                default="Baidu",
                options=TRANSLATION_ENGINES,
            ),
            SettingField(
                "translation_language",
                "翻译目标语言",
                "text",
                help="翻译的目标语言代码，例如 zh-CN；不能是 ja。",
                default=DEFAULT_TRANSLATION_LANGUAGE,
                max_length=32,
            ),
            SettingField("baidu_app_id", "百度 App ID", "text", max_length=128),
            SettingField("baidu_app_key", "百度 App Key", "secret", max_length=256),
            SettingField("google_api_key", "Google API Key", "secret", max_length=256),
            SettingField(
                "google_api_url",
                "Google API 地址",
                "url",
                help="自定义的 Google 翻译接口地址（可选）。",
                max_length=512,
            ),
            SettingField("deepl_api_key", "DeepL API Key", "secret", max_length=256),
            SettingField(
                "deepl_api_url",
                "DeepL API 地址",
                "url",
                help="自定义的 DeepL 兼容接口地址（可选）。",
                max_length=512,
            ),
            SettingField("openai_api_key", "OpenAI API Key", "secret", max_length=256),
            SettingField(
                "openai_api_url",
                "OpenAI API 地址",
                "url",
                help="自定义的 OpenAI 兼容接口地址（可选）。",
                max_length=512,
            ),
            SettingField(
                "openai_model",
                "OpenAI 模型",
                "text",
                help="自定义的 OpenAI 兼容接口模型（可选）。",
                max_length=128,
            ),
            SettingField("enable_title_substitution", "启用标题替换", "bool", default=False),
            SettingField(
                "title_substitution_table",
                "标题替换表",
                "text",
                help="每行一条，用等号分隔；目标留空表示删除原字符串。",
                max_length=TABLE_LIMIT,
            ),
            SettingField("enable_actor_substitution", "启用演员替换", "bool", default=False),
            SettingField(
                "actor_substitution_table",
                "演员替换表",
                "text",
                help="每行一条，用等号分隔；目标留空表示删除该演员。",
                max_length=TABLE_LIMIT,
            ),
            SettingField("enable_genre_substitution", "启用类别替换", "bool", default=False),
            SettingField(
                "genre_substitution_table",
                "类别替换表",
                "text",
                help="每行一条，用等号分隔；目标留空表示删除该类别。",
                max_length=TABLE_LIMIT,
            ),
        ),
        store=store,
    )


@dataclass(frozen=True)
class TranslationConfig:
    mode: str
    engine: str
    language: str
    # 随请求发给服务器的引擎参数，键就是 /v1/translate 的查询参数名
    params: Mapping[str, str]


@dataclass(frozen=True)
class Config:
    server: str
    token: str
    enable_directors: bool
    enable_ratings: bool
    enable_real_actor_names: bool
    primary_image_ratio: float
    image_quality: int
    provider_filter: tuple[str, ...] | None
    name_template: str
    tagline_template: str
    # 没有启用模板时使用内置默认模板，调用方据此决定是否在日期无效时省略标语
    default_tagline: bool
    translation: TranslationConfig
    title_table: SubstitutionTable | None
    actor_table: SubstitutionTable | None
    genre_table: SubstitutionTable | None

    @classmethod
    def from_values(cls, values: Mapping[str, Any]) -> Config:
        template = _flag(values, "enable_template")
        provider_filter = None
        if _flag(values, "enable_provider_filter"):
            names = _provider_filter(_text(values, "provider_filter"))
            provider_filter = names or None
        return cls(
            server=_text(values, "server").rstrip("/"),
            token=_text(values, "token"),
            enable_directors=_flag(values, "enable_directors", True),
            enable_ratings=_flag(values, "enable_ratings", True),
            enable_real_actor_names=_flag(values, "enable_real_actor_names"),
            primary_image_ratio=float(_number(values, "primary_image_ratio", -1)),
            image_quality=int(_number(values, "image_quality", DEFAULT_IMAGE_QUALITY)),
            provider_filter=provider_filter,
            name_template=(
                _text(values, "name_template", DEFAULT_NAME_TEMPLATE)
                if template
                else DEFAULT_NAME_TEMPLATE
            ),
            tagline_template=(
                _text(values, "tagline_template", DEFAULT_TAGLINE_TEMPLATE)
                if template
                else DEFAULT_TAGLINE_TEMPLATE
            ),
            default_tagline=not template,
            translation=_translation(values),
            title_table=_table(values, "title"),
            actor_table=_table(values, "actor"),
            genre_table=_table(values, "genre"),
        )


def _text(values: Mapping[str, Any], name: str, default: str = "") -> str:
    value = values.get(name)
    return value.strip() if isinstance(value, str) else default


def _flag(values: Mapping[str, Any], name: str, default: bool = False) -> bool:
    value = values.get(name)
    return value if isinstance(value, bool) else default


def _number(values: Mapping[str, Any], name: str, default: float) -> float:
    value = values.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return value


def _provider_filter(raw: str) -> tuple[str, ...]:
    names: list[str] = []
    for part in raw.split(","):
        name = part.strip()
        if name and name.casefold() not in {item.casefold() for item in names}:
            names.append(name)
    return tuple(names)


def _table(values: Mapping[str, Any], kind: str) -> SubstitutionTable | None:
    if not _flag(values, f"enable_{kind}_substitution"):
        return None
    return SubstitutionTable.parse(_text(values, f"{kind}_substitution_table"))


def _translation(values: Mapping[str, Any]) -> TranslationConfig:
    mode = _text(values, "translation_mode", "disabled")
    engine = _text(values, "translation_engine", "Baidu")
    params: dict[str, str]
    match engine.casefold():
        case "baidu":
            params = {
                "baidu-app-id": _text(values, "baidu_app_id"),
                "baidu-app-key": _text(values, "baidu_app_key"),
            }
        case "google":
            params = {
                "google-api-key": _text(values, "google_api_key"),
                "google-api-url": _text(values, "google_api_url"),
            }
        case "deepl":
            params = {
                "deepl-api-key": _text(values, "deepl_api_key"),
                "deepl-api-url": _text(values, "deepl_api_url"),
            }
        case "openai":
            params = {
                "openai-api-key": _text(values, "openai_api_key"),
                "openai-api-url": _text(values, "openai_api_url"),
                "openai-model": _text(values, "openai_model"),
            }
        case _:
            params = {}
    return TranslationConfig(
        mode=mode,
        engine=engine,
        language=_text(values, "translation_language", DEFAULT_TRANSLATION_LANGUAGE),
        params=params,
    )
