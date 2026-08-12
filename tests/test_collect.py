"""Критерии 1, 10 (частичный отказ), 14 (ретраи) — сбор кандидатов.

Мокаются только системные границы: сеть и время.
"""
import datetime as dt
import pathlib

import pytest

import collect


REPO = pathlib.Path(__file__).resolve().parent.parent


# --- Критерий 1: окно свежести считается от текущего UTC ---------------------

def test_window_start_is_relative_to_now():
    now = dt.datetime(2026, 8, 11, 4, 0, tzinfo=dt.timezone.utc)
    assert collect.window_start(now, days=3) == "2026-08-08"


def test_window_start_moves_with_now():
    # Через сутки окно обязано сдвинуться — иначе дата зашита.
    a = collect.window_start(dt.datetime(2026, 8, 11, tzinfo=dt.timezone.utc), days=3)
    b = collect.window_start(dt.datetime(2026, 8, 12, tzinfo=dt.timezone.utc), days=3)
    assert (a, b) == ("2026-08-08", "2026-08-09")


def test_window_depth_is_configurable():
    now = dt.datetime(2026, 8, 11, tzinfo=dt.timezone.utc)
    assert collect.window_start(now, days=7) == "2026-08-04"


def test_no_frozen_probe_date_in_source():
    # Дата пробного прогона 19.07.2026 не должна остаться константой в коде.
    src = (REPO / "pipeline" / "collect.py").read_text()
    assert "2026,7,19" not in src.replace(" ", "")
    assert "2026-07-19" not in src


# --- Критерий 10: частичный отказ источников ---------------------------------

def test_collect_survives_one_dead_source():
    def x_ok(_q, _n=15):
        return [{"source": "X", "title": "живой", "url": "https://x.com/1"}]

    def boom(_q, _n=10):
        raise ConnectionError("GitHub недоступен")

    got = collect.gather(sources={"x": x_ok, "github": boom}, queries={"x": ["q"], "github": ["q"]})

    assert [c["source"] for c in got] == ["X"], "живой источник обязан доехать"


def test_collect_fails_when_all_sources_dead():
    def boom(_q, _n=10):
        raise ConnectionError("нет сети")

    with pytest.raises(RuntimeError):
        collect.gather(sources={"x": boom, "github": boom},
                       queries={"x": ["q"], "github": ["q"]})


# --- Критерий 14: разовый сбой лечится ретраем, а не деградацией ------------

def test_transient_failure_is_retried():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("разовый таймаут")
        return "ok"

    assert collect.with_retry(flaky, attempts=3, base_delay=0) == "ok"
    assert calls["n"] == 2, "после успешной второй попытки третьей быть не должно"


def test_retry_gives_up_after_attempts():
    calls = {"n": 0}

    def always_dead():
        calls["n"] += 1
        raise TimeoutError("всё плохо")

    with pytest.raises(TimeoutError):
        collect.with_retry(always_dead, attempts=3, base_delay=0)
    assert calls["n"] == 3, "должно быть ровно 3 попытки"


def test_retry_does_not_retry_on_success():
    calls = {"n": 0}

    def fine():
        calls["n"] += 1
        return 42

    assert collect.with_retry(fine, attempts=3, base_delay=0) == 42
    assert calls["n"] == 1
