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
import json
import logging
import os
import pathlib
import re
import sys
import urllib.parse
import urllib.request

from collect import collect_candidates
from config import secret
from curate import curate as curate_digest
from dedup import History
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


def sanitize_alert(text, secrets=()):
    """Вычистить значения секретов из текста алёрта.

    В сообщение об ошибке провайдера легко попадает URL с ключом в query —
    и алёрт о сбое сам становится утечкой.
    """
    out = str(text)
    for value in secrets:
        if value:
            out = out.replace(value, "***")
    out = _BEARER.sub(r"\1***", out)
    out = _KEY_IN_URL.sub(r"\1***", out)
    return out


# ---------- блокировка -------------------------------------------------------

def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except (OSError, TypeError):
        return False
    return True


def acquire_lock(now, path=None):
    """Занять lock. False — если жив другой прогон.

    Протухший lock (процесс мёртв или висит дольше потолка) перехватываем:
    иначе одно зависшее утро заблокировало бы все следующие.
    """
    path = pathlib.Path(path or LOCK_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        try:
            held = json.loads(path.read_text())
            started = dt.datetime.fromisoformat(held["started"])
            age = (now - started).total_seconds()
            if _pid_alive(held.get("pid")) and age < MAX_RUNTIME_SECONDS:
                log.error("прогон уже идёт (pid %s, %.0f c) — выходим",
                          held.get("pid"), age)
                return False
            log.warning("перехватываем протухший lock (pid %s)", held.get("pid"))
        except (json.JSONDecodeError, KeyError, ValueError, OSError):
            log.warning("lock нечитаем — перехватываем")

    path.write_text(json.dumps({"pid": os.getpid(), "started": now.isoformat()}))
    return True


def release_lock(path=None):
    try:
        pathlib.Path(path or LOCK_PATH).unlink(missing_ok=True)
    except OSError:
        pass


# ---------- прогон -----------------------------------------------------------

def _date_label(now):
    return f"{WEEKDAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]}"


def run(now=None, force=False, dry_run=False):
    """Один прогон. Возвращает код возврата процесса."""
    now = now or dt.datetime.now(dt.timezone.utc)
    data_dir = pathlib.Path(DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)

    if not acquire_lock(now):
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
                return 0

        candidates = collect_candidates(now=now)
        fresh = history.filter_new(candidates, now=now)
        log.info("кандидатов: %d, после дедупа: %d", len(candidates), len(fresh))

        digest = curate_digest(fresh)
        if not digest.get("blocks"):
            log.error("дайджест пуст — отправлять нечего")
            return 1

        post = build_post(render_digest(digest, _date_label(now)))
        urls = [b["url"] for b in digest["blocks"]]
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
        resp = send_telegram(post)
        history.record_sent(urls, message_id=resp.get("message_id"),
                            digest_hash=digest_hash, now=now)

        log.info("отправлено: %d блоков, message_id=%s",
                 len(digest["blocks"]), resp.get("message_id"))
        return 0
    finally:
        release_lock()


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
                  logging.StreamHandler(sys.stderr)])

    now = dt.datetime.fromisoformat(args.now) if args.now else None

    try:
        return run(now=now, force=args.force, dry_run=args.dry_run)
    except Exception as e:                          # noqa: BLE001
        log.exception("прогон упал")
        try:
            leaked = [os.environ.get(k) for k in
                      ("TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY",
                       "PERPLEXITY_API_KEY", "X_BEARER_TOKEN",
                       "EXA_API_KEY", "GITHUB_TOKEN")]
            send_alert(sanitize_alert(
                f"⚠️ Дайджест не отправлен.\n{type(e).__name__}: {e}",
                secrets=[v for v in leaked if v]))
        except Exception:                           # noqa: BLE001
            # Алёрт — best-effort: его падение не должно маскировать исходную ошибку.
            log.error("не удалось доставить алёрт о сбое")
        return 1


if __name__ == "__main__":
    sys.exit(main())
