"""Критерии 5, 6, 17 — дедуп, нормализация URL, устойчивость истории.

Ожидания — литералы: канонический вид URL проработан вручную по RFC 3986
(схема и хост регистронезависимы, путь — нет) и по списку трекинг-параметров.
"""
import datetime as dt
import json

import pytest

from dedup import History, canonical_url


NOW = dt.datetime(2026, 8, 11, 4, 0, tzinfo=dt.timezone.utc)


# --- Критерий 6: разные формы одного URL считаются одним ---------------------

@pytest.mark.parametrize("raw,expected", [
    ("https://example.com/post", "https://example.com/post"),
    ("http://example.com/post", "https://example.com/post"),
    ("https://www.example.com/post", "https://example.com/post"),
    ("https://EXAMPLE.com/post", "https://example.com/post"),
    ("https://example.com/post/", "https://example.com/post"),
    ("https://example.com/post#section", "https://example.com/post"),
    ("https://example.com/post?utm_source=x&utm_medium=y", "https://example.com/post"),
    ("https://example.com/post?fbclid=123", "https://example.com/post"),
    ("https://example.com/post?ref=newsletter", "https://example.com/post"),
    # Значимые параметры остаются — иначе разные страницы схлопнутся в одну.
    ("https://example.com/list?page=2", "https://example.com/list?page=2"),
])
def test_canonical_url_forms(raw, expected):
    assert canonical_url(raw) == expected


def test_path_case_is_preserved():
    # Путь регистрозависим: lower() по всему URL сломал бы ссылку.
    assert canonical_url("https://example.com/AbC") == "https://example.com/AbC"


def test_differing_urls_stay_different():
    assert canonical_url("https://example.com/a") != canonical_url("https://example.com/b")


# --- Критерий 5: отправленное в окне 30 дней не повторяется ------------------

def test_recently_sent_url_is_filtered(tmp_path):
    h = History(tmp_path / "sent.json")
    h.record_sent(["https://example.com/post"], message_id=1,
                  digest_hash="abc", now=NOW - dt.timedelta(days=5))

    fresh = h.filter_new([{"url": "https://example.com/post"},
                          {"url": "https://example.com/other"}], now=NOW)

    assert [c["url"] for c in fresh] == ["https://example.com/other"]


def test_filter_matches_across_url_forms(tmp_path):
    h = History(tmp_path / "sent.json")
    h.record_sent(["https://example.com/post"], message_id=1,
                  digest_hash="abc", now=NOW - dt.timedelta(days=1))

    fresh = h.filter_new(
        [{"url": "http://www.example.com/post/?utm_source=tg"}], now=NOW)

    assert fresh == [], "тот же материал в другой форме URL должен отсеяться"


def test_url_outside_window_is_allowed_again(tmp_path):
    h = History(tmp_path / "sent.json")
    h.record_sent(["https://example.com/post"], message_id=1,
                  digest_hash="abc", now=NOW - dt.timedelta(days=31))

    fresh = h.filter_new([{"url": "https://example.com/post"}], now=NOW)

    assert len(fresh) == 1, "старше окна дедупа — можно показывать снова"


def test_history_survives_reload(tmp_path):
    path = tmp_path / "sent.json"
    History(path).record_sent(["https://example.com/post"], message_id=1,
                              digest_hash="abc", now=NOW)

    fresh = History(path).filter_new([{"url": "https://example.com/post"}], now=NOW)

    assert fresh == [], "история не пережила перезапуск процесса"


# --- Критерий 17: битая история не роняет прогон и не теряется ---------------

def test_corrupt_history_is_quarantined_not_lost(tmp_path):
    path = tmp_path / "sent.json"
    path.write_text('{"entries": [ЭТО НЕ JSON')

    h = History(path)                      # не должно бросать

    assert h.filter_new([{"url": "https://example.com/a"}], now=NOW), \
        "после битого файла работа продолжается с пустой историей"
    assert path.with_suffix(".corrupt").exists(), \
        "битый файл обязан сохраниться для разбора, а не быть затёртым"


def test_corrupt_history_is_reported(tmp_path):
    path = tmp_path / "sent.json"
    path.write_text("не json")
    assert History(path).recovered_from_corruption is True


def test_atomic_write_leaves_no_temp_files(tmp_path):
    path = tmp_path / "sent.json"
    History(path).record_sent(["https://example.com/a"], message_id=1,
                              digest_hash="x", now=NOW)

    # Проверяем по факту содержимого директории, а не по угаданному суффиксу:
    # ассерт на «.tmp/.part» был бы зелёным всегда — код таких файлов не создаёт.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != path.name]
    assert leftovers == [], f"остались временные файлы записи: {leftovers}"


def test_history_file_is_valid_json(tmp_path):
    path = tmp_path / "sent.json"
    History(path).record_sent(["https://example.com/a"], message_id=7,
                              digest_hash="deadbeef", now=NOW)
    json.loads(path.read_text())        # упадёт, если запись невалидна


# --- Критерий 12: отметка об отправке видна сразу после send -----------------

def test_sent_marker_visible_to_next_run(tmp_path):
    path = tmp_path / "sent.json"
    History(path).record_sent(["https://example.com/a"], message_id=42,
                              digest_hash="hash1", now=NOW)

    assert History(path).already_sent_today(NOW) is True


def test_no_marker_means_not_sent_today(tmp_path):
    assert History(tmp_path / "sent.json").already_sent_today(NOW) is False


def test_yesterday_marker_does_not_block_today(tmp_path):
    path = tmp_path / "sent.json"
    History(path).record_sent(["https://example.com/a"], message_id=42,
                              digest_hash="h", now=NOW - dt.timedelta(days=1))

    assert History(path).already_sent_today(NOW) is False
