"""MetaTube provider：搜索、详情、图片和演员资料。

流程照搬 jellyfin-plugin-metatube 的 MovieProvider / ActorProvider：详情依次做真实演员名、
标题/演员/类别替换、翻译、去重，再按模板生成标题和标语；演员头像通过演员搜索补上。
Jellyfin 的标签、合集和预告片在 Iris 的元数据里没有对应字段，不输出。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any
from urllib.parse import quote, unquote

from iris_plugin_sdk import (
    MetadataCandidate,
    MetadataCredit,
    MetadataError,
    MetadataKind,
    MetadataNotFound,
    MetadataPerson,
    MetadataRecord,
    MetadataSearchRequest,
    MetadataSeason,
)

from iris_plugin_metatube.client import MetaTubeClient
from iris_plugin_metatube.settings import Config
from iris_plugin_metatube.similarity import title_similarity
from iris_plugin_metatube.translation import Translator

CONTENT_RATING = "JP-18+"
AVBASE = "AVBASE"
GFRIENDS = "Gfriends"
# 只有这些来源的影片能到 AVBASE 查真实演员名
AVBASE_SUPPORTED = frozenset({"duga", "fanza", "getchu", "mgs"})
SIMILARITY_THRESHOLD = 0.8
DIRECTOR_PREFIX = "director:"
NAME_PREFIX = "name:"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
# 文件名里跟在番号后的标记：字幕（-C）、无码（-U、-UC）、4K、泄漏，以及没去掉的扩展名
_NUMBER_MARKS = re.compile(
    r"(?:(?<=\d)[-_. ]+(?:uc|cu|u|c|4k|leak|uncensored)|[. ]+(?:mp4|mkv|avi|wmv|ts|iso))$",
    re.IGNORECASE,
)
_NOT_ALNUM = re.compile(r"[^0-9a-z]+")


class MetaTubeProvider:
    def __init__(
        self,
        client: MetaTubeClient,
        config: Callable[[], Config],
        plugin_id: str,
        logger: Any,
        translator: Translator,
    ) -> None:
        self.id = plugin_id
        self._client = client
        self._config = config
        self._logger = logger
        self._translator = translator

    # ---- 宿主协议 ----

    def unavailable_reason(self) -> str | None:
        if not self._config().server:
            return "请先在插件设置里填写 MetaTube 服务器地址"
        return None

    def search(self, request: MetadataSearchRequest) -> list[MetadataCandidate]:
        if request.kind != "movie":
            return []
        cfg = self._config()
        query = _strip_number_marks(request.title)
        results = self._client.search_movies(cfg, query)
        results = _apply_provider_filter(results, cfg.provider_filter)
        # 同一个番号会从多个来源各返回一条。宿主要求能确定唯一的一个才自动匹配，所以番号
        # 完全一致的结果只留排在最前面的来源，并用查询串作原名，让宿主按「原名与文件名一致」认出它
        key = _number_key(query)
        exact = [r for r in results if key and _number_key(_str(r, "number")) == key]
        if exact:
            results = exact[:1]
        candidates = []
        for item in results:
            provider, movie_id = _str(item, "provider"), _str(item, "id")
            if not provider or not movie_id:
                continue
            number = _str(item, "number")
            parts = (f"[{provider}]", number, _str(item, "title"))
            title = " ".join(part for part in parts if part)
            release = _valid_date(_str(item, "release_date"))
            candidates.append(
                MetadataCandidate(
                    provider_id=self.id,
                    remote_id=make_remote_id(provider, movie_id),
                    title=title,
                    # 没有精确命中时用番号作原名，宿主才能拿它和文件名比相似度
                    original_title=request.title if exact else number or None,
                    year=int(release[:4]) if release else None,
                    kind="movie",
                )
            )
        return candidates

    def find(self, kind: MetadataKind, scheme: str, value: str) -> str | None:
        # MetaTube 的条目没有 TMDB/IMDb 对应关系
        return None

    def details(self, remote_id: str, *, kind: MetadataKind) -> MetadataRecord:
        if kind != "movie":
            raise MetadataNotFound("MetaTube 只提供影片资料")
        cfg = self._config()
        provider, movie_id = parse_remote_id(remote_id)
        info = self._client.movie(cfg, provider, movie_id)
        number, original_title = _str(info, "number"), _str(info, "title")
        title, summary = original_title, _str(info, "summary")
        actors = _strings(info, "actors")
        genres = _strings(info, "genres")

        if cfg.enable_real_actor_names:
            actors = self._real_actor_names(cfg, info, actors)
        if cfg.title_table is not None:
            title = cfg.title_table.substitute_text(title)
        if cfg.actor_table is not None:
            actors = cfg.actor_table.substitute_items(actors)
        if cfg.genre_table is not None:
            genres = cfg.genre_table.substitute_items(genres)
        title, summary = self._translator.translate_movie(cfg, title, summary)
        actors = _distinct(actors)
        genres = _distinct(genres)
        previews = _distinct(_strings(info, "preview_images"))

        release = _valid_date(_str(info, "release_date"))
        variables = {
            "provider": provider,
            "id": movie_id,
            "number": number,
            "title": title,
            "series": _str(info, "series"),
            "maker": _str(info, "maker"),
            "label": _str(info, "label"),
            "director": _str(info, "director"),
            "actors": " ".join(actors),
            "first_actor": actors[0] if actors else "",
            "year": release[:4] if release else "",
            "month": release[5:7] if release else "",
            "date": release or "",
        }
        name = _render(cfg.name_template, variables) or " ".join(
            part for part in (number, title) if part
        )
        tagline = _render(cfg.tagline_template, variables)
        if cfg.default_tagline and release is None:
            tagline = ""

        score = _float(info.get("score"))
        maker, director = _str(info, "maker"), _str(info, "director")
        directors = (
            (MetadataCredit(remote_id=DIRECTOR_PREFIX + quote(director, safe=""), name=director),)
            if cfg.enable_directors and director
            else ()
        )
        image = self._client.image_source
        return MetadataRecord(
            provider_id=self.id,
            remote_id=make_remote_id(provider, movie_id),
            title=name,
            kind="movie",
            original_title=original_title or None,
            overview=summary or None,
            year=int(release[:4]) if release else None,
            release_date=release,
            rating=round(score * 2, 1) if cfg.enable_ratings and score > 0 else None,
            tagline=tagline or None,
            genres=tuple(genres),
            studios=(maker,) if maker else (),
            content_rating=CONTENT_RATING,
            poster=image("primary", provider, movie_id, cfg),
            backdrop=image("backdrop", provider, movie_id, cfg, ratio=-1),
            thumb=image("thumb", provider, movie_id, cfg, ratio=-1),
            artwork={
                "poster": (
                    image("primary", provider, movie_id, cfg),
                    *(image("primary", provider, movie_id, cfg, url=url) for url in previews),
                ),
                "backdrop": (
                    image("backdrop", provider, movie_id, cfg, ratio=-1),
                    *(
                        image("backdrop", provider, movie_id, cfg, url=url, ratio=-1)
                        for url in previews
                    ),
                ),
                "thumb": (
                    image("thumb", provider, movie_id, cfg, ratio=-1),
                    *(
                        image("thumb", provider, movie_id, cfg, url=url, ratio=-1)
                        for url in previews
                    ),
                ),
            },
            cast=tuple(self._actor_credit(cfg, actor) for actor in actors),
            directors=directors,
            external_ids={"metatube": make_remote_id(provider, movie_id)},
        )

    def season(self, remote_id: str, number: int) -> MetadataSeason:
        raise MetadataNotFound("MetaTube 只提供影片资料")

    def page_url(self, kind: MetadataKind, remote_id: str) -> str | None:
        server = self._config().server
        if kind != "movie" or not server:
            return None
        return f"{server}?redirect={quote(remote_id, safe=':%')}"

    def image(self, source: str, width: int) -> bytes:
        return self._client.image(self._config(), source)

    def person(self, remote_id: str) -> MetadataPerson:
        cfg = self._config()
        if remote_id.startswith(DIRECTOR_PREFIX):
            raise MetadataNotFound("导演没有人物资料")
        if remote_id.startswith(NAME_PREFIX):
            name = unquote(remote_id[len(NAME_PREFIX) :])
            results = self._client.search_actors(cfg, name)
            if not results:
                raise MetadataNotFound("MetaTube 上没有这位演员")
            provider, actor_id = _str(results[0], "provider"), _str(results[0], "id")
            if not provider or not actor_id:
                raise MetadataNotFound("MetaTube 上没有这位演员")
        else:
            provider, actor_id = parse_remote_id(remote_id)
        info = self._client.actor(cfg, provider, actor_id)
        return MetadataPerson(
            remote_id=remote_id,
            name=_str(info, "name"),
            biography=_actor_overview(info) or None,
            birthday=_valid_date(_str(info, "birthday")),
            place_of_birth=_str(info, "nationality") or None,
        )

    # ---- 设置页 ----

    def test_connection(self, values: Mapping[str, Any]) -> str | None:
        cfg = Config.from_values(values)
        if not cfg.server:
            return "请填写服务器地址"
        try:
            self._client.check(cfg)
        except MetadataError as exc:
            return exc.message
        return None

    # ---- 内部 ----

    def _real_actor_names(self, cfg: Config, info: dict[str, Any], actors: list[str]) -> list[str]:
        if _str(info, "provider").casefold() not in AVBASE_SUPPORTED:
            return actors
        movie_id = _str(info, "id")
        try:
            results = self._client.search_movies(cfg, movie_id, AVBASE)
        except MetadataError as exc:
            self._logger.warning("转换真实演员名失败：%s（%s）", _str(info, "number"), exc.message)
            return actors
        for result in results:
            similarity = title_similarity(
                (_str(info, "number"), _str(info, "title")),
                (_str(result, "number"), _str(result, "title")),
            )
            if similarity >= SIMILARITY_THRESHOLD:
                return _strings(result, "actors") or actors
        self._logger.warning("AVBASE 上没有找到匹配的影片：%s", movie_id)
        return actors

    def _actor_credit(self, cfg: Config, name: str) -> MetadataCredit:
        fallback = MetadataCredit(remote_id=NAME_PREFIX + quote(name, safe=""), name=name)
        try:
            results = self._client.search_actors(cfg, name)
        except MetadataError as exc:
            self._logger.warning("获取演员头像失败：%s（%s）", name, exc.message)
            return fallback
        if not results:
            self._logger.warning("没有找到演员：%s", name)
            return fallback
        first = results[0]
        provider, actor_id = _str(first, "provider"), _str(first, "id")
        if not provider or not actor_id:
            return fallback
        profile = _actor_image(self._client, cfg, first)
        # 有 Gfriends 的头像时优先使用，多条时以最后一条为准
        for result in results:
            if _str(result, "provider") == GFRIENDS:
                profile = _actor_image(self._client, cfg, result) or profile
        return MetadataCredit(
            remote_id=make_remote_id(provider, actor_id), name=name, profile=profile
        )


def make_remote_id(provider: str, remote_id: str) -> str:
    return f"{provider}:{quote(remote_id, safe='')}"


def parse_remote_id(value: str) -> tuple[str, str]:
    provider, separator, rest = value.partition(":")
    if not separator or not provider or not rest:
        raise MetadataNotFound("MetaTube 条目 ID 不正确")
    return provider, unquote(rest)


def _actor_image(client: MetaTubeClient, cfg: Config, result: dict[str, Any]) -> str | None:
    images = _strings(result, "images")
    if not images:
        return None
    return client.image_source(
        "primary",
        _str(result, "provider"),
        _str(result, "id"),
        cfg,
        url=images[0],
        position=0.5,
        auto=True,
    )


def _strip_number_marks(text: str) -> str:
    text = text.strip()
    while (stripped := _NUMBER_MARKS.sub("", text)) != text:
        text = stripped
    return text


def _number_key(text: str) -> str:
    """比较番号用：忽略大小写、连字符和空格。"""
    return _NOT_ALNUM.sub("", text.lower())


def _apply_provider_filter(
    results: list[dict[str, Any]], names: tuple[str, ...] | None
) -> list[dict[str, Any]]:
    if not names:
        return results
    order = {name.casefold(): index for index, name in enumerate(names)}
    kept = [item for item in results if _str(item, "provider").casefold() in order]
    # sorted 是稳定排序，同一来源内保持服务器给出的顺序
    return sorted(kept, key=lambda item: order[_str(item, "provider").casefold()])


def _render(template: str, variables: Mapping[str, str]) -> str:
    return _PLACEHOLDER.sub(
        lambda match: variables.get(match.group(1), match.group(0)), template
    ).strip()


def _actor_overview(info: dict[str, Any]) -> str:
    aliases = _distinct(
        alias
        for alias in _strings(info, "aliases")
        if alias.casefold() != _str(info, "name").casefold()
    )
    height = info.get("height")
    blood = _str(info, "blood_type")
    debut = _valid_date(_str(info, "debut_date"))
    rows = (
        ("別名", ", ".join(aliases)),
        ("3サイズ", _str(info, "measurements")),
        ("カップサイズ", _str(info, "cup_size")),
        ("身長", f"{height}cm" if isinstance(height, (int, float)) and height > 0 else ""),
        ("血液型", f"{blood}型" if blood else ""),
        ("デビュー", f"{int(debut[:4])}年{int(debut[5:7])}月{int(debut[8:10])}日" if debut else ""),
    )
    return "\n".join(f"{label}: {value}" for label, value in rows if value.strip())


def _valid_date(value: str) -> str | None:
    """服务器的日期形如 2020-01-02T00:00:00Z；零值（0001-01-01）视为没有。"""
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return None
    return parsed.isoformat() if parsed.year > 1 else None


def _str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    return value.strip() if isinstance(value, str) else ""


def _strings(data: Mapping[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _distinct(items: Any) -> list[str]:
    return list(dict.fromkeys(item for item in items if item.strip()))


def _float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)
