#!/usr/bin/env python3
"""Оркестратор ежедневного дайджеста: collect → dedup → curate → send.

Рассчитан на запуск из cron, где никто не смотрит на вывод:
- все пути абсолютные (cron стартует из чужого cwd);
- падение уходит алёртом в Telegram, а не только в лог;
- намерение отправить пишется до отправки, чтобы падение не дало дубль утром.
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import logging
import os
import pathlib
import re
import socket
import sys
import time
import urllib.parse
import urllib.request

from collect import collect_candidates
import config
from config import secret
from curate import MIN_BLOCKS, curate as curate_digest
from dedup import History, canonical_url
from formatting import build_post, render_digest

# Пути резолвятся от файла, а не от cwd: под cron рабочая директория чужая,
# и относительный путь увёл бы историю дедупа в другое место — молча.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
LOCK_PATH = DATA_DIR / "run.lock"
LOG_PATH = REPO_ROOT / "logs" / "run_daily.log"

MAX_RUNTIME_SECONDS = 600       # потолок прогона; лежащий дольше lock считаем протухшим

log = logging.getLogger("run_daily")

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг",
            "пятница", "суббота", "воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]


# ---------- внешние границы (мокаются в тестах) ------------------------------

def send_telegram(text, disable_preview=True):
    """Отправить пост. Возвращает ответ Telegram (в нём message_id)."""
    token = secret("TELEGRAM_BOT_TOKEN")
    chat = secret("TELEGRAM_CHAT_ID")
    data = urllib.parse.urlencode({
        "chat_id": chat, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": "true" if disable_preview else "false"}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.load(r)
    if not resp.get("ok"):
        raise RuntimeError(f"Telegram отверг сообщение: {resp.get('description')}")
    return resp.get("result", {})


def send_alert(text):
    """Короткое уведомление о сбое — обычным текстом, без разметки."""
    token = secret("TELEGRAM_BOT_TOKEN")
    chat = secret("TELEGRAM_CHAT_ID")
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


# ---------- безопасность вывода ---------------------------------------------

_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{16,}")
_KEY_IN_URL = re.compile(
    r"([?&](?:api[-_]?key|key|token|access[-_]?token|secret)=)[^&\s]+", re.I)
# Токен Telegram живёт в ПУТИ URL, а не в query — отдельный паттерн.
_TG_TOKEN_IN_PATH = re.compile(r"/bot\d{5,}:[A-Za-z0-9_\-]{20,}")
_XAPIKEY = re.compile(r"(x-api-key['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9_\-]{16,}", re.I)


def sanitize_alert(text, secrets=None):
    """Вычистить значения секретов из текста.

    По умолчанию маскируем по реестру фактически выданных значений
    (config.issued_secrets): в проде секреты приходят из Key Vault, и маскировка
    «по os.environ» не сработала бы вообще — там их нет.
    """
    out = str(text)
    values = config.issued_secrets() if secrets is None else secrets
    for value in values:
        if value and len(str(value)) >= 8:
            out = out.replace(str(value), "***")
    out = _BEARER.sub(r"\1***", out)
    out = _KEY_IN_URL.sub(r"\1***", out)
    out = _TG_TOKEN_IN_PATH.sub("/bot***", out)
    out = _XAPIKEY.sub(r"\1***", out)
    return out


class SecretRedactingFilter(logging.Filter):
    """Санитайзер на самом логгере.

    Алёрт чистился, а traceback от log.exception уходил в файл сырым — это
    отдельный путь утечки, не совпадающий с алёртом.
    """

    def filter(self, record):
        try:
            record.msg = sanitize_alert(record.getMessage())
            record.args = ()
            if record.exc_info:
                record.exc_text = sanitize_alert(
                    logging.Formatter().formatException(record.exc_info))
                record.exc_info = None
        except Exception:                           # noqa: BLE001
            record.msg = "[запись лога вычищена: ошибка санитайзера]"
            record.args = ()
        return True


# ---------- блокировка -------------------------------------------------------

def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except (OSError, TypeError):
        return False
    return True


def acquire_lock(now, path=None):
    """Занять lock атомарно. False — если жив другой прогон.

    Создание через O_CREAT|O_EXCL: проверка «файла нет» и запись должны быть
    одной операцией, иначе два почти одновременных запуска (cron наложился на
    ручной) оба пройдут проверку и оба отправят пост.
    """
    path = pathlib.Path(path or LOCK_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"pid": os.getpid(), "started": now.isoformat()})

    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(payload)
            return True
        except FileExistsError:
            if not _steal_if_stale(path, now):
                return False
    return False


def _steal_if_stale(path, now):
    """Снять чужой lock, только если его владелец мёртв.

    Живой процесс, работающий дольше потолка, lock не теряет: отобрать его —
    значит получить два параллельных прогона, ровно то, от чего lock защищает.
    """
    try:
        held = json.loads(pathlib.Path(path).read_text())
    except (json.JSONDecodeError, ValueError, OSError):
        log.warning("lock нечитаем — перехватываем")
        _force_unlink(path)
        return True

    pid, started = held.get("pid"), held.get("started")
    if _pid_alive(pid):
        try:
            age = (now - dt.datetime.fromisoformat(started)).total_seconds()
        except (TypeError, ValueError):
            age = 0
        if age >= MAX_RUNTIME_SECONDS:
            log.error("прогон pid %s жив, но идёт %.0f c — дольше потолка; "
                      "не отбираем lock, разбирайтесь вручную", pid, age)
            # Отобрать lock у живого нельзя (получим два параллельных прогона),
            # но и молчать нельзя: иначе один висяк убивает сервис навсегда.
            _try_alert(f"⚠️ Дайджест не отправлен: прошлый прогон (pid {pid}) "
                       f"висит {age / 60:.0f} мин и держит блокировку. "
                       f"Нужно вмешательство: снимите процесс вручную.")
        else:
            log.error("прогон уже идёт (pid %s) — выходим", pid)
        return False

    log.warning("владелец lock (pid %s) мёртв — перехватываем", pid)
    _force_unlink(path)
    return True


def _force_unlink(path):
    try:
        pathlib.Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def release_lock(path=None):
    """Снять СВОЙ lock.

    Без проверки владельца очнувшийся зависший процесс снёс бы lock того, кто
    его перехватил, и открыл дорогу третьему параллельному прогону.
    """
    path = pathlib.Path(path or LOCK_PATH)
    try:
        held = json.loads(path.read_text())
    except (json.JSONDecodeError, ValueError, OSError):
        return
    if held.get("pid") == os.getpid():
        _force_unlink(path)


def _try_alert(text, attempts=3, base_delay=2.0):
    """Уведомить, не роняя основной поток: доставка алёрта — best-effort.

    В отличие от дайджеста, алёрт повторяем смело: два одинаковых «не отправлено»
    безвредны, а тишина нарушает главное обещание сервиса — узнать о сбое
    сообщением, а не по отсутствию поста. Сбой сети — самый частый случай, и
    именно в нём одна попытка почти наверняка потерялась бы.
    """
    safe = sanitize_alert(text)
    for i in range(attempts):
        try:
            send_alert(safe)
            return True
        except Exception:                           # noqa: BLE001
            if i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
    log.error("не удалось доставить уведомление за %d попыток", attempts)
    return False


# ---------- доставка ---------------------------------------------------------

# Ошибки, которые случаются ДО передачи запроса: соединение не установлено,
# значит сообщение заведомо не доставлено и повтор безопасен.
# ВАЖНО: urllib заворачивает их в URLError, наружу голый gaierror не выходит —
# проверять надо .reason, иначе ветка повтора недостижима вообще.
_NOT_DELIVERED_REASONS = (socket.gaierror, ConnectionRefusedError)


def _is_definitely_not_delivered(exc):
    if isinstance(exc, _NOT_DELIVERED_REASONS):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, _NOT_DELIVERED_REASONS)


def _send_once_or_safely_retry(post, attempts=3, base_delay=2.0):
    """Отправить пост, повторяя только заведомо недоставленные попытки.

    Отправка НЕ идемпотентна: если Telegram принял сообщение, а ответ потерялся
    по дороге (RST, таймаут чтения), повтор создаст ВТОРОЙ пост у читателя.
    Поэтому вслепую ретраить нельзя — только случаи, где соединение вообще не
    состоялось. Остальное разбирает журнал намерений: молчание безопаснее дубля.
    """
    for i in range(attempts):
        try:
            return send_telegram(post)
        except Exception as e:                      # noqa: BLE001
            if not _is_definitely_not_delivered(e) or i == attempts - 1:
                raise
            log.warning("соединение с Telegram не состоялось (%s) — повтор %d/%d",
                        type(e).__name__, i + 2, attempts)
            time.sleep(base_delay * (2 ** i))
    raise RuntimeError("недостижимо")


# ---------- прогон -----------------------------------------------------------

def _date_label(now):
    return f"{WEEKDAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]}"


def run(now=None, force=False, dry_run=False):
    """Один прогон. Возвращает код возврата процесса."""
    now = now or dt.datetime.now(dt.timezone.utc)
    data_dir = pathlib.Path(DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Lock живёт рядом с данными прогона: так он автоматически следует за
    # DATA_DIR и тесты не пишут в рабочий репозиторий.
    lock_path = data_dir / "run.lock"
    if not acquire_lock(now, path=lock_path):
        return 2

    try:
        history = History(data_dir / "sent_history.json")
        if history.recovered_from_corruption:
            log.warning("журнал отправок был битым — начат новый, старый в .corrupt")

        if not force and not dry_run:
            if history.already_sent_today(now):
                log.info("сегодня уже отправляли — выходим без действий")
                return 0
            if history.has_pending_today(now):
                log.warning("есть неразрешённое намерение за сегодня "
                            "(прошлый прогон мог отправить) — молчим до завтра")
                _try_alert("⚠️ Дайджест сегодня не отправлен: прошлый прогон "
                           "оборвался на отправке, исход неизвестен. "
                           "Проверьте канал; повтор — с флагом --force.")
                return 3

        candidates = collect_candidates(now=now)
        seen = history.seen_urls(now)
        fresh = history.filter_new(candidates, now=now)
        log.info("кандидатов: %d, после дедупа: %d", len(candidates), len(fresh))

        # seen передаём внутрь: Perplexity добирает материалы уже после этого
        # фильтра, и без второй проверки они минуют дедуп целиком.
        digest = curate_digest(fresh, seen_urls=seen)

        # Страховка на случай, если модель всё-таки вернула отправленное раньше.
        kept = [b for b in digest.get("blocks", [])
                if canonical_url(b.get("url", "")) not in seen]
        if len(kept) != len(digest.get("blocks", [])):
            log.warning("отброшено %d блоков, уже отправленных ранее",
                        len(digest.get("blocks", [])) - len(kept))
        digest["blocks"] = kept
        digest["radar"] = [r for r in (digest.get("radar") or [])
                           if canonical_url(r.get("url", "")) not in seen]

        # Смоук состава validate_digest отработал ДО этого фильтра, поэтому
        # нижнюю границу проверяем ещё раз: дедуп мог срезать блоки после него.
        if len(digest["blocks"]) < MIN_BLOCKS:
            log.error("после дедупа осталось %d блоков (нужно от %d) — не шлём",
                      len(digest["blocks"]), MIN_BLOCKS)
            _try_alert(f"⚠️ Дайджест сегодня не отправлен: после дедупа осталось "
                       f"{len(digest['blocks'])} новых материалов, нужно "
                       f"минимум {MIN_BLOCKS}.")
            return 1

        post = build_post(render_digest(digest, _date_label(now)))
        # Радар тоже уходит читателю, значит тоже попадает в историю —
        # иначе завтра он вернётся как «новый». Но записываем ТОЛЬКО то, что
        # уцелело после усечения по лимиту: помеченный отправленным блок,
        # который выпал из поста, не вернётся 30 дней и потеряется молча.
        candidate_urls = ([b["url"] for b in digest["blocks"]]
                          + [r["url"] for r in (digest.get("radar") or [])
                             if r.get("url")])
        urls = [u for u in candidate_urls if html.escape(u, quote=True) in post]
        if len(urls) != len(candidate_urls):
            log.warning("%d материалов не влезли в лимит и в историю не пишутся",
                        len(candidate_urls) - len(urls))
        digest_hash = hashlib.sha256(post.encode()).hexdigest()[:16]

        (data_dir / f"digest-{now.date().isoformat()}.json").write_text(
            json.dumps(digest, ensure_ascii=False, indent=1))

        if dry_run:
            log.info("--dry-run: пост готов (%d символов), отправка пропущена", len(post))
            print(post)
            return 0

        # Намерение фиксируем ДО отправки: если процесс погибнет между вызовом
        # Telegram и записью результата, завтрашний прогон об этом узнает.
        history.record_intent(digest_hash, now)
        resp = _send_once_or_safely_retry(post)
        history.record_sent(urls, message_id=resp.get("message_id"),
                            digest_hash=digest_hash, now=now)

        log.info("отправлено: %d блоков, message_id=%s",
                 len(digest["blocks"]), resp.get("message_id"))
        return 0
    finally:
        release_lock(lock_path)


def main(argv=None):
    p = argparse.ArgumentParser(description="Ежедневный AI-dev дайджест")
    p.add_argument("--dry-run", action="store_true",
                   help="пройти весь путь и не отправлять")
    p.add_argument("--force", action="store_true",
                   help="отправить, даже если сегодня уже отправляли")
    p.add_argument("--now", help="переопределить текущее время (ISO), для отладки")
    args = p.parse_args(argv)

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"),
                  logging.StreamHandler(sys.stderr)],
        # force: без него basicConfig — no-op при уже настроенном root-логгере,
        # и записи молча уходят мимо файла.
        force=True)
    redactor = SecretRedactingFilter()
    for h in logging.getLogger().handlers:
        h.addFilter(redactor)

    now = dt.datetime.fromisoformat(args.now) if args.now else None
    if now is not None and now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)   # naive-отметки портят журнал

    try:
        return run(now=now, force=args.force, dry_run=args.dry_run)
    except Exception as e:                          # noqa: BLE001
        log.exception("прогон упал")
        # Через _try_alert, а не одним вызовом: падение прогона чаще всего
        # вызвано сетью, и одиночная попытка потерялась бы ровно тогда,
        # когда уведомление нужнее всего.
        _try_alert(f"⚠️ Дайджест не отправлен.\n{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
