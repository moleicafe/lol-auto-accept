import httpx

from laa.updates import UpdateInfo, check_for_update, parse_version


def test_parse_version():
    assert parse_version("v1.1.4") == (1, 1, 4)
    assert parse_version("1.2.10") == (1, 2, 10)
    assert parse_version("V2.0") == (2, 0)
    assert parse_version("nightly") is None
    assert parse_version("") is None


def release_transport(tag: str, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.github.com"
        return httpx.Response(status, json={
            "tag_name": tag,
            "html_url": f"https://github.com/moleicafe/lol-auto-accept/releases/tag/{tag}",
        })
    return httpx.MockTransport(handler)


async def test_newer_release_reported():
    http = httpx.AsyncClient(transport=release_transport("v9.9.9"))
    info = await check_for_update("1.1.4", http=http)
    assert info == UpdateInfo(
        version="9.9.9",
        url="https://github.com/moleicafe/lol-auto-accept/releases/tag/v9.9.9")


async def test_same_version_is_quiet():
    http = httpx.AsyncClient(transport=release_transport("v1.1.4"))
    assert await check_for_update("1.1.4", http=http) is None


async def test_older_release_is_quiet():
    http = httpx.AsyncClient(transport=release_transport("v1.0.0"))
    assert await check_for_update("1.1.4", http=http) is None


async def test_numeric_compare_not_string_compare():
    http = httpx.AsyncClient(transport=release_transport("v1.1.10"))
    info = await check_for_update("1.1.9", http=http)
    assert info is not None and info.version == "1.1.10"


async def test_http_error_is_quiet():
    http = httpx.AsyncClient(transport=release_transport("v9.9.9", status=500))
    assert await check_for_update("1.1.4", http=http) is None


async def test_garbage_tag_is_quiet():
    http = httpx.AsyncClient(transport=release_transport("latest-build"))
    assert await check_for_update("1.1.4", http=http) is None
