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


@pytest.fixture(autouse=True)
def clean_completion_stamp():
    """Штамп завершения живёт в модуле и течёт между тестами.

    Без сброса проверка «штамп снят под lock» зелена от чужого прогона —
    ровно такая холостая проверка и не покраснела на мутации.
    """
    run_daily._LAST_COMPLETION.clear()
    yield
    run_daily._LAST_COMPLETION.clear()


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
    # Отметка обязана назвать себя: иначе опечатка в пути на стороне монитора
    # приведёт его к чужому валидному JSON, и чек замолчит, выглядя исправным.
    assert beat["service"] == "ai-dev-daily"

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

    # Проглотить ошибку молча тоже нельзя: сломанный heartbeat = ослепший монитор.
    # Читаем реальный файл лога, а не caplog: basicConfig(force=True) в main()
    # сносит хендлер pytest, и caplog покажет пусто при исправном логировании.
    log_text = (pathlib.Path(data_dir) / "run_daily.log").read_text(encoding="utf-8")
    assert "отправлено" in log_text, "предусловие: лог прогона непустой и пишется"
    assert "heartbeat" in log_text.lower(), \
        "сбой записи heartbeat не оставил следа в логе"


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


# --- Семантика finished_at (вопрос внешнего ревью диффа) --------------------

def test_finished_at_is_write_time_in_production(env, monkeypatch):
    """Без --now отметка несёт РЕАЛЬНОЕ время завершения, а не время старта.

    Ревью диффа заподозрило, что main() фиксирует `now` один раз и передаёт его
    же в heartbeat, то есть отметка врёт на длительность прогона. В проде флага
    --now нет, `now` остаётся None, и время берётся в момент записи. Проверяем
    это, а не читаем код глазами: на нём стоит вся арифметика порога 24 ч.
    """
    data_dir, _ = env
    before = dt.datetime.now(dt.timezone.utc)
    assert run_daily.main([]) == 0                      # ровно так зовёт cron
    after = dt.datetime.now(dt.timezone.utc)

    beat = hb(data_dir)
    finished = dt.datetime.fromisoformat(beat["finished_at"].replace("Z", "+00:00"))
    assert before.replace(microsecond=0) <= finished <= after + dt.timedelta(seconds=1), \
        "finished_at не совпал с моментом записи — порог свежести поедет"


def test_now_flag_is_debug_only_and_marks_the_beat(env):
    """--now подменяет и отметку тоже. Осознанно: флаг только для отладки.

    Тест фиксирует поведение, чтобы «боевой прогон с --now» не выглядел
    безобидным: отметка получит поддельное время и обманет монитор.
    """
    data_dir, _ = env
    past = dt.datetime(2026, 1, 1, 4, 0, tzinfo=dt.timezone.utc)
    run_daily.main(["--now", past.isoformat()])
    assert hb(data_dir)["finished_at"].startswith("2026-01-01")


# --- Находка Codex (PR #3): гонка после освобождения lock -------------------

def test_older_run_does_not_overwrite_newer_heartbeat(env):
    """Отметка обязана представлять ПОСЛЕДНИЙ завершившийся прогон.

    Запись происходит уже после освобождения lock, поэтому порядок записи может
    разойтись с порядком завершения: провалившийся прогон, вытесненный с CPU,
    очнётся и затрёт успех более позднего ретрая ложным failure — и сторож
    честно поднимет тревогу по несуществующей поломке.
    """
    data_dir, _ = env
    later = NOW + dt.timedelta(minutes=5)

    run_daily.write_heartbeat("success", now=later)      # прогон B завершился позже
    run_daily.write_heartbeat("failure", now=NOW)        # прогон A завершился раньше, пишет позже

    beat = hb(data_dir)
    assert beat["status"] == "success", \
        "старый исход затёр более свежий — сторож заалёртит на ровном месте"
    assert beat["finished_at"].startswith(later.strftime("%Y-%m-%dT%H:%M"))


def test_newer_run_does_overwrite_older_heartbeat(env):
    """Обратная сторона: нормальная смена дней обязана работать."""
    data_dir, _ = env
    run_daily.write_heartbeat("failure", now=NOW)
    run_daily.write_heartbeat("success", now=NOW + dt.timedelta(days=1))
    assert hb(data_dir)["status"] == "success", "свежая отметка не записалась"


def test_temp_file_name_is_unique_per_process(env, monkeypatch):
    """Два писателя не должны делить одно имя временного файла."""
    data_dir, _ = env
    seen = []
    real_replace = run_daily.os.replace
    monkeypatch.setattr(run_daily.os, "replace",
                        lambda src, dst: seen.append(str(src)) or real_replace(src, dst))

    run_daily.write_heartbeat("success", now=NOW)
    assert seen, "предусловие: запись действительно шла через os.replace"
    assert str(run_daily.os.getpid()) in seen[0], \
        f"общее имя временного файла у конкурирующих процессов: {seen[0]}"


def test_completion_time_is_taken_while_holding_the_lock(env, monkeypatch):
    """Порядок завершения задаётся lock'ом, значит и штамп снимать под ним.

    Иначе защита от отката пустая: вытесненный прогон очнётся уже после
    чужой записи, возьмёт СВОЙ штамп позже чужого и на законных основаниях
    затрёт более свежий исход (находка Codex на PR #3).
    """
    data_dir, _ = env
    seen = {}
    real_release = run_daily.release_lock
    monkeypatch.setattr(
        run_daily, "release_lock",
        lambda path=None: seen.update(stamp=run_daily._LAST_COMPLETION.get("at"))
        or real_release(path))

    assert run_daily._LAST_COMPLETION.get("at") is None, \
        "предусловие: до прогона штампа нет, иначе проверка холостая"
    run_daily.main([])

    assert seen.get("stamp") is not None, \
        "штамп снят уже после освобождения lock — порядок завершения не зафиксирован"


def test_heartbeat_uses_the_in_lock_timestamp(env, monkeypatch):
    """main() обязан писать именно тот момент, что зафиксирован под lock'ом."""
    data_dir, _ = env
    inside = dt.datetime(2026, 8, 13, 4, 0, 5, tzinfo=dt.timezone.utc)

    def fake_run(**kwargs):
        run_daily._LAST_COMPLETION["at"] = inside      # как это делает настоящий run()
        return 0

    monkeypatch.setattr(run_daily, "run", fake_run)
    run_daily.main([])

    assert hb(data_dir)["finished_at"] == "2026-08-13T04:00:05.000000Z", \
        "записан момент записи, а не момент завершения под lock'ом"


# --- Находки CodeRabbit (PR #3, 🟠 Major): защита не должна залипать ---------

def test_corrupt_existing_heartbeat_is_replaced(env):
    """Битая отметка не имеет права запретить запись навсегда.

    Строковое сравнение делает `{"finished_at":"z"}` больше любой валидной
    даты: все здоровые прогоны пропускали бы запись, и сторож остался бы в
    ошибке навечно — залипание страшнее гонки, от которой защищались.
    """
    data_dir, _ = env
    (pathlib.Path(data_dir) / "heartbeat.json").write_text(
        json.dumps({"finished_at": "z"}), encoding="utf-8")

    run_daily.write_heartbeat("success", now=NOW)

    beat = hb(data_dir)
    assert beat["status"] == "success", "битая отметка заблокировала запись навсегда"
    assert beat["service"] == "ai-dev-daily"


def test_foreign_existing_heartbeat_is_replaced(env):
    """Чужая отметка по нашему пути тоже не должна нас блокировать."""
    data_dir, _ = env
    (pathlib.Path(data_dir) / "heartbeat.json").write_text(
        json.dumps({"service": "чужой-сервис", "status": "success",
                    "finished_at": "2099-01-01T00:00:00Z"}), encoding="utf-8")

    run_daily.write_heartbeat("failure", now=NOW, reason="повод")
    assert hb(data_dir)["service"] == "ai-dev-daily", "чужая отметка заблокировала нашу"


def test_unparsable_existing_timestamp_is_replaced(env):
    """Нечитаемое время у лежащей отметки = она устарела, а не «свежее всех»."""
    data_dir, _ = env
    (pathlib.Path(data_dir) / "heartbeat.json").write_text(
        json.dumps({"service": "ai-dev-daily", "status": "success",
                    "finished_at": "вчера вечером"}), encoding="utf-8")

    run_daily.write_heartbeat("success", now=NOW)
    assert hb(data_dir)["finished_at"].startswith("2026-08-13T04:00")


def test_two_runs_in_the_same_second_are_ordered(env):
    """Секундной точности мало: два прогона в одной секунде неразличимы."""
    data_dir, _ = env
    first = NOW
    second = NOW + dt.timedelta(microseconds=500000)

    run_daily.write_heartbeat("success", now=second)   # завершился позже
    run_daily.write_heartbeat("failure", now=first)    # завершился раньше, пишет позже

    assert hb(data_dir)["status"] == "success", \
        "в пределах одной секунды порядок завершений потерян"
