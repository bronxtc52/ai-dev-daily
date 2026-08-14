"""Автономность сервиса: то, что нужно, чтобы он жил годами без человека.

Пять независимых классов отказа, каждый из которых сегодня проходит молча:

1. Пост уезжает в ПУБЛИЧНЫЙ канал, а аварийные сообщения — тем же адресатом,
   то есть подписчикам. Адресаты обязаны разойтись.
2. Разовый сбой в 04:00 стоит целого дня: ретрая прогона нет.
3. Источник умер (протух токен, сменился API) — сбор идёт на оставшихся,
   дайджест выходит худее, и в логе лежит WARNING, который никто не читает.
4. Логи и суточные digest-файлы растут вечно.
5. GitHub PAT имеет срок; о его истечении узнаём постфактум, по поломке.
"""
import datetime as dt
import json
import pathlib

import pytest

import collect
import config
import run_daily


NOW = dt.datetime(2026, 8, 14, 4, 0, tzinfo=dt.timezone.utc)


# --- 1. Адресат поста и адресат аварий -------------------------------------

@pytest.fixture
def captured_calls(monkeypatch):
    """Перехват HTTP-вызова Telegram: интересен адресат, не доставка."""
    calls = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true, "result": {"message_id": 1}}'

    def fake_urlopen(req, timeout=None):
        calls.append({"url": req.full_url, "body": req.data.decode()})
        return _Resp()

    monkeypatch.setattr(run_daily.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(run_daily.json, "load", lambda r: json.loads(r.read()))
    return calls


def _set_secrets(monkeypatch, **kw):
    """Подменить разрешение секретов, не трогая Key Vault.

    Ненастроенный ключ обязан давать RuntimeError — ровно то, что бросает
    настоящий config.secret. Подмена, падающая KeyError, проверяла бы не тот
    контракт: ветка fallback ловит именно RuntimeError.
    """
    def fake(key):
        if key not in kw:
            raise RuntimeError(f"{key}: не настроен")
        return kw[key]

    monkeypatch.setattr(config, "secret", fake)
    monkeypatch.setattr(run_daily, "secret", fake)


def test_alert_goes_to_owner_not_to_channel(monkeypatch, captured_calls):
    """Авария не должна попадать в публичный канал.

    Пока адресат один, сообщение «⚠️ Дайджест не отправлен» увидят подписчики.
    """
    _set_secrets(monkeypatch,
                 TELEGRAM_BOT_TOKEN="bot-token",
                 TELEGRAM_CHAT_ID="-1001234567890",      # публичный канал
                 TELEGRAM_ALERT_CHAT_ID="201374791")     # личка владельца

    run_daily.send_alert("⚠️ Дайджест не отправлен")

    assert "chat_id=201374791" in captured_calls[-1]["body"], \
        "алёрт ушёл не владельцу"
    assert "-1001234567890" not in captured_calls[-1]["body"], \
        "алёрт видно в публичном канале"


def test_digest_goes_to_channel(monkeypatch, captured_calls):
    _set_secrets(monkeypatch,
                 TELEGRAM_BOT_TOKEN="bot-token",
                 TELEGRAM_CHAT_ID="-1001234567890",
                 TELEGRAM_ALERT_CHAT_ID="201374791")

    run_daily.send_telegram("пост")

    assert "chat_id=-1001234567890" in captured_calls[-1]["body"]


def test_alert_falls_back_to_main_chat(monkeypatch, captured_calls):
    """Без отдельного адресата поведение остаётся прежним.

    Иначе выкат новой версии до правки cron уронил бы алёрты совсем — то есть
    сломал бы ровно тот контур, который и должен сообщать о поломках.
    """
    def only_main(key):
        if key == "TELEGRAM_ALERT_CHAT_ID":
            raise RuntimeError("не задан")
        return {"TELEGRAM_BOT_TOKEN": "bot-token",
                "TELEGRAM_ALERT_BOT_TOKEN": "bot-token",
                "TELEGRAM_CHAT_ID": "201374791"}[key]

    monkeypatch.setattr(config, "secret", only_main)
    monkeypatch.setattr(run_daily, "secret", only_main)

    run_daily.send_alert("авария")

    assert "chat_id=201374791" in captured_calls[-1]["body"]


def test_partial_alert_config_does_not_mix_destinations(monkeypatch, captured_calls):
    """Половина настройки хуже, чем никакой (находка Codex на PR #7, P2).

    Два независимых fallback дают смешанный адресат: заданный алёрт-бот вместе
    с чатом ДАЙДЖЕСТА опубликует внутреннюю аварию подписчикам — ровно та
    утечка, ради предотвращения которой адресаты и разводились. Пара
    «бот+чат» обязана разрешаться целиком: либо оба свои, либо оба общие.
    """
    _set_secrets(monkeypatch,
                 TELEGRAM_BOT_TOKEN="channel-bot",
                 TELEGRAM_ALERT_BOT_TOKEN="alert-bot",   # задан
                 TELEGRAM_CHAT_ID="-1001234567890")      # а чата алёртов НЕТ

    run_daily.send_alert("авария")

    body = captured_calls[-1]["body"]
    url = captured_calls[-1]["url"]
    assert not ("/botalert-bot/" in url and "chat_id=-1001234567890" in body), \
        "смешанный адресат: алёрт-бот пишет в публичный канал"


def test_alert_can_use_separate_bot(monkeypatch, captured_calls):
    """Алёрт может идти другим ботом.

    Бот канала не обязан иметь право писать владельцу в личку: пока тот не
    нажал Start, DM от него запрещён Telegram'ом. Возможность развести боты
    снимает эту человеко-зависимость.
    """
    _set_secrets(monkeypatch,
                 TELEGRAM_BOT_TOKEN="channel-bot",
                 TELEGRAM_ALERT_BOT_TOKEN="alert-bot",
                 TELEGRAM_CHAT_ID="-1001234567890",
                 TELEGRAM_ALERT_CHAT_ID="201374791")

    run_daily.send_alert("авария")

    assert "/botalert-bot/" in captured_calls[-1]["url"]


# --- 2. Ретрай прогона -------------------------------------------------------

@pytest.fixture
def failing_env(tmp_path, monkeypatch):
    """Прогон, который гарантированно падает на сборе."""
    monkeypatch.setattr(run_daily, "DATA_DIR", tmp_path)
    monkeypatch.setattr(run_daily, "LOCK_PATH", tmp_path / "run.lock")
    monkeypatch.setattr(run_daily, "LOG_PATH", tmp_path / "run_daily.log")

    def boom(**k):
        raise RuntimeError("источники недоступны")

    monkeypatch.setattr(run_daily, "collect_candidates", boom)
    alerts = []
    monkeypatch.setattr(run_daily, "send_alert",
                        lambda text, **k: alerts.append(text))
    monkeypatch.setattr(run_daily, "init_sentry", lambda: False)
    return tmp_path, alerts


def test_non_final_attempt_stays_silent(failing_env):
    """Первая из трёх попыток не будит человека и не пугает сторож.

    Алёрт на каждой попытке — тройной шум по одному инциденту. Отметка
    `failure` на промежуточной попытке хуже: сторож читает её как «прогон
    завершился ошибкой» и алёртит по поломке, которая через полчаса
    вылечится сама.
    """
    tmp_path, alerts = failing_env

    rc = run_daily.main(["--attempt", "1", "--attempts", "3",
                         "--now", NOW.isoformat()])

    assert rc == 1
    assert alerts == [], "непоследняя попытка разбудила человека"
    assert not (tmp_path / "heartbeat.json").exists(), \
        "непоследняя попытка оставила failure — сторож поднимет ложную тревогу"


def test_final_attempt_alerts(failing_env):
    tmp_path, alerts = failing_env

    rc = run_daily.main(["--attempt", "3", "--attempts", "3",
                         "--now", NOW.isoformat()])

    assert rc == 1
    assert alerts, "последняя попытка промолчала — сбой прошёл незамеченным"
    hb = json.loads((tmp_path / "heartbeat.json").read_text())
    assert hb["status"] == "failure"


def test_single_attempt_is_final_by_default(failing_env):
    """Прогон без флагов ведёт себя как раньше: падение = алёрт."""
    tmp_path, alerts = failing_env

    run_daily.main(["--now", NOW.isoformat()])

    assert alerts


def test_sigterm_is_reported_like_a_failure(failing_env, monkeypatch):
    """Снятие по SIGTERM обязано пройти обычным путём провала.

    Находка Codex на PR #7 (P1). Внешний `timeout` шлёт процессу SIGTERM, и по
    умолчанию Python на нём просто умирает: это не исключение, ветка `except`
    в main() не выполняется, отметка `failure` не пишется и алёрт не уходит.
    То есть зависание — единственный сценарий, ради которого timeout и ставился,
    — оставалось молчаливым, а узнать о нём можно было бы только назавтра, по
    протухшей отметке.
    """
    import os
    import signal

    tmp_path, alerts = failing_env

    def hang_then_get_terminated(**k):
        os.kill(os.getpid(), signal.SIGTERM)
        return []                                   # сюда не дойдём

    monkeypatch.setattr(run_daily, "collect_candidates", hang_then_get_terminated)

    rc = run_daily.main(["--now", NOW.isoformat()])

    assert rc == 1
    assert alerts, "снятие по SIGTERM прошло молча"
    hb = json.loads((tmp_path / "heartbeat.json").read_text())
    assert hb["status"] == "failure"


# --- 3. Тихая деградация источников -----------------------------------------

def test_gather_reports_per_source_counts():
    """Сколько дал каждый источник — иначе смерть одного не отличить от тишины."""
    stats = {}
    collect.gather(
        sources={"x": lambda q: [{"url": "u1"}],
                 "github": lambda q: []},
        queries={"x": ["q"], "github": ["q"]},
        stats=stats)

    assert stats["x"] == 1
    assert stats["github"] == 0


def test_source_returning_nothing_is_reported(tmp_path, monkeypatch):
    """Источник отдал ноль — владелец узнаёт сообщением, а не по худому посту."""
    monkeypatch.setattr(run_daily, "DATA_DIR", tmp_path)
    monkeypatch.setattr(run_daily, "LOCK_PATH", tmp_path / "run.lock")
    monkeypatch.setattr(run_daily, "LOG_PATH", tmp_path / "run_daily.log")

    def collect_with_dead_source(now=None, stats=None, **k):
        if stats is not None:
            stats.update({"x": 60, "exa": 32, "github": 0})
        return [{"url": "https://example.com/src", "title": "t"}]

    monkeypatch.setattr(run_daily, "collect_candidates", collect_with_dead_source)
    monkeypatch.setattr(run_daily, "curate_digest", lambda *a, **k: {
        "blocks": [{"emoji": "🏗", "title": f"М{i}",
                    "url": f"https://example.com/{i}",
                    "benefit": "Что вам это даёт: польза."} for i in range(4)],
        "radar": [], "degraded": False})
    monkeypatch.setattr(run_daily, "send_telegram",
                        lambda text, **k: {"message_id": 7})
    notices = []
    monkeypatch.setattr(run_daily, "send_alert",
                        lambda text, **k: notices.append(text))
    monkeypatch.setattr(run_daily, "init_sentry", lambda: False)

    rc = run_daily.main(["--now", NOW.isoformat()])

    assert rc == 0, "мёртвый источник не должен отменять дайджест"
    assert any("github" in n for n in notices), \
        "смерть источника прошла молча"


def test_dead_source_is_not_reported_twice(tmp_path, monkeypatch):
    """Повторное уведомление о том же — шум, который приучает игнорировать.

    Мёртвый источник остаётся мёртвым неделями; ежедневное сообщение об этом
    обесценивает канал алёртов целиком.
    """
    state = tmp_path / "notices.json"
    run_daily.remember_notice(state, "source-dead:github", NOW)

    assert not run_daily.should_notify(state, "source-dead:github", NOW)
    assert run_daily.should_notify(
        state, "source-dead:github", NOW + dt.timedelta(days=8))


# --- 4. Гигиена диска --------------------------------------------------------

def test_old_digests_are_pruned(tmp_path):
    """Суточные файлы копятся вечно: за пять лет — почти две тысячи штук."""
    old = tmp_path / "digest-2026-01-01.json"
    recent = tmp_path / "digest-2026-08-13.json"
    other = tmp_path / "digest-2026-07-19.md"      # не наш формат — не трогаем
    for f in (old, recent, other):
        f.write_text("{}")

    run_daily.prune_old_digests(tmp_path, now=NOW, keep_days=90)

    assert not old.exists()
    assert recent.exists()
    assert other.exists(), "тронут файл, который прунингу не принадлежит"


def test_prune_survives_unparsable_names(tmp_path):
    """Мусорное имя не должно ронять прогон в самом конце успешного пути."""
    junk = tmp_path / "digest-не-дата.json"
    junk.write_text("{}")

    run_daily.prune_old_digests(tmp_path, now=NOW, keep_days=90)

    assert junk.exists()


# --- 5. Протухание GitHub PAT ------------------------------------------------

def test_token_expiry_warns_in_advance(tmp_path, monkeypatch):
    """О сроке токена узнаём заранее, а не по молчанию источника."""
    monkeypatch.setattr(
        collect, "github_token_expiry",
        lambda: NOW + dt.timedelta(days=10))

    notices = []
    monkeypatch.setattr(run_daily, "send_alert",
                        lambda text, **k: notices.append(text))

    run_daily.check_token_expiry(tmp_path, now=NOW, warn_days=14)

    assert any("GitHub" in n for n in notices)


def test_token_expiry_quiet_when_far_away(tmp_path, monkeypatch):
    monkeypatch.setattr(
        collect, "github_token_expiry",
        lambda: NOW + dt.timedelta(days=200))
    notices = []
    monkeypatch.setattr(run_daily, "send_alert",
                        lambda text, **k: notices.append(text))

    run_daily.check_token_expiry(tmp_path, now=NOW, warn_days=14)

    assert notices == []


def test_token_expiry_never_breaks_the_run(tmp_path, monkeypatch):
    """Служебная проверка не имеет права стоить дайджеста."""
    def boom():
        raise RuntimeError("GitHub недоступен")

    monkeypatch.setattr(collect, "github_token_expiry", boom)
    monkeypatch.setattr(run_daily, "send_alert", lambda text, **k: None)

    run_daily.check_token_expiry(tmp_path, now=NOW, warn_days=14)   # не падает
