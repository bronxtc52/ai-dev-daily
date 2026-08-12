"""Критерии 1–6 ТЗ heartbeat (docs/specs/heartbeat.md) — сторона сервиса.

Heartbeat — единственный след прогона, который видит внешний монитор. Поэтому
проверяем не «файл появился», а ровно те свойства, на которые монитор опирается:
исход записан честно, отладочный прогон монитор не ослепляет, секрет в файл не
утекает, и сама запись не может уронить дайджест.
"""
import datetime as dt
import json
import pathlib

import pytest

import run_daily


NOW = dt.datetime(2026, 8, 13, 4, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Изолированный прогон с фейковой сетью — как в test_run_daily."""
    monkeypatch.setattr(run_daily, "DATA_DIR", tmp_path)
    monkeypatch.setattr(run_daily, "LOCK_PATH", tmp_path / "run.lock")
    monkeypatch.setattr(run_daily, "LOG_PATH", tmp_path / "run_daily.log")

    runs = {"n": 0}

    def fresh_digest(*a, **k):
        runs["n"] += 1
        return {"blocks": [{"emoji": "🏗", "title": f"Материал {runs['n']}.{i}",
                            "url": f"https://example.com/{runs['n']}/{i}",
                            "benefit": "Что вам это даёт: экономия времени."}
                           for i in range(4)],
                "radar": [], "degraded": False}

    monkeypatch.setattr(run_daily, "collect_candidates",
                        lambda **k: [{"url": "https://example.com/src", "title": "t"}])
    monkeypatch.setattr(run_daily, "curate_digest", fresh_digest)
    sent = []
    monkeypatch.setattr(run_daily, "send_telegram",
                        lambda text, **k: sent.append(text) or {"message_id": len(sent)})
    monkeypatch.setattr(run_daily, "send_alert", lambda text, **k: None)
    return tmp_path, sent


def hb(data_dir):
    """Прочитать heartbeat; None — файла нет."""
    path = pathlib.Path(data_dir) / "heartbeat.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# --- Критерий 1: успешный прогон оставляет success --------------------------

def test_successful_run_writes_success_heartbeat(env):
    data_dir, sent = env
    assert run_daily.main(["--now", NOW.isoformat()]) == 0
    assert len(sent) == 1, "предусловие теста: пост должен был уйти"

    beat = hb(data_dir)
    assert beat is not None, "успешный прогон не оставил heartbeat — монитор ослеп"
    assert beat["status"] == "success"
    assert beat["digest_date"] == "2026-08-13"

    finished = dt.datetime.fromisoformat(beat["finished_at"].replace("Z", "+00:00"))
    assert finished.tzinfo is not None, "время без зоны — возраст посчитается неверно"
    assert abs((finished - NOW).total_seconds()) < 3600


# --- Критерий 2: падение пишется как failure, и ДО алёрта -------------------

def test_crashed_run_writes_failure_heartbeat(env, monkeypatch):
    data_dir, _ = env
    monkeypatch.setattr(run_daily, "curate_digest",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("курация легла")))

    assert run_daily.main(["--now", NOW.isoformat()]) == 1

    beat = hb(data_dir)
    assert beat is not None, "упавший прогон не оставил heartbeat"
    assert beat["status"] == "failure"
    assert "курация легла" in beat["reason"]


def test_heartbeat_written_before_alert(env, monkeypatch):
    """Алёрт идёт по сети и может не дойти — heartbeat обязан лечь раньше."""
    data_dir, _ = env
    seen = {}

    monkeypatch.setattr(run_daily, "curate_digest",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("бум")))
    monkeypatch.setattr(run_daily, "_try_alert",
                        lambda text, **k: seen.update(hb_at_alert=hb(data_dir)))

    run_daily.main(["--now", NOW.isoformat()])

    assert seen.get("hb_at_alert") is not None, \
        "на момент алёрта heartbeat ещё не записан: падение доставки съест исход"
    assert seen["hb_at_alert"]["status"] == "failure"


def test_run_returning_failure_code_without_exception_is_failure(env, monkeypatch):
    """Провал «в пост влезло мало блоков» — это return 1, а не исключение."""
    data_dir, _ = env
    monkeypatch.setattr(run_daily, "run", lambda **k: 1)

    assert run_daily.main(["--now", NOW.isoformat()]) == 1
    beat = hb(data_dir)
    assert beat is not None and beat["status"] == "failure", \
        "провал без исключения записан как успех — монитор промолчит"


def test_lock_busy_does_not_touch_heartbeat(env, monkeypatch):
    """Код 2 = работает ДРУГОЙ прогон; его исход этому процессу неизвестен."""
    data_dir, _ = env
    run_daily.main(["--now", NOW.isoformat()])
    before = hb(data_dir)
    assert before is not None, "предусловие: первый прогон оставил heartbeat"

    monkeypatch.setattr(run_daily, "run", lambda **k: 2)
    run_daily.main(["--now", (NOW + dt.timedelta(days=1)).isoformat()])

    assert hb(data_dir) == before, "перезаписали heartbeat чужого прогона"


# --- Критерий 3: dry-run не ослепляет монитор ------------------------------

def test_dry_run_does_not_write_heartbeat(env):
    data_dir, sent = env
    assert run_daily.main(["--now", NOW.isoformat(), "--dry-run"]) == 0
    assert sent == [], "предусловие: dry-run не отправляет"
    assert hb(data_dir) is None, \
        "dry-run оставил heartbeat: ручная отладка маскирует пропущенный прогон"


def test_dry_run_does_not_touch_existing_heartbeat(env):
    data_dir, _ = env
    run_daily.main(["--now", NOW.isoformat()])
    before = hb(data_dir)
    assert before is not None, "предусловие: боевой прогон оставил heartbeat"

    run_daily.main(["--now", (NOW + dt.timedelta(days=1)).isoformat(), "--dry-run"])
    assert hb(data_dir) == before, "dry-run обновил чужую отметку свежести"


# --- Критерий 4: секрет не утекает в heartbeat ------------------------------

def test_secret_does_not_leak_into_heartbeat(env, monkeypatch):
    data_dir, _ = env
    secret = "AAAAbbbbCCCCddddEEEEffff11112222"
    monkeypatch.setattr(run_daily.config, "issued_secrets", lambda: [secret])
    monkeypatch.setattr(
        run_daily, "curate_digest",
        lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError(f"401 от провайдера, ключ {secret} отвергнут")))

    run_daily.main(["--now", NOW.isoformat()])

    beat = hb(data_dir)
    # Сначала доказываем, что файл вообще содержит причину: без этого проверка
    # «секрета нет» зелена и на пустом файле (урок logging-basicconfig-noop).
    assert beat is not None and beat["status"] == "failure"
    assert "401 от провайдера" in beat["reason"], "причина не записана — проверять нечего"
    assert secret not in json.dumps(beat, ensure_ascii=False), "секрет утёк в heartbeat"


# --- Критерий 5: запись heartbeat не может уронить прогон -------------------

def test_heartbeat_write_failure_does_not_break_run(env, monkeypatch):
    data_dir, sent = env
    # Путь занят директорией — запись обречена.
    (pathlib.Path(data_dir) / "heartbeat.json").mkdir()

    assert run_daily.main(["--now", NOW.isoformat()]) == 0, \
        "сломанная запись heartbeat уронила успешный прогон"
    assert len(sent) == 1, "пост не ушёл из-за проблемы со служебным файлом"


# --- Критерий 6: атомарность и абсолютный путь ------------------------------

def test_heartbeat_write_is_atomic_and_leaves_no_temp(env):
    data_dir, _ = env
    run_daily.main(["--now", NOW.isoformat()])

    leftovers = [p.name for p in pathlib.Path(data_dir).glob("heartbeat*")
                 if p.name != "heartbeat.json"]
    assert leftovers == [], f"остался временный файл записи: {leftovers}"
    assert hb(data_dir)["status"] == "success", "итоговый файл невалиден"


def test_heartbeat_path_is_absolute_and_cwd_independent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                     # cron стартует не из репозитория
    assert pathlib.Path(run_daily.heartbeat_path()).is_absolute()
