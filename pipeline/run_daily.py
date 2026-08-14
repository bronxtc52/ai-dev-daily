#!/usr/bin/env python3
"""Оркестратор ежедневного дайджеста: collect → dedup → curate → send.

Рассчитан на запуск из cron, где никто не смотрит на вывод:
- все пути абсолютные (cron стартует из чужого cwd);
- падение уходит алёртом в Telegram, а не только в лог;
- намерение отправить пишется до отправки, чтобы падение не дало дубль утром.
"""
import argparse
import contextlib
import datetime as dt
import hashlib
import html
import json
import logging
import os
import pathlib
import re
import signal
import socket
import sys
import time
import urllib.parse
import urllib.request

import collect
from collect import collect_candidates
import config
from config import secret
from curate import MIN_BLOCKS, curate as curate_digest
from dedup import History, _atomic_write_json, canonical_url
from formatting import build_post, render_digest

# Пути резолвятся от файла, а не от cwd: под cron рабочая директория чужая,
# и относительный путь увёл бы историю дедупа в другое место — молча.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
LOCK_PATH = DATA_DIR / "run.lock"
LOG_PATH = REPO_ROOT / "logs" / "run_daily.log"

MAX_RUNTIME_SECONDS = 600       # потолок прогона; лежащий дольше lock считаем протухшим
LOCK_BUSY_CODE = 2              # код возврата «работает другой прогон»

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


def _optional_secret(key, fallback_key):
    """Значение `key`, а если он не настроен — значение `fallback_key`."""
    try:
        return secret(key)
    except RuntimeError:
        return secret(fallback_key)


def alert_destination():
    """Куда слать аварии: пара (бот, чат).

    Отсутствие настройки здесь — штатная конфигурация, а не поломка: пока
    отдельный адресат не задан, всё работает как раньше. Иначе выкат новой
    версии до правки окружения уронил бы именно контур уведомлений — тот, что
    обязан сообщать о поломках.

    ⚠️ Ключи НЕ разрешаются независимо друг от друга (находка Codex на PR #7).
    Заданный алёрт-бот при незаданном алёрт-чате дал бы смешанный адресат:
    отдельный бот пишет в чат ДАЙДЖЕСТА, то есть внутренняя авария уходит
    участникам группы с дайджестом — ровно та утечка, ради которой адресаты и
    разводились.

    Но и симметричное «оба или ни одного» неверно: половины здесь неравноценны.
    Опасен только ЧАТ — он решает, кто прочтёт. Бот лишь доставляет, и
    конфигурация «тот же бот, но в личку владельца» совершенно законна;
    правило «оба или ничего» сломало бы её, вернув аварии в общий чат. Поэтому
    решает чат: нет своего чата — вся пара общая, и заданный алёрт-бот
    игнорируется как неполная настройка.
    """
    try:
        chat = secret("TELEGRAM_ALERT_CHAT_ID")
    except RuntimeError:
        return secret("TELEGRAM_BOT_TOKEN"), secret("TELEGRAM_CHAT_ID")
    return _optional_secret("TELEGRAM_ALERT_BOT_TOKEN", "TELEGRAM_BOT_TOKEN"), chat


def send_alert(text):
    """Короткое уведомление о сбое — обычным текстом, без разметки.

    Адресат — ВЛАДЕЛЕЦ, а не адресат дайджеста. Дайджест уходит в общий чат
    (у нас — группа «Вайбкодинг от Армана»), и «⚠️ Дайджест не отправлен» на
    общем адресате увидели бы все её участники: внутренняя авария стала бы
    публикацией.

    Бот тоже может быть другим. Бот, публикующий дайджест, не обязан иметь
    право писать владельцу в личку — Telegram запрещает боту первым писать
    пользователю, пока тот не нажал Start, — и без этой развилки контур
    уведомлений зависел бы от ручного действия человека.
    """
    token, chat = alert_destination()
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


# ---------- снятие извне -----------------------------------------------------

class Terminated(BaseException):
    """Прогон снят сигналом извне: внешний timeout, оператор, systemd.

    Наследуется от BaseException, а НЕ от Exception, намеренно (находка
    CodeRabbit на PR #7). Путь сбора ловит `Exception` дважды: `with_retry`
    повторяет вызов, а `gather` списывает запрос в «отброшен» и идёт дальше.
    Обычное исключение здесь проглатывалось бы целиком — прогон продолжался
    бы как ни в чём не бывало, и внешний timeout снова стал бы бесполезным.

    Родство с BaseException — это заявление «меня не ловить по дороге»,
    ровно как у KeyboardInterrupt, из которого этот сценарий и растёт.
    Ловит его только main, явно."""


def install_termination_handler():
    """Превратить SIGTERM в обычное исключение.

    Обёртка накрывает прогон внешним `timeout`, а тот на истечении шлёт именно
    SIGTERM. По умолчанию Python на нём просто умирает: это не исключение,
    ветка `except` в main() не выполняется, отметка `failure` не пишется и
    алёрт не уходит. Получалось, что зависание — ЕДИНСТВЕННЫЙ сценарий, ради
    которого timeout и ставился, — оставалось молчаливым, и узнать о нём можно
    было бы лишь назавтра по протухшей отметке (находка Codex на PR #7).

    Запаса времени хватает: `--kill-after=60s` даёт минуту на запись отметки и
    доставку алёрта, прежде чем придёт неперехватываемый KILL.
    """
    def handler(signum, _frame):
        raise Terminated(f"прогон снят сигналом {signal.Signals(signum).name}")

    try:
        return signal.signal(signal.SIGTERM, handler)
    except ValueError:
        return None                 # не главный поток; под cron не наш случай


# ---------- Sentry -----------------------------------------------------------

def _resolve_sentry_dsn():
    """DSN из окружения или Key Vault; None, если не настроен."""
    try:
        return secret("SENTRY_DSN")
    except RuntimeError:
        return None                 # Sentry не обязателен для работы сервиса


def _sentry_init(**kwargs):
    import sentry_sdk
    sentry_sdk.init(**kwargs)


def init_sentry():
    """Подключить Sentry, если он настроен.

    Best-effort целиком: ни отсутствие DSN, ни недоступность SDK или самого
    Sentry не должны стоить утреннего дайджеста. DSN не логируем — в нём ключ.
    """
    try:
        dsn = _resolve_sentry_dsn()
        if not dsn:
            log.info("Sentry не настроен — работаем без него")
            return False
        _sentry_init(
            dsn=dsn,
            environment=os.environ.get("SENTRY_ENVIRONMENT", "prod"),
            release=os.environ.get("SENTRY_RELEASE") or _git_release(),
            send_default_pii=False,     # в событиях и так нет пользовательских данных
            traces_sample_rate=0.0,     # трейсы для суточного cron избыточны
        )
        log.info("Sentry подключён")
        return True
    except Exception as e:              # noqa: BLE001
        log.warning("Sentry не подключился (%s) — продолжаем без него",
                    type(e).__name__)
        return False


def _git_release():
    """Версия для тегирования релиза — короткий sha рабочей копии."""
    try:
        import subprocess
        return subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            text=True, timeout=10).strip()
    except Exception:                   # noqa: BLE001
        return None


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


# ---------- heartbeat --------------------------------------------------------
#
# След прогона для ВНЕШНЕГО монитора (server-watchdog). Собственный алёрт сервиса
# ловит только упавший процесс; отсутствие процесса — cron не сработал, venv
# сломался, identity потеряла доступ — послать алёрт некому. Файл отвечает на
# вопрос, на который изнутри ответить нельзя: «прогон вообще состоялся?».
#
# Пишем на ЗАВЕРШЕНИЕ и только в боевом режиме: dry-run обновлял бы отметку
# свежести, и ручная отладка вечером маскировала бы пропущенное утро.

# Момент завершения прогона, снятый ПОКА ДЕРЖИМ lock. Именно lock задаёт порядок
# завершений, поэтому штамп, снятый после его освобождения, этот порядок не отражает:
# вытесненный с CPU прогон очнулся бы позже чужой записи, получил бы более поздний
# штамп и на законных основаниях затёр более свежий исход.
_LAST_COMPLETION = {}

HEARTBEAT_NAME = "heartbeat.json"
SERVICE_NAME = "ai-dev-daily"    # подпись отметки: чужой JSON не сойдёт за нашу
MAX_REASON_CHARS = 500          # причина — для человека в алёрте, не лог целиком


def heartbeat_path():
    """Абсолютный путь к отметке. Считается на вызове: DATA_DIR подменяют тесты."""
    return pathlib.Path(DATA_DIR) / HEARTBEAT_NAME


HEARTBEAT_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
HEARTBEAT_LOCK_ATTEMPTS = 20        # ~0.2 c суммарно: дольше ждать нечего, файл крошечный
HEARTBEAT_STATUSES = ("success", "failure")


def _parse_heartbeat_time(value):
    """Время из отметки как datetime; None — если это не наше время."""
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.strptime(value, HEARTBEAT_TIME_FORMAT).replace(
            tzinfo=dt.timezone.utc)
    except ValueError:
        try:                                        # отметки прежнего формата, без долей
            return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=dt.timezone.utc)
        except ValueError:
            return None


def _existing_heartbeat_is_newer(finished_at):
    """Лежит ли на месте ВАЛИДНАЯ отметка более позднего прогона.

    Сравнивать сырые строки нельзя: `{"finished_at": "z"}` лексикографически
    больше любой даты, и одна такая запись запретила бы обновление НАВСЕГДА —
    сторож остался бы в ошибке навечно. Залипание хуже гонки, от которой
    защищаемся, поэтому «сохраняем чужое» только если чужое — действительно
    наша отметка: своё имя сервиса, известный статус, разбираемое время.
    """
    try:
        current = json.loads(heartbeat_path().read_text(encoding="utf-8"))
    except Exception:                               # noqa: BLE001
        return False                                # нет файла или мусор — пишем поверх
    if not isinstance(current, dict):
        return False
    if current.get("service") != SERVICE_NAME:
        return False
    if current.get("status") not in HEARTBEAT_STATUSES:
        return False
    theirs = _parse_heartbeat_time(current.get("finished_at"))
    ours = _parse_heartbeat_time(finished_at)
    if theirs is None or ours is None:
        return False
    return theirs > ours


@contextlib.contextmanager
def _heartbeat_write_lock():
    """Сериализовать «прочитать-сравнить-записать».

    Проверка и запись — две операции, между ними другой прогон успевает
    записаться, и мы затираем его результат уже после сравнения. Лок
    best-effort: не досталась — всё равно пишем (тишина монитора дороже
    редкой гонки), но большинство наложений он разводит.
    """
    lock = heartbeat_path().with_name(HEARTBEAT_NAME + ".lock")
    fd = None
    for _ in range(HEARTBEAT_LOCK_ATTEMPTS):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            time.sleep(0.01)
        except OSError:
            break                                   # каталог недоступен — не наша беда
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
            try:
                os.unlink(lock)
            except OSError:
                pass


def write_heartbeat(status, now=None, reason=None):
    """Оставить отметку о завершении прогона. Никогда не поднимает исключение.

    Служебная запись не имеет права стоить дайджеста: любая ошибка здесь —
    предупреждение в лог, а не падение прогона.
    """
    try:
        now = now or dt.datetime.now(dt.timezone.utc)
        payload = {
            # Отметка называет себя: монитор с опечаткой в пути иначе может
            # набрести на чужой валидный JSON со `status` внутри и замолчать
            # навсегда, выглядя при этом исправным.
            "service": SERVICE_NAME,
            "status": status,
            # Возраст монитор считает по ЭТОМУ полю, а не по mtime файла: mtime
            # переживает cp -p и rsync, то есть врёт при переносе состояния.
            # Доли секунды обязательны: два прогона в одной секунде иначе
            # неразличимы по времени, и порядок завершений теряется.
            "finished_at": now.astimezone(dt.timezone.utc)
                              .strftime(HEARTBEAT_TIME_FORMAT),
            "digest_date": now.date().isoformat(),
        }
        if reason:
            # Тот же санитайзер, что у алёрта: в тексте исключения от провайдера
            # легко оказывается URL с ключом в query.
            payload["reason"] = sanitize_alert(str(reason))[:MAX_REASON_CHARS]

        # Запись идёт уже ПОСЛЕ освобождения lock, поэтому порядок записи может
        # разойтись с порядком завершения: вытесненный с CPU провалившийся прогон
        # очнётся и затрёт успех более позднего ретрая. Сторож поднял бы тревогу
        # по несуществующей поломке, а причину искали бы в сервисе. Отметка обязана
        # представлять последний ЗАВЕРШИВШИЙСЯ прогон, поэтому старую не откатываем.
        with _heartbeat_write_lock():
            if _existing_heartbeat_is_newer(payload["finished_at"]):
                log.info("heartbeat не тронут: на месте отметка более позднего прогона")
                return
            _atomic_write_json(heartbeat_path(), payload)
    except Exception as e:                          # noqa: BLE001
        log.warning("не удалось записать heartbeat (%s) — прогон это не ломает",
                    type(e).__name__)


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


# Идёт ли ещё одна попытка прогона после текущей. Пока идёт, о неудаче
# сообщать рано: инцидент, который через полчаса вылечится сам, не должен
# будить человека трижды. Флаг модульный, а не параметр, потому что алёрт
# шлют и вложенные помощники (_steal_if_stale), до которых аргумент пришлось
# бы протаскивать через весь стек.
_ALERTS_SUPPRESSED = {"value": False}


def _try_alert(text, attempts=3, base_delay=2.0, suppressible=True):
    """Уведомить, не роняя основной поток: доставка алёрта — best-effort.

    В отличие от дайджеста, алёрт повторяем смело: два одинаковых «не отправлено»
    безвредны, а тишина нарушает главное обещание сервиса — узнать о сбое
    сообщением, а не по отсутствию поста. Сбой сети — самый частый случай, и
    именно в нём одна попытка почти наверняка потерялась бы.

    `suppressible=False` — для сообщений, которые НЕ описывают исход прогона
    (мёртвый источник, срок токена). Откладывать их «до последней попытки»
    бессмысленно и вредно: см. _notify_once.
    """
    safe = sanitize_alert(text)
    if suppressible and _ALERTS_SUPPRESSED["value"]:
        log.info("алёрт отложен до последней попытки: %s", safe)
        return False
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


# ---------- журнал уведомлений ------------------------------------------------
#
# Отдельный от истории отправок файл: он отвечает не «что читатель уже видел»,
# а «о чём мы уже говорили владельцу». Мёртвый источник остаётся мёртвым
# неделями, и ежедневное сообщение об этом обесценивает канал алёртов целиком —
# человек перестаёт их читать ровно к тому дню, когда случится настоящая авария.

NOTICES_NAME = "notices.json"
NOTICE_COOLDOWN_DAYS = 7
DIGEST_RETENTION_DAYS = 90
TOKEN_WARN_DAYS = 14


def _load_notices(path):
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:                               # noqa: BLE001
        return {}                                   # нет файла или мусор — начинаем заново
    return data if isinstance(data, dict) else {}


def should_notify(path, key, now, cooldown_days=NOTICE_COOLDOWN_DAYS):
    """Пора ли снова говорить владельцу об этом же."""
    stamp = _load_notices(path).get(key)
    if not isinstance(stamp, str):
        return True
    try:
        last = dt.datetime.fromisoformat(stamp)
    except ValueError:
        return True                                 # непонятная отметка — лучше сказать
    if last.tzinfo is None:
        last = last.replace(tzinfo=dt.timezone.utc)
    return (now - last) >= dt.timedelta(days=cooldown_days)


def remember_notice(path, key, now):
    """Отметить, что об этом уже сообщили. Никогда не роняет прогон."""
    try:
        data = _load_notices(path)
        data[key] = now.isoformat()
        _atomic_write_json(pathlib.Path(path), data)
    except Exception:                               # noqa: BLE001
        log.warning("не удалось записать журнал уведомлений — прогон это не ломает")


def _notify_once(data_dir, key, text, now):
    """Сообщить владельцу наблюдение, если об этом давно не говорили.

    ⚠️ Идёт МИМО подавления алёртов (`suppressible=False`), и это существенно
    (находка CodeRabbit на PR #7). Подавление отвечает на вопрос «стоит ли
    жаловаться на исход ЭТОГО захода, если будет следующий». Здесь вопрос
    другой: мёртвый источник и истекающий токен — свойства мира, а не исход
    попытки, и следующий заход их не исправит.

    Практически: в боевом расписании прогон идёт `--attempt 1 --attempts 3`,
    успешно отправляет дайджест на первой же попытке, а заходы 2 и 3 выходят
    раньше сбора по идемпотентности. С подавлением такое уведомление не ушло
    бы НИКОГДА. Своя защита от шума у него есть и без того — cooldown.
    """
    path = pathlib.Path(data_dir) / NOTICES_NAME
    if not should_notify(path, key, now):
        log.info("уведомление «%s» подавлено: недавно уже отправляли", key)
        return False
    if _try_alert(text, suppressible=False):
        remember_notice(path, key, now)
        return True
    return False


def report_dead_sources(data_dir, stats, now):
    """Сообщить о источниках, не давших НИ ОДНОГО материала.

    Сбор устроен так, что смерть одного источника не отменяет дайджест — это
    правильно для утреннего поста, но означает, что отказ виден только как
    строка WARNING в логе, которую под cron никто не читает. Протухший токен
    так может жить месяцами: пост выходит, просто беднее.
    """
    dead = sorted(name for name, count in (stats or {}).items() if not count)
    if not dead:
        return []
    _notify_once(
        data_dir, "source-dead:" + ",".join(dead),
        f"⚠️ Источники молчат: {', '.join(dead)}. Дайджест вышел на остальных. "
        f"Вероятная причина — протухший ключ или смена API.",
        now)
    return dead


def check_token_expiry(data_dir, now, warn_days=TOKEN_WARN_DAYS):
    """Предупредить о скором истечении GitHub PAT.

    Единственный наш ключ, который объявляет свой срок. Остальные о нём
    молчат, и их протухание ловится только детектом мёртвого источника —
    то есть постфактум. Здесь узнаём заранее.

    Проверка служебная: любая её ошибка — предупреждение в лог, не падение.
    """
    try:
        expires = collect.github_token_expiry()
        if expires is None:
            return None
        left = expires - now
        if left > dt.timedelta(days=warn_days):
            return left
        _notify_once(
            data_dir, f"token-expiry:github:{expires.date().isoformat()}",
            f"🔑 GitHub-токен истекает {expires.date().isoformat()} "
            f"(осталось дней: {max(left.days, 0)}). Обновите "
            f"ai-dev-daily--prod--GITHUB-TOKEN в Key Vault, иначе источник "
            f"GitHub замолчит.",
            now)
        return left
    except Exception as e:                          # noqa: BLE001
        log.warning("проверка срока токена не удалась (%s) — прогон это не ломает",
                    type(e).__name__)
        return None


def prune_old_digests(data_dir, now, keep_days=DIGEST_RETENTION_DAYS):
    """Убрать суточные снимки дайджеста старше окна хранения.

    Один файл в день — за пять лет почти две тысячи штук. Сами по себе они
    крошечные, но сервис, который должен жить годами без человека, не имеет
    права бесконечно накапливать что бы то ни было.

    Имя, которое не разбирается в дату, не трогаем: в каталоге лежат и чужие
    файлы (ручной `digest-2026-07-19.md`), и удалять непонятное — худший из
    возможных дефолтов для уборщика.
    """
    edge = (now - dt.timedelta(days=keep_days)).date()
    removed = 0
    for f in sorted(pathlib.Path(data_dir).glob("digest-*.json")):
        stamp = f.stem[len("digest-"):]
        try:
            when = dt.date.fromisoformat(stamp)
        except ValueError:
            continue
        if when < edge:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    if removed:
        log.info("убрано старых снимков дайджеста: %d", removed)
    return removed


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
        return LOCK_BUSY_CODE

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

        # Счётчики по источникам собираем ВСЕГДА: без них отказ одного из трёх
        # выглядит просто как более скромный день в новостях.
        source_stats = {}
        candidates = collect_candidates(now=now, stats=source_stats)
        seen = history.seen_urls(now)
        fresh = history.filter_new(candidates, now=now)
        log.info("кандидатов: %d, после дедупа: %d", len(candidates), len(fresh))

        # Сразу после сбора, а не в конце: мёртвый источник — самая вероятная
        # причина того, что дальше не наберётся блоков, и знать о нём надо
        # даже в прогоне, который до отправки не дойдёт.
        if not dry_run:
            report_dead_sources(data_dir, source_stats, now)

        # seen передаём внутрь: Perplexity добирает материалы уже после этого
        # фильтра, и без второй проверки они минуют дедуп целиком.
        digest = curate_digest(fresh, seen_urls=seen, now=now)

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

        # Смоук 3-6 блоков считался ДО сборки поста. Усечение по лимиту может
        # оставить в тексте меньше: тогда читателю уехал бы куцый дайджест,
        # а история пометила бы день отправленным.
        in_post = [b for b in digest["blocks"]
                   if html.escape(b["url"], quote=True) in post]
        if len(in_post) < MIN_BLOCKS:
            log.error("в пост влезло %d блоков из %d (нужно от %d) — не отправляем",
                      len(in_post), len(digest["blocks"]), MIN_BLOCKS)
            _try_alert(f"⚠️ Дайджест сегодня не отправлен: после усечения по лимиту "
                       f"в посте осталось {len(in_post)} материалов при минимуме "
                       f"{MIN_BLOCKS}. Вероятно, модель выдала слишком длинные тексты.")
            return 1
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
        try:
            resp = _send_once_or_safely_retry(post)
        except Exception as e:                      # noqa: BLE001
            if _is_definitely_not_delivered(e):
                # Исход известен: сообщение не ушло. Держать намерение незачем —
                # иначе повтор в тот же день молча упрётся в «исход неизвестен».
                history.clear_intent()
                log.warning("доставка заведомо не состоялась — намерение снято, "
                            "повтор сегодня разрешён")
            raise
        history.record_sent(urls, message_id=resp.get("message_id"),
                            digest_hash=digest_hash, now=now)

        log.info("отправлено: %d блоков, message_id=%s",
                 len(digest["blocks"]), resp.get("message_id"))

        # Обслуживание — строго ПОСЛЕ отправки и в своём try: уборка мусора и
        # проверка срока токена не имеют права стоить уже состоявшегося утра.
        try:
            prune_old_digests(data_dir, now)
            check_token_expiry(data_dir, now)
        except Exception:                           # noqa: BLE001
            log.warning("обслуживание после отправки не отработало полностью")
        return 0
    finally:
        # Штамп — до освобождения lock: пока он наш, ни один другой прогон не мог
        # завершиться, значит порядок штампов совпадает с порядком завершений.
        _LAST_COMPLETION["at"] = dt.datetime.now(dt.timezone.utc)
        release_lock(lock_path)


def main(argv=None):
    p = argparse.ArgumentParser(description="Ежедневный AI-dev дайджест")
    p.add_argument("--dry-run", action="store_true",
                   help="пройти весь путь и не отправлять")
    p.add_argument("--force", action="store_true",
                   help="отправить, даже если сегодня уже отправляли")
    p.add_argument("--now", help="переопределить текущее время (ISO), для отладки")
    p.add_argument("--attempt", type=int, default=1,
                   help="номер попытки за сегодня (cron делает несколько заходов)")
    p.add_argument("--attempts", type=int, default=1,
                   help="сколько всего попыток запланировано на сегодня")
    args = p.parse_args(argv)

    # Последняя попытка отвечает за громкость: только она будит человека и
    # только она фиксирует провал в heartbeat. Промежуточная делает то же
    # самое молча — иначе один инцидент даёт три алёрта, а отметка `failure`
    # заставляет сторож сообщать о поломке, которая через полчаса вылечится.
    is_final = args.attempt >= args.attempts
    _ALERTS_SUPPRESSED["value"] = not is_final

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

    init_sentry()
    # До первой сетевой работы: иначе снятие по таймауту на самом длинном шаге
    # (курация) прошло бы мимо обработчика.
    install_termination_handler()

    now = dt.datetime.fromisoformat(args.now) if args.now else None
    if now is not None and now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)   # naive-отметки портят журнал

    try:
        rc = run(now=now, force=args.force, dry_run=args.dry_run)
    # Terminated перечислен явно: он BaseException, и одним `except Exception`
    # не ловится — иначе снятие по таймауту прошло бы мимо записи исхода.
    except (Exception, Terminated) as e:            # noqa: BLE001
        # Штамп берём тот, что снят под lock'ом внутри run(). Свой здесь снимать
        # нельзя: между освобождением lock и этой строкой чужой прогон мог успеть
        # завершиться и записаться, а более поздний штамп дал бы нам право его
        # затереть — ровно тот откат, от которого защищаемся.
        finished = _LAST_COMPLETION.get("at") or dt.datetime.now(dt.timezone.utc)
        # Heartbeat — ПЕРВЫМ делом: всё остальное в этой ветке ходит по сети
        # (Sentry, алёрт) и может не дойти, а исход прогона потерять нельзя.
        # Но только на последней попытке: промежуточный `failure` сторож читает
        # как состоявшуюся поломку. Отметка при этом не подделывается — она
        # просто остаётся прежней, и если следующая попытка не состоится вовсе,
        # сторож честно увидит протухшую отметку и сообщит об этом.
        if not args.dry_run and is_final:
            write_heartbeat("failure", now=now or finished,
                            reason=f"{type(e).__name__}: {e}")
        log.exception("прогон упал")
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
            sentry_sdk.flush(timeout=10)
        except Exception:                           # noqa: BLE001
            pass                                    # Sentry не критичен для потока
        # Через _try_alert, а не одним вызовом: падение прогона чаще всего
        # вызвано сетью, и одиночная попытка потерялась бы ровно тогда,
        # когда уведомление нужнее всего.
        _try_alert(f"⚠️ Дайджест не отправлен.\n{type(e).__name__}: {e}")
        return 1

    # Провал без исключения — это тоже провал: `run` возвращает 1 (в пост влезло
    # меньше минимума блоков) и 3 (неразрешённое намерение), и оба означают, что
    # утром поста не будет. Код 2 пропускаем осознанно: он значит «работает ДРУГОЙ
    # прогон», чужой исход этому процессу неизвестен, а свой ещё не наступил.
    finished = _LAST_COMPLETION.get("at") or dt.datetime.now(dt.timezone.utc)
    # Успех отмечаем всегда — он окончателен, дальнейшие попытки его не изменят
    # (и просто выйдут по идемпотентности). Провал — только на последней.
    if not args.dry_run and rc != LOCK_BUSY_CODE and (rc == 0 or is_final):
        write_heartbeat(
            "success" if rc == 0 else "failure", now=now or finished,
            reason=None if rc == 0 else f"прогон завершился кодом {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
