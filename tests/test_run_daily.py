"""Критерии 10, 12, 13, 16, 18, 20 — оркестратор.

Мокается только внешняя граница: отправка в Telegram и курация (сеть).
"""
import datetime as dt
import os
import pathlib

import pytest

import run_daily
from dedup import History


NOW = dt.datetime(2026, 8, 11, 4, 0, tzinfo=dt.timezone.utc)

DIGEST = {
    "blocks": [{"emoji": "🏗", "title": f"Материал {i}",
                "url": f"https://example.com/{i}",
                "benefit": "Что вам это даёт: экономия времени."} for i in range(4)],
    "radar": [],
    "degraded": False,
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Изолированное окружение прогона: своя data-директория и фейковая сеть."""
    monkeypatch.setattr(run_daily, "DATA_DIR", tmp_path)
    monkeypatch.setattr(run_daily, "collect_candidates",
                        lambda **k: [{"url": "https://example.com/0", "title": "t"}])
    monkeypatch.setattr(run_daily, "curate_digest", lambda *a, **k: dict(DIGEST))
    sent = []
    monkeypatch.setattr(run_daily, "send_telegram",
                        lambda text, **k: sent.append(text) or {"message_id": len(sent)})
    return tmp_path, sent


# --- Критерий 10: повторный запуск в тот же день не шлёт дубль --------------

def test_second_run_same_day_sends_nothing(env):
    _, sent = env
    assert run_daily.run(now=NOW) == 0
    assert len(sent) == 1

    assert run_daily.run(now=NOW) == 0, "повтор — это не ошибка"
    assert len(sent) == 1, "второй запуск в тот же день отправил дубль"


def test_next_day_sends_again(env):
    _, sent = env
    run_daily.run(now=NOW)
    run_daily.run(now=NOW + dt.timedelta(days=1))
    assert len(sent) == 2


def test_force_flag_overrides_same_day_guard(env):
    _, sent = env
    run_daily.run(now=NOW)
    run_daily.run(now=NOW, force=True)
    assert len(sent) == 2


# --- Критерий 12: падение после отправки не даёт дубль ----------------------

def test_crash_after_send_does_not_duplicate(env, monkeypatch):
    data_dir, sent = env

    # Сеть отработала, а процесс упал сразу после ответа Telegram.
    def send_then_die(text, **k):
        sent.append(text)
        raise RuntimeError("процесс убит после успешной отправки")

    monkeypatch.setattr(run_daily, "send_telegram", send_then_die)
    with pytest.raises(Exception):
        run_daily.run(now=NOW)
    assert len(sent) == 1

    # Следующий запуск обязан знать, что пост уже ушёл.
    monkeypatch.setattr(run_daily, "send_telegram",
                        lambda text, **k: sent.append(text) or {"message_id": 2})
    run_daily.run(now=NOW)

    assert len(sent) == 1, "дубль после падения между отправкой и записью истории"


# --- Критерий 13: работа из произвольного cwd -------------------------------

def test_paths_are_absolute_and_cwd_independent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                     # cron стартует не из репозитория
    assert pathlib.Path(run_daily.DATA_DIR).is_absolute()
    assert pathlib.Path(run_daily.LOCK_PATH).is_absolute()
    assert pathlib.Path(run_daily.LOG_PATH).is_absolute()


def test_run_works_from_foreign_cwd(env, monkeypatch, tmp_path):
    foreign = tmp_path / "elsewhere"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    _, sent = env
    assert run_daily.run(now=NOW) == 0
    assert len(sent) == 1


# --- Критерий 16: алёрт о сбое не несёт секретов ----------------------------

def test_alert_text_strips_secret_values():
    secret = "sk-ant-super-secret-value-12345"
    raw = f"HTTPError: https://api.example.com/v1?key={secret} returned 401"

    safe = run_daily.sanitize_alert(raw, secrets=[secret])

    assert secret not in safe
    assert "401" in safe, "полезная часть диагностики должна остаться"


def test_alert_masks_bearer_tokens_generically():
    raw = "Authorization: Bearer AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA failed"
    safe = run_daily.sanitize_alert(raw, secrets=[])
    assert "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" not in safe


def test_failure_sends_alert(env, monkeypatch):
    data_dir, sent = env
    alerts = []
    monkeypatch.setattr(run_daily, "curate_digest",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Claude умер")))
    monkeypatch.setattr(run_daily, "send_alert", lambda text, **k: alerts.append(text))

    code = run_daily.main(["--now", NOW.isoformat()])

    assert code != 0, "провал обязан вернуть ненулевой код"
    assert alerts, "о провале должен уйти алёрт"


def test_empty_digest_is_not_sent(env, monkeypatch):
    _, sent = env
    monkeypatch.setattr(run_daily, "curate_digest",
                        lambda *a, **k: {"blocks": [], "radar": [], "degraded": False})

    code = run_daily.run(now=NOW)

    assert sent == [], "пустой дайджест отправлять нельзя"
    assert code != 0


# --- Критерий 18: протухший lock перехватывается ----------------------------

def test_stale_lock_is_taken_over(env, tmp_path, monkeypatch):
    lock = tmp_path / "run.lock"
    # Заведомо мёртвый pid и старая отметка времени.
    lock.write_text('{"pid": 999999, "started": "2026-08-01T00:00:00+00:00"}')
    monkeypatch.setattr(run_daily, "LOCK_PATH", lock)
    _, sent = env

    assert run_daily.run(now=NOW) == 0, "протухший lock заблокировал прогон"
    assert len(sent) == 1


def test_live_lock_blocks_second_run(env, tmp_path, monkeypatch):
    lock = tmp_path / "run.lock"
    lock.write_text(
        '{"pid": %d, "started": "%s"}' % (os.getpid(), NOW.isoformat()))
    monkeypatch.setattr(run_daily, "LOCK_PATH", lock)
    _, sent = env

    code = run_daily.run(now=NOW)

    assert sent == [], "параллельный прогон не должен слать второй пост"
    assert code != 0


# --- Критерий 20: dry-run проходит путь и молчит ----------------------------

def test_dry_run_sends_nothing(env):
    _, sent = env
    assert run_daily.run(now=NOW, dry_run=True) == 0
    assert sent == [], "--dry-run не должен отправлять"


def test_dry_run_does_not_write_history(env):
    data_dir, _ = env
    run_daily.run(now=NOW, dry_run=True)
    assert History(data_dir / "sent_history.json").already_sent_today(NOW) is False
