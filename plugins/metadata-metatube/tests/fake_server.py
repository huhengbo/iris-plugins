"""用 httpx2.MockTransport 模拟 MetaTube 服务器。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx2
from iris_plugin_sdk import DirectHttpClient

from iris_plugin_metatube.client import MetaTubeClient
from iris_plugin_metatube.provider import MetaTubeProvider
from iris_plugin_metatube.settings import Config
from iris_plugin_metatube.translation import Translator

SERVER = "http://metatube.test"
TOKEN = "secret-token"

MOVIE = {
    "provider": "FANZA",
    "id": "ssis00001",
    "number": "SSIS-001",
    "title": "原題タイトル",
    "summary": "あらすじ",
    "director": "監督A",
    "actors": ["女優A", "女優B", "女優A", ""],
    "genres": ["単体作品", "巨乳", "単体作品"],
    "maker": "S1",
    "label": "S1 NO.1",
    "series": "系列X",
    "score": 4.25,
    "release_date": "2021-02-03T00:00:00Z",
    "preview_images": ["https://img.test/p1.jpg", "https://img.test/p2.jpg"],
}


class Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


def envelope(data: Any, status: int = 200) -> httpx2.Response:
    return httpx2.Response(status, json={"data": data})


def error(status: int, message: str) -> httpx2.Response:
    return httpx2.Response(status, json={"error": {"code": status, "message": message}})


def make_provider(
    handler: Callable[[httpx2.Request], httpx2.Response],
    values: dict[str, Any] | None = None,
    sleeps: list[float] | None = None,
) -> tuple[MetaTubeProvider, Recorder]:
    recorder = Recorder()

    def recording(request: httpx2.Request) -> httpx2.Response:
        recorder.requests.append(request)
        return handler(request)

    http = DirectHttpClient(None, transport=httpx2.MockTransport(recording))
    client = MetaTubeClient(http, "test")
    config = {"server": SERVER, "token": TOKEN, **(values or {})}
    logger = _Logger()
    translator = Translator(client, logger, sleep=(sleeps if sleeps is not None else []).append)
    provider = MetaTubeProvider(
        client, lambda: Config.from_values(config), "metatube", logger, translator
    )
    return provider, recorder


class _Logger:
    def warning(self, message: str, *args: Any) -> None: ...

    def info(self, message: str, *args: Any) -> None: ...


def standard_handler(request: httpx2.Request) -> httpx2.Response:
    path = request.url.path
    if path == "/v1/movies/search":
        return envelope(
            [
                {"provider": "DMM", "id": "a", "number": "SSIS-001", "title": "B"},
                {
                    "provider": "FANZA",
                    "id": "ssis00001",
                    "number": "SSIS-001",
                    "title": "A",
                    "release_date": "2021-02-03T00:00:00Z",
                },
            ]
        )
    if path.startswith("/v1/movies/FANZA/"):
        return envelope(MOVIE)
    if path == "/v1/actors/search":
        return envelope(
            [
                {
                    "provider": "FANZA",
                    "id": "1",
                    "name": "女優A",
                    "images": ["https://a.test/1.jpg"],
                },
                {
                    "provider": "Gfriends",
                    "id": "g1",
                    "name": "女優A",
                    "images": ["https://g.test/1.jpg"],
                },
            ]
            if request.url.params["q"] == "女優A"
            else []
        )
    return error(404, "not found")
