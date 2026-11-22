"""Offline tests for the cloro GPT Researcher plugin.

``requests.post`` is replaced with a recorder, so no test touches the network.
The fixtures are shortened copies of real cloro API responses.
"""

import json
from importlib.metadata import entry_points
from pathlib import Path

import pytest
import requests

import gpt_researcher_cloro as plugin
from gpt_researcher_cloro import CloroAIModeSearch, CloroBingAIModeSearch, CloroBingSearch, CloroSearch

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


class _Resp:
    def __init__(self, payload=None, status=200, bad_json=False):
        self._payload = payload
        self.status_code = status
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not JSON")
        return self._payload


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CLORO_API_KEY", "test-key")
    monkeypatch.delenv("CLORO_COUNTRY", raising=False)
    monkeypatch.delenv("CLORO_INCLUDE_ADS", raising=False)


@pytest.fixture
def post(monkeypatch):
    calls = []
    state = {"resp": _Resp({"success": True, "result": {}})}

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if isinstance(state["resp"], Exception):
            raise state["resp"]
        return state["resp"]

    monkeypatch.setattr(plugin.requests, "post", fake_post)
    fake_post.calls = calls
    fake_post.state = state
    return fake_post


# Entry points


def test_entry_points_are_registered():
    names = {ep.name: ep.value for ep in entry_points(group="gpt_researcher.retrievers")}
    assert names["cloro"] == "gpt_researcher_cloro:CloroSearch"
    assert names["cloro_bing"] == "gpt_researcher_cloro:CloroBingSearch"
    assert names["cloro_aimode"] == "gpt_researcher_cloro:CloroAIModeSearch"
    assert names["cloro_bing_aimode"] == "gpt_researcher_cloro:CloroBingAIModeSearch"


def test_gpt_researcher_resolves_plugin_names():
    retriever = pytest.importorskip("gpt_researcher.actions.retriever")
    assert retriever.get_retriever("cloro") is CloroSearch
    assert retriever.get_retriever("cloro_bing") is CloroBingSearch
    assert retriever.get_retriever("cloro_aimode") is CloroAIModeSearch
    assert retriever.get_retriever("cloro_bing_aimode") is CloroBingAIModeSearch


# Google retriever


def test_google_request(post):
    post.state["resp"] = _Resp(_load("google.json"))
    CloroSearch("rank tracker").search()
    call = post.calls[0]
    assert call["url"] == "https://api.cloro.dev/v1/monitor/google"
    assert call["json"] == {"query": "rank tracker", "country": "US"}
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert "test-key" not in call["url"]


def test_google_results_skip_empty_and_redirect_links(post):
    post.state["resp"] = _Resp(_load("google.json"))
    results = CloroSearch("rank tracker").search(max_results=10)
    assert len(results) == 4
    assert results[0]["href"] == "https://zapier.com/blog/best-rank-tracker/"
    assert results[0]["title"] == "The 12 best rank tracker tools"
    assert all("google.com/goto" not in r["href"] for r in results)
    assert all(set(r) == {"title", "href", "body"} for r in results)


def test_google_respects_max_results(post):
    post.state["resp"] = _Resp(_load("google.json"))
    assert len(CloroSearch("q").search(max_results=2)) == 2


def test_google_query_domains_become_site_filters(post):
    post.state["resp"] = _Resp(_load("google.json"))
    CloroSearch("q", query_domains=["a.com", " b.org "]).search()
    assert post.calls[0]["json"]["query"] == "q site:a.com OR site:b.org"


def test_country_from_env(post, monkeypatch):
    monkeypatch.setenv("CLORO_COUNTRY", "de")
    post.state["resp"] = _Resp(_load("google.json"))
    CloroSearch("q").search()
    assert post.calls[0]["json"]["country"] == "DE"


def test_accepts_extra_constructor_kwargs(post):
    CloroSearch("q", query_domains=None, headers={}, websocket=None, researcher=None).search()


# Bing retriever


def test_bing_request(post):
    post.state["resp"] = _Resp(_load("bing.json"))
    CloroBingSearch("season a wok", query_domains=["a.com"]).search()
    call = post.calls[0]
    assert call["url"] == "https://api.cloro.dev/v1/monitor/bing"
    assert call["json"] == {"query": "season a wok site:a.com", "country": "US"}


def test_bing_results(post):
    payload = _load("bing.json")
    post.state["resp"] = _Resp(payload)
    results = CloroBingSearch("season a wok").search(max_results=10)
    assert [r["href"] for r in results] == [r["link"] for r in payload["result"]["organicResults"]]
    assert results[0]["title"] == "How to Season a Wok"
    assert all(set(r) == {"title", "href", "body"} for r in results)
    assert CloroBingSearch.requires_scraping is True


# Ads

ADS = [
    {
        "position": 1,
        "blockPosition": "top",
        "type": "RESULT",
        "title": "Wok Sale",
        "url": "https://shop.example/woks",
        "page": 1,
        "description": "Carbon steel woks.",
    },
    {
        "position": 1,
        "blockPosition": "rhs",
        "type": "SHOPPING_CARD",
        "title": "14 in Wok",
        "url": "https://shop.example/wok-14",
        "page": 1,
        "price": {"value": 29, "currency": "$", "raw": "$29.00"},
        "store": "Shop",
    },
    {},
]


@pytest.mark.parametrize(
    ("cls", "fixture", "engine", "href"),
    [
        (CloroSearch, "google.json", "Google", "https://www.google.com/search?q=season+a+wok"),
        (CloroBingSearch, "bing.json", "Bing", "https://www.bing.com/search?q=season+a+wok"),
    ],
)
def test_ads_are_one_marked_result(post, monkeypatch, cls, fixture, engine, href):
    monkeypatch.setenv("CLORO_INCLUDE_ADS", "true")
    payload = _load(fixture)
    payload["result"]["ads"] = ADS
    post.state["resp"] = _Resp(payload)
    retriever = cls("season a wok")
    results = retriever.search(max_results=2)
    assert post.calls[0]["json"] == {"query": "season a wok", "country": "US"}
    assert len(results) == 3
    assert all("raw_content" not in r for r in results[:2])
    assert retriever.requires_scraping is False
    ads = results[2]
    assert ads["title"] == f"{engine} ads: season a wok"
    assert ads["href"] == href
    assert ads["source"] == f"{engine.lower()}_ad"
    assert ads["raw_content"] == (
        f"{engine} ads for: season a wok\n\n"
        f"{engine} ad (RESULT top 1): Wok Sale\nhttps://shop.example/woks\nCarbon steel woks.\n\n"
        f"{engine} ad (SHOPPING_CARD rhs 1): 14 in Wok\nhttps://shop.example/wok-14\n$29.00\nShop\n\n"
        f"{engine} ad ():"
    )


@pytest.mark.parametrize("value", [None, "", "false", "0"])
def test_ads_off_by_default(post, monkeypatch, value):
    if value is not None:
        monkeypatch.setenv("CLORO_INCLUDE_ADS", value)
    payload = _load("bing.json")
    payload["result"]["ads"] = ADS
    post.state["resp"] = _Resp(payload)
    retriever = CloroBingSearch("q")
    assert all(set(r) == {"title", "href", "body"} for r in retriever.search())
    assert retriever.requires_scraping is True


def test_include_ads_without_ads(post, monkeypatch):
    monkeypatch.setenv("CLORO_INCLUDE_ADS", "true")
    post.state["resp"] = _Resp(_load("bing.json"))
    assert len(CloroBingSearch("q").search()) == 3


# AI Mode retriever


def test_aimode_request(post):
    post.state["resp"] = _Resp(_load("aimode.json"))
    CloroAIModeSearch("rank tracker").search()
    call = post.calls[0]
    assert call["url"] == "https://api.cloro.dev/v1/monitor/aimode"
    assert call["json"] == {"prompt": "rank tracker", "country": "US", "include": {"markdown": True}}


def test_aimode_answer_first_then_sources(post):
    payload = _load("aimode.json")
    post.state["resp"] = _Resp(payload)
    results = CloroAIModeSearch("rank tracker").search(max_results=10)
    answer, sources = results[0], results[1:]
    assert answer["href"] == "https://www.google.com/search?udm=50&q=rank+tracker"
    assert payload["result"]["markdown"] in answer["raw_content"]
    assert [s["href"] for s in sources] == [s["url"] for s in payload["result"]["sources"]]
    assert all("raw_content" not in s for s in sources)
    assert CloroAIModeSearch.requires_scraping is False


def test_aimode_falls_back_to_text_without_markdown(post):
    payload = _load("aimode.json")
    del payload["result"]["markdown"]
    post.state["resp"] = _Resp(payload)
    answer = CloroAIModeSearch("q").search()[0]
    assert payload["result"]["text"] in answer["raw_content"]


def test_aimode_respects_max_results(post):
    post.state["resp"] = _Resp(_load("aimode.json"))
    assert len(CloroAIModeSearch("q").search(max_results=2)) == 2


# Bing AI Mode retriever


def test_bing_aimode_request(post):
    post.state["resp"] = _Resp(_load("bing_aimode.json"))
    CloroBingAIModeSearch("iphone 17 vs samsung galaxy s26 comparison").search()
    call = post.calls[0]
    assert call["url"] == "https://api.cloro.dev/v1/monitor/bing/aimode"
    assert call["json"] == {
        "prompt": "iphone 17 vs samsung galaxy s26 comparison",
        "country": "US",
        "include": {"markdown": True},
    }


def test_bing_aimode_answer_first_then_sources(post):
    payload = _load("bing_aimode.json")
    post.state["resp"] = _Resp(payload)
    results = CloroBingAIModeSearch("iphone 17 vs galaxy s26").search(max_results=10)
    answer, sources = results[0], results[1:]
    assert answer["title"] == "Bing AI Mode: iphone 17 vs galaxy s26"
    assert answer["href"] == "https://www.bing.com/copilotsearch?q=iphone+17+vs+galaxy+s26"
    assert answer["raw_content"].startswith("Bing AI Mode answer to: iphone 17 vs galaxy s26")
    assert payload["result"]["markdown"] in answer["raw_content"]
    assert [s["href"] for s in sources] == [s["url"] for s in payload["result"]["sources"]]
    assert all("raw_content" not in s for s in sources)
    assert CloroBingAIModeSearch.requires_scraping is False


def test_bing_aimode_respects_max_results(post):
    post.state["resp"] = _Resp(_load("bing_aimode.json"))
    assert len(CloroBingAIModeSearch("q").search(max_results=2)) == 2


# Failures return []


@pytest.mark.parametrize("cls", [CloroSearch, CloroBingSearch, CloroAIModeSearch, CloroBingAIModeSearch])
def test_missing_key_returns_empty_without_request(post, monkeypatch, cls):
    monkeypatch.delenv("CLORO_API_KEY")
    assert cls("q").search() == []
    assert post.calls == []


@pytest.mark.parametrize("cls", [CloroSearch, CloroBingSearch, CloroAIModeSearch, CloroBingAIModeSearch])
@pytest.mark.parametrize(
    "resp",
    [
        _Resp(_load("error_401.json"), status=401),
        _Resp({"success": False, "error": {"code": "INSUFFICIENT_CREDITS"}}, status=403),
        _Resp(None, status=502, bad_json=True),
        _Resp({"success": True, "result": None}),
        requests.Timeout("slow"),
        requests.ConnectionError("down"),
    ],
)
def test_failures_return_empty(post, cls, resp):
    post.state["resp"] = resp
    assert cls("q").search() == []


def test_error_log_has_code_and_no_key(post, caplog):
    post.state["resp"] = _Resp(_load("error_401.json"), status=401)
    CloroSearch("q").search()
    assert "INVALID_API_KEY_FORMAT" in caplog.text
    assert "test-key" not in caplog.text


def test_google_search_and_shopping_links_are_not_sources():
    from gpt_researcher_cloro import _is_direct_link

    assert _is_direct_link("https://aws.amazon.com/what-is/retrieval-augmented-generation/")
    assert not _is_direct_link("https://www.google.com/search?q=product&ibp=oshop")
    assert not _is_direct_link("https://www.google.com/goto?url=x")
    assert not _is_direct_link("")
