#!/usr/bin/env python3
"""Дедуп отправленных материалов и журнал отправок.

Состояние — один JSON-файл. Запись атомарная (tmp + os.replace): падение посреди
записи не должно оставлять битый журнал, иначе теряется вся история дедупа.
"""
import datetime as dt
import json
import os
import pathlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

WINDOW_DAYS = 30

# Параметры, не меняющие содержимое страницы: их наличие не делает материал новым.
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_EXACT = {"fbclid", "gclid", "yclid", "msclkid", "ref", "ref_src",
                   "referrer", "source", "mc_cid", "mc_eid", "igshid"}


def canonical_url(url):
    """Каноническая форма URL для сравнения материалов.

    Схема и хост регистронезависимы (RFC 3986) — их приводим к нижнему регистру.
    Путь регистрозависим, поэтому его НЕ трогаем: lower() по всему URL сломал бы
    ссылку на сайтах с чувствительными путями.
    """
    parts = urlsplit(url.strip())

    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    path = parts.path.rstrip("/")

    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not _is_tracking(k)])

    # Схему нормализуем к https: http/https-варианты одной страницы — один материал.
    return urlunsplit(("https", host, path, query, ""))


def _is_tracking(key):
    k = key.lower()
    return k in _TRACKING_EXACT or any(k.startswith(p) for p in _TRACKING_PREFIXES)


def _atomic_write_json(path, data):
    """Записать JSON атомарно: сначала во временный файл, потом подменить."""
    path = pathlib.Path(path)
    # Имя временного файла — с pid: два процесса, пишущих одно состояние, иначе
    # делят один tmp, и os.replace одного уносит содержимое другого.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.writing")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    os.replace(tmp, path)               # атомарно в пределах одной ФС


class History:
    """Журнал отправленных материалов."""

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.recovered_from_corruption = False
        self._data = self._load()

    def _load(self):
        if not self.path.exists():
            return {"entries": [], "last_sent": None}
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict) or "entries" not in data:
                raise ValueError("неожиданная структура журнала")
            return data
        except (json.JSONDecodeError, ValueError, OSError):
            # Битый журнал не роняет утренний прогон и не затирается молча:
            # уводим в .corrupt для разбора и продолжаем с чистого листа.
            quarantine = self.path.with_suffix(".corrupt")
            try:
                os.replace(self.path, quarantine)
            except OSError:
                pass
            self.recovered_from_corruption = True
            return {"entries": [], "last_sent": None}

    # --- чтение ---------------------------------------------------------

    def seen_urls(self, now, window_days=WINDOW_DAYS):
        """Канонические URL, отправленные внутри окна дедупа."""
        edge = now - dt.timedelta(days=window_days)
        out = set()
        for e in self._data.get("entries", []):
            try:
                sent_at = dt.datetime.fromisoformat(e["sent_at"])
                if sent_at.tzinfo is None:
                    # Запись без таймзоны (например, от отладочного --now) иначе
                    # роняла бы сравнение TypeError каждое следующее утро.
                    sent_at = sent_at.replace(tzinfo=dt.timezone.utc)
                if sent_at >= edge:
                    out.add(e["url"])
            except (KeyError, ValueError, TypeError):
                continue
        return out

    def filter_new(self, candidates, now, window_days=WINDOW_DAYS):
        """Оставить только материалы, которых не было в окне дедупа."""
        seen = self.seen_urls(now, window_days)
        fresh = []
        for c in candidates:
            url = c.get("url")
            if not url:
                continue
            if canonical_url(url) not in seen:
                fresh.append(c)
        return fresh

    def already_sent_today(self, now):
        last = self._data.get("last_sent")
        return bool(last) and last.get("date") == now.date().isoformat()

    def has_pending_today(self, now):
        """Есть ли неразрешённое намерение отправить за сегодня.

        Намерение пишется ДО обращения к Telegram. Если процесс погиб между
        отправкой и записью результата, следующий запуск видит намерение и не
        шлёт повторно: молчание безопаснее дубля в личном канале.
        """
        pending = self._data.get("pending")
        return bool(pending) and pending.get("date") == now.date().isoformat()

    # --- запись ---------------------------------------------------------

    def record_intent(self, digest_hash, now):
        """Зафиксировать намерение отправить — до вызова Telegram."""
        self._data["pending"] = {
            "date": now.date().isoformat(),
            "digest_hash": digest_hash,
            "started": now.isoformat(),
        }
        _atomic_write_json(self.path, self._data)

    def clear_intent(self):
        """Снять намерение: исход отправки достоверно известен как неудачный."""
        if self._data.pop("pending", None) is not None:
            _atomic_write_json(self.path, self._data)

    def record_sent(self, urls, message_id, digest_hash, now):
        """Зафиксировать факт отправки.

        Вызывается СРАЗУ после успешного ответа Telegram: падение после отправки,
        но до записи, дало бы дубль на следующем запуске.
        """
        stamp = now.isoformat()
        for url in urls:
            self._data["entries"].append({"url": canonical_url(url), "sent_at": stamp})
        self._data["last_sent"] = {
            "date": now.date().isoformat(),
            "message_id": message_id,
            "digest_hash": digest_hash,
            "sent_at": stamp,
        }
        self._data.pop("pending", None)     # исход известен — намерение разрешено
        self._prune(now)
        _atomic_write_json(self.path, self._data)

    def _prune(self, now, window_days=WINDOW_DAYS):
        """Выбросить записи вне окна дедупа: иначе журнал растёт бесконечно."""
        edge = now - dt.timedelta(days=window_days)
        kept = []
        for e in self._data.get("entries", []):
            try:
                sent_at = dt.datetime.fromisoformat(e["sent_at"])
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=dt.timezone.utc)
                if sent_at >= edge:
                    kept.append(e)
            except (KeyError, ValueError, TypeError):
                continue                    # битую запись не тащим дальше
        self._data["entries"] = kept
