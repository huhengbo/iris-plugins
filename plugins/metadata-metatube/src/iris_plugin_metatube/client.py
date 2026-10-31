"""MetaTube 服务器 API 客户端。

响应统一是 ``{"data": ..., "error": {"code", "message"}}``；影片和演员接口需要令牌，图片和
翻译接口是公开的（与 jellyfin-plugin-metatube 的 ApiClient 一致）。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx2
from iris_plugin_sdk import (
    MetadataNotFound,
    MetadataUnavailable,
    PluginHttpClient,
    PluginHttpResponse,
)

from iris_plugin_metatube.settings import Config

IMAGE_PREFIX = "/v1/images/"
TIMEOUT_SECONDS = 60.0


class MetaTubeClient:
    def __init__(self, http: PluginHttpClient, user_agent: str) -> None:
        self._http = http
        self._user_agent = user_agent

    # ---- 影片和演员 ----

    def search_movies(self, cfg: Config, q: str, provider: str = "") -> list[dict[str, Any]]:
        return self._list(cfg, "/v1/movies/search", {"q": q, "provider": provider})

    def search_actors(self, cfg: Config, q: str, provider: str = "") -> list[dict[str, Any]]:
        return self._list(cfg, "/v1/actors/search", {"q": q, "provider": provider})

    def movie(self, cfg: Config, provider: str, remote_id: str) -> dict[str, Any]:
        return self._object(cfg, f"/v1/movies/{_segment(provider)}/{_segment(remote_id)}")

    def actor(self, cfg: Config, provider: str, remote_id: str) -> dict[str, Any]:
        return self._object(cfg, f"/v1/actors/{_segment(provider)}/{_segment(remote_id)}")

    def translate(self, cfg: Config, text: str, target: str) -> str:
        translation = cfg.translation
        params = {
            "q": text,
            "from": "auto",
            "to": target,
            "engine": translation.engine,
            **translation.params,
        }
        data = self._get(cfg, "/v1/translate", params, auth=False)
        translated = data.get("translated_text") if isinstance(data, dict) else None
        if not isinstance(translated, str):
            raise MetadataUnavailable("MetaTube 服务器没有返回翻译结果")
        return translated

    # ---- 连接检查 ----

    def check(self, cfg: Config) -> None:
        """先确认服务器可达，再用需要令牌的接口确认令牌有效。"""
        self._get(cfg, "/", {}, auth=False)
        self._get(cfg, "/v1/db/version", {})

    # ---- 图片 ----

    @staticmethod
    def image_source(
        kind: str,
        provider: str,
        remote_id: str,
        cfg: Config,
        *,
        url: str = "",
        position: float = -1,
        auto: bool = False,
        ratio: float | None = None,
    ) -> str:
        """图片来源：相对服务器根的路径和查询，下载时再拼上当前配置的服务器地址。"""
        params = {
            "ratio": repr(cfg.primary_image_ratio if ratio is None else ratio),
            "pos": repr(position),
            "auto": "true" if auto else "false",
            "quality": str(cfg.image_quality),
        }
        if url:
            params["url"] = url
        path = f"{IMAGE_PREFIX}{kind}/{_segment(provider)}/{_segment(remote_id)}"
        return f"{path}?{urlencode(params)}"

    def image(self, cfg: Config, source: str) -> bytes:
        parts = urlsplit(source)
        if parts.scheme or parts.netloc or not source.startswith(IMAGE_PREFIX):
            raise MetadataNotFound("不是 MetaTube 的图片来源")
        response = self._send(cfg, cfg.server + source, {}, auth=False)
        if response.status_code == 404:
            raise MetadataNotFound("MetaTube 上没有这张图片")
        if response.status_code >= 400:
            raise MetadataUnavailable(f"MetaTube 图片请求失败（HTTP {response.status_code}）")
        return response.content

    # ---- 内部 ----

    def _list(self, cfg: Config, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
        data = self._get(cfg, path, {**params, "fallback": "true"})
        if data is None:
            return []
        if not isinstance(data, list):
            raise MetadataUnavailable("MetaTube 服务器返回的内容无法解析")
        return [item for item in data if isinstance(item, dict)]

    def _object(self, cfg: Config, path: str) -> dict[str, Any]:
        data = self._get(cfg, path, {"lazy": "true"})
        if not isinstance(data, dict):
            raise MetadataUnavailable("MetaTube 服务器返回的内容无法解析")
        return data

    def _get(self, cfg: Config, path: str, params: dict[str, str], *, auth: bool = True) -> Any:
        response = self._send(cfg, cfg.server + path, params, auth=auth)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code >= 400:
            raise _http_error(response.status_code, payload)
        if not isinstance(payload, dict):
            raise MetadataUnavailable("MetaTube 服务器返回的内容无法解析")
        return payload.get("data")

    def _send(
        self, cfg: Config, url: str, params: dict[str, str], *, auth: bool
    ) -> PluginHttpResponse:
        if not cfg.server:
            raise MetadataUnavailable("请先在插件设置里填写 MetaTube 服务器地址")
        headers = {"Accept": "application/json", "User-Agent": self._user_agent}
        if auth and cfg.token:
            headers["Authorization"] = f"Bearer {cfg.token}"
        try:
            # 空的 params 会冲掉 url 自带的查询串（图片来源就是带查询串的完整路径）
            if params:
                return self._http.get(url, params=params, headers=headers)
            return self._http.get(url, headers=headers)
        except httpx2.ProxyError as exc:
            raise MetadataUnavailable("代理不可用，请检查代理地址") from exc
        except httpx2.TimeoutException as exc:
            raise MetadataUnavailable("连接 MetaTube 服务器超时") from exc
        except httpx2.RequestError as exc:
            raise MetadataUnavailable("连不上 MetaTube 服务器，请检查服务器地址") from exc


def _segment(value: str) -> str:
    return quote(value, safe="")


def _http_error(status: int, payload: Any) -> Exception:
    message = ""
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        raw = payload["error"].get("message")
        message = raw if isinstance(raw, str) else ""
    if status == 404:
        return MetadataNotFound(message or "MetaTube 上没有这个条目")
    if status in (401, 403):
        return MetadataUnavailable("MetaTube 服务器拒绝了访问，请检查插件设置里的令牌")
    if status == 429:
        return MetadataUnavailable("MetaTube 服务器请求过于频繁，请稍后再试")
    detail = f"：{message}" if message else ""
    return MetadataUnavailable(f"MetaTube 服务器返回错误（HTTP {status}）{detail}")
