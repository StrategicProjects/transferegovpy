import time

import transferegovpy as tg
from transferegovpy import _cache

from .conftest import add_page


def test_a_repeated_request_is_served_from_the_cache(mock):
    tg.set_cache(True)
    add_page(mock, 2, total=2)

    first = tg.get("parcerias", "parceria", limit=2)
    second = tg.get("parcerias", "parceria", limit=2)

    assert len(mock.calls) == 1
    assert tg.metadata(first)["cached"] is False
    assert tg.metadata(second)["cached"] is True
    assert first.equals(second)


def test_a_different_query_is_a_different_cache_entry(mock):
    tg.set_cache(True)
    add_page(mock, 1, total=1)
    add_page(mock, 1, total=1)

    tg.get("parcerias", "parceria", limit=1)
    tg.get("parcerias", "parceria", in_situacao_parceria="Aprovada", limit=1)

    assert len(mock.calls) == 2


def test_the_cache_argument_overrides_the_session_setting(mock):
    tg.set_cache(False)
    add_page(mock, 1, total=1)

    tg.get("parcerias", "parceria", limit=1, use_cache=True)
    tg.get("parcerias", "parceria", limit=1, use_cache=True)

    assert len(mock.calls) == 1


def test_an_entry_past_its_time_to_live_is_refetched(mock):
    tg.set_cache(True)
    tg.set_cache_ttl(0)
    add_page(mock, 1, total=1)
    add_page(mock, 1, total=1)

    tg.get("parcerias", "parceria", limit=1)
    time.sleep(0.01)
    tg.get("parcerias", "parceria", limit=1)

    assert len(mock.calls) == 2


def test_a_corrupt_cache_file_is_a_miss_not_a_failure(mock):
    tg.set_cache(True)
    add_page(mock, 1, total=1)
    add_page(mock, 1, total=1)

    tg.get("parcerias", "parceria", limit=1)
    for entry in tg.cache_dir().glob("*.json"):
        entry.write_text("{ not json", encoding="utf-8")

    tg.get("parcerias", "parceria", limit=1)

    assert len(mock.calls) == 2


def test_an_entry_stamped_in_the_future_is_a_miss(mock):
    tg.set_cache(True)
    add_page(mock, 1, total=1)
    add_page(mock, 1, total=1)

    tg.get("parcerias", "parceria", limit=1)
    for entry in tg.cache_dir().glob("*.json"):
        import json

        payload = json.loads(entry.read_text(encoding="utf-8"))
        payload["created"] = time.time() + 86400
        entry.write_text(json.dumps(payload), encoding="utf-8")

    tg.get("parcerias", "parceria", limit=1)

    assert len(mock.calls) == 2


def test_cache_clear_empties_the_directory(mock):
    tg.set_cache(True)
    add_page(mock, 1, total=1)

    tg.get("parcerias", "parceria", limit=1)
    assert len(list(tg.cache_dir().glob("*.json"))) == 1

    assert tg.cache_clear() == 1
    assert len(list(tg.cache_dir().glob("*.json"))) == 0


def test_clearing_a_directory_that_does_not_exist_is_not_an_error(tmp_path):
    _cache._state["dir"] = tmp_path / "absent"
    assert tg.cache_clear() == 0


def test_the_cache_defaults_to_the_temporary_directory(monkeypatch):
    import tempfile

    _cache._state["dir"] = None
    monkeypatch.delenv("TRANSFEREGOVPY_CACHE_DIR", raising=False)

    # Nothing is written to the user's filesystem unless they ask for it.
    assert str(tg.cache_dir()).startswith(tempfile.gettempdir())


def test_the_environment_variable_sets_a_persistent_directory(monkeypatch, tmp_path):
    _cache._state["dir"] = None
    monkeypatch.setenv("TRANSFEREGOVPY_CACHE_DIR", str(tmp_path / "persist"))

    assert tg.cache_dir() == tmp_path / "persist"


def test_setting_the_cache_directory_creates_it(tmp_path):
    target = tmp_path / "nested" / "cache"
    assert tg.cache_dir(target) == target
    assert target.is_dir()


def test_a_cached_multi_page_collection_reports_itself_as_cached(mock):
    tg.set_cache(True)
    add_page(mock, 2, start=1, total=4, page=1, page_size=2)
    add_page(mock, 2, start=3, total=4, page=2, page_size=2)

    first = tg.get("parcerias", "parceria", limit=4, page_size=2)
    second = tg.get("parcerias", "parceria", limit=4, page_size=2)

    assert tg.metadata(first)["cached"] is False
    assert tg.metadata(second)["cached"] is True
    assert list(first["id_parceria"]) == list(second["id_parceria"])
