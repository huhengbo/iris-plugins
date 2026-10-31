from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from iris_plugin_sdk import MetadataNotFound, MetadataSearchRequest, MetadataUnavailable

from tests.fake_server import (
    MOVIE,
    SERVER,
    TOKEN,
    envelope,
    error,
    make_provider,
    standard_handler,
)


def test_search_formats_candidates_like_jellyfin_plugin() -> None:
    provider, recorder = make_provider(standard_handler)

    candidates = provider.search(MetadataSearchRequest(title="SSIS-001"))

    assert [c.title for c in candidates] == ["[DMM] SSIS-001 B", "[FANZA] SSIS-001 A"]
    assert candidates[1].remote_id == "FANZA:ssis00001"
    assert candidates[1].year == 2021
    assert candidates[0].year is None
    request = recorder.requests[0]
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.url.params["q"] == "SSIS-001"
    assert request.url.params["fallback"] == "true"


def test_search_filter_keeps_listed_providers_in_filter_order() -> None:
    provider, _ = make_provider(
        standard_handler,
        {"enable_provider_filter": True, "provider_filter": "fanza, dmm ,FANZA"},
    )

    titles = [c.title for c in provider.search(MetadataSearchRequest(title="x"))]

    assert titles == ["[FANZA] SSIS-001 A", "[DMM] SSIS-001 B"]


def test_search_filter_drops_unlisted_providers() -> None:
    provider, _ = make_provider(
        standard_handler, {"enable_provider_filter": True, "provider_filter": "FANZA"}
    )

    assert len(provider.search(MetadataSearchRequest(title="x"))) == 1


def test_search_ignores_empty_filter() -> None:
    provider, _ = make_provider(
        standard_handler, {"enable_provider_filter": True, "provider_filter": " , "}
    )

    assert len(provider.search(MetadataSearchRequest(title="x"))) == 2


def test_search_series_returns_nothing_without_request() -> None:
    provider, recorder = make_provider(standard_handler)

    assert provider.search(MetadataSearchRequest(title="x", kind="series")) == []
    assert recorder.requests == []


def test_details_maps_fields_with_default_templates() -> None:
    provider, _ = make_provider(standard_handler)

    record = provider.details("FANZA:ssis00001", kind="movie")

    assert record.remote_id == "FANZA:ssis00001"
    assert record.title == "SSIS-001 原題タイトル"
    assert record.original_title == "原題タイトル"
    assert record.overview == "あらすじ"
    assert record.tagline == "配信開始日 2021-02-03"
    assert record.release_date == "2021-02-03"
    assert record.year == 2021
    assert record.rating == 8.5
    assert record.content_rating == "JP-18+"
    assert record.genres == ("単体作品", "巨乳")
    assert record.studios == ("S1",)
    assert [d.name for d in record.directors] == ["監督A"]
    assert [c.name for c in record.cast] == ["女優A", "女優B"]
    assert record.external_ids == {"metatube": "FANZA:ssis00001"}


def test_details_cast_uses_gfriends_image_and_first_result_identity() -> None:
    provider, _ = make_provider(standard_handler)

    record = provider.details("FANZA:ssis00001", kind="movie")

    actor_a, actor_b = record.cast
    assert actor_a.remote_id == "FANZA:1"
    assert actor_a.profile is not None
    path, _, query = actor_a.profile.partition("?")
    assert path == "/v1/images/primary/Gfriends/g1"
    params = parse_qs(query)
    assert params["url"] == ["https://g.test/1.jpg"]
    assert params["pos"] == ["0.5"]
    assert params["auto"] == ["true"]
    # 搜不到的演员没有头像，也不能当成已确认的演员
    assert actor_b.profile is None
    assert actor_b.remote_id == "name:%E5%A5%B3%E5%84%AAB"


def test_details_images_are_server_relative_and_include_previews() -> None:
    provider, _ = make_provider(standard_handler, {"image_quality": 80, "primary_image_ratio": 0.7})

    record = provider.details("FANZA:ssis00001", kind="movie")

    assert record.poster is not None and record.poster.startswith(
        "/v1/images/primary/FANZA/ssis00001?"
    )
    assert parse_qs(urlsplit(record.poster).query)["ratio"] == ["0.7"]
    assert parse_qs(urlsplit(record.poster).query)["quality"] == ["80"]
    assert record.backdrop is not None
    assert parse_qs(urlsplit(record.backdrop).query)["ratio"] == ["-1"]
    assert record.thumb is not None and "/v1/images/thumb/" in record.thumb
    assert len(record.artwork["poster"]) == 3
    assert parse_qs(urlsplit(record.artwork["poster"][1]).query)["url"] == [
        "https://img.test/p1.jpg"
    ]
    assert all(s.startswith("/v1/images/backdrop/") for s in record.artwork["backdrop"])


def test_details_template_variables_and_blank_handling() -> None:
    provider, _ = make_provider(
        standard_handler,
        {
            "enable_template": True,
            "name_template": "[{maker}] {number} {first_actor} {unknown}",
            "tagline_template": "{year}/{month} {actors} {series} {label} {director}",
        },
    )

    record = provider.details("FANZA:ssis00001", kind="movie")

    assert record.title == "[S1] SSIS-001 女優A {unknown}"
    assert record.tagline == "2021/02 女優A 女優B 系列X S1 NO.1 監督A"


def test_details_default_tagline_dropped_without_valid_date() -> None:
    movie = {**MOVIE, "release_date": "0001-01-01T00:00:00Z"}
    provider, _ = make_provider(
        lambda r: envelope(movie) if r.url.path.startswith("/v1/movies/") else envelope([])
    )

    record = provider.details("FANZA:ssis00001", kind="movie")

    assert record.tagline is None
    assert record.release_date is None
    assert record.year is None


def test_details_substitutions_apply_before_template() -> None:
    provider, _ = make_provider(
        standard_handler,
        {
            "enable_title_substitution": True,
            "title_substitution_table": "原題=翻訳済み\nタイトル=",
            "enable_actor_substitution": True,
            "actor_substitution_table": "女優B=\n女優a=別名A",
            "enable_genre_substitution": True,
            "genre_substitution_table": "巨乳=",
        },
    )

    record = provider.details("FANZA:ssis00001", kind="movie")

    assert record.title == "SSIS-001 翻訳済み"
    assert record.original_title == "原題タイトル"
    assert [c.name for c in record.cast] == ["別名A"]
    assert record.genres == ("単体作品",)


def test_details_optional_switches_off() -> None:
    provider, _ = make_provider(
        standard_handler, {"enable_directors": False, "enable_ratings": False}
    )

    record = provider.details("FANZA:ssis00001", kind="movie")

    assert record.directors == ()
    assert record.rating is None


def test_real_actor_names_replaces_when_title_similar() -> None:
    def handler(request):  # type: ignore[no-untyped-def]
        if request.url.path == "/v1/movies/search":
            assert request.url.params["provider"] == "AVBASE"
            assert request.url.params["q"] == "ssis00001"
            return envelope(
                [
                    {"number": "XXX-999", "title": "全然違う", "actors": ["別人"]},
                    {"number": "SSIS-001", "title": "原題タイトル", "actors": ["本名A"]},
                ]
            )
        return standard_handler(request)

    provider, _ = make_provider(handler, {"enable_real_actor_names": True})

    assert [c.name for c in provider.details("FANZA:ssis00001", kind="movie").cast] == ["本名A"]


def test_real_actor_names_keeps_original_when_no_match_or_failure() -> None:
    def no_match(request):  # type: ignore[no-untyped-def]
        if request.url.path == "/v1/movies/search":
            return envelope([{"number": "XXX-999", "title": "全然違う", "actors": ["別人"]}])
        return standard_handler(request)

    def failing(request):  # type: ignore[no-untyped-def]
        if request.url.path == "/v1/movies/search":
            return error(500, "boom")
        return standard_handler(request)

    for handler in (no_match, failing):
        provider, _ = make_provider(handler, {"enable_real_actor_names": True})
        names = [c.name for c in provider.details("FANZA:ssis00001", kind="movie").cast]
        assert names == ["女優A", "女優B"]


def test_real_actor_names_skips_unsupported_provider() -> None:
    movie = {**MOVIE, "provider": "Other"}
    provider, recorder = make_provider(
        lambda r: envelope(movie) if r.url.path.startswith("/v1/movies/Other") else envelope([]),
        {"enable_real_actor_names": True},
    )

    provider.details("Other:x", kind="movie")

    assert "/v1/movies/search" not in recorder.paths()


def test_translation_title_and_summary_with_retry_and_delay() -> None:
    attempts = {"count": 0}

    def handler(request):  # type: ignore[no-untyped-def]
        if request.url.path == "/v1/translate":
            assert "Authorization" not in request.headers
            params = request.url.params
            assert params["to"] == "zh-CN"
            assert params["from"] == "auto"
            assert params["engine"] == "Baidu"
            assert params["baidu-app-id"] == "id1"
            attempts["count"] += 1
            if attempts["count"] == 1:
                return error(500, "temporary")
            return envelope({"translated_text": "译:" + params["q"]})
        return standard_handler(request)

    sleeps: list[float] = []
    provider, _ = make_provider(
        handler,
        {
            "translation_mode": "both",
            "translation_engine": "Baidu",
            "baidu_app_id": "id1",
            "baidu_app_key": "key1",
        },
        sleeps,
    )

    record = provider.details("FANZA:ssis00001", kind="movie")

    assert record.title == "SSIS-001 译:原題タイトル"
    assert record.overview == "译:あらすじ"
    assert sleeps == [1.0, 1.0, 1.0]


def test_translation_failure_keeps_original_text() -> None:
    def handler(request):  # type: ignore[no-untyped-def]
        if request.url.path == "/v1/translate":
            return error(500, "down")
        return standard_handler(request)

    provider, _ = make_provider(handler, {"translation_mode": "summary"}, [])

    record = provider.details("FANZA:ssis00001", kind="movie")

    assert record.overview == "あらすじ"


def test_translation_to_japanese_is_refused_without_requests() -> None:
    provider, recorder = make_provider(
        standard_handler, {"translation_mode": "both", "translation_language": "ja"}, []
    )

    provider.details("FANZA:ssis00001", kind="movie")

    assert "/v1/translate" not in recorder.paths()


def test_details_not_found_and_auth_errors() -> None:
    provider, _ = make_provider(lambda r: error(404, "movie not found"))
    with pytest.raises(MetadataNotFound):
        provider.details("FANZA:x", kind="movie")

    provider, _ = make_provider(lambda r: error(401, "bad token"))
    with pytest.raises(MetadataUnavailable, match="令牌"):
        provider.details("FANZA:x", kind="movie")


def test_details_rejects_malformed_remote_id_and_series() -> None:
    provider, _ = make_provider(standard_handler)
    with pytest.raises(MetadataNotFound):
        provider.details("no-colon", kind="movie")
    with pytest.raises(MetadataNotFound):
        provider.details("FANZA:x", kind="series")


def test_unavailable_reason_and_page_url() -> None:
    provider, _ = make_provider(standard_handler, {"server": ""})
    assert provider.unavailable_reason() is not None
    with pytest.raises(MetadataUnavailable):
        provider.search(MetadataSearchRequest(title="x"))
    assert provider.page_url("movie", "FANZA:x") is None

    provider, _ = make_provider(standard_handler, {"server": SERVER + "/"})
    assert provider.unavailable_reason() is None
    assert provider.page_url("movie", "FANZA:a%2Fb") == f"{SERVER}?redirect=FANZA:a%2Fb"


def test_image_download_is_limited_to_server_image_api() -> None:
    def handler(request):  # type: ignore[no-untyped-def]
        assert "Authorization" not in request.headers
        if request.url.path == "/v1/images/primary/FANZA/missing":
            return error(404, "no image")
        return httpx_image()

    provider, recorder = make_provider(handler)

    assert provider.image("/v1/images/primary/FANZA/x?ratio=-1.0", 300) == b"\xff\xd8img"
    assert str(recorder.requests[0].url) == f"{SERVER}/v1/images/primary/FANZA/x?ratio=-1.0"
    with pytest.raises(MetadataNotFound):
        provider.image("/v1/images/primary/FANZA/missing", 300)
    for bad in ("http://evil.test/v1/images/x", "//evil.test/v1/images/x", "/v1/movies/a/b", ""):
        with pytest.raises(MetadataNotFound):
            provider.image(bad, 300)
    assert len(recorder.requests) == 2


def httpx_image():  # type: ignore[no-untyped-def]
    import httpx2

    return httpx2.Response(200, content=b"\xff\xd8img", headers={"content-type": "image/jpeg"})


def test_person_formats_overview_like_actor_provider() -> None:
    actor = {
        "provider": "FANZA",
        "id": "1",
        "name": "女優A",
        "aliases": ["女優A", "別名1", "別名1", "別名2"],
        "birthday": "1995-04-05T00:00:00Z",
        "blood_type": "A",
        "cup_size": "F",
        "debut_date": "2016-07-08T00:00:00Z",
        "height": 160,
        "measurements": "B88 W58 H86",
        "nationality": "JP",
        "summary": "ignored",
    }

    def handler(request):  # type: ignore[no-untyped-def]
        if request.url.path == "/v1/actors/FANZA/1":
            return envelope(actor)
        return standard_handler(request)

    provider, _ = make_provider(handler)

    person = provider.person("FANZA:1")

    assert person.name == "女優A"
    assert person.birthday == "1995-04-05"
    assert person.place_of_birth == "JP"
    assert person.biography == (
        "別名: 別名1, 別名2\n3サイズ: B88 W58 H86\nカップサイズ: F\n身長: 160cm\n血液型: A型\n"
        "デビュー: 2016年7月8日"
    )


def test_person_by_name_searches_and_director_has_no_profile() -> None:
    def handler(request):  # type: ignore[no-untyped-def]
        if request.url.path == "/v1/actors/search":
            return envelope([{"provider": "FANZA", "id": "1", "name": "女優A"}])
        if request.url.path == "/v1/actors/FANZA/1":
            return envelope({"name": "女優A"})
        return error(404, "x")

    provider, _ = make_provider(handler)

    assert provider.person("name:%E5%A5%B3%E5%84%AAA").name == "女優A"
    with pytest.raises(MetadataNotFound):
        provider.person("director:x")


def test_test_connection_reports_server_and_token_problems() -> None:
    def handler(request):  # type: ignore[no-untyped-def]
        if request.url.path == "/":
            return envelope({"app": "metatube"})
        if request.headers.get("Authorization") == "Bearer good":
            return envelope({"version": "1"})
        return error(401, "unauthorized")

    provider, _ = make_provider(handler)

    assert provider.test_connection({"server": SERVER, "token": "good"}) is None
    assert "令牌" in (provider.test_connection({"server": SERVER, "token": "bad"}) or "")
    assert provider.test_connection({"server": ""}) == "请填写服务器地址"
