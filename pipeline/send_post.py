#!/usr/bin/env python3
"""Отправка готового дайджеста в Telegram.

Раньше здесь лежал текст конкретного поста от 19.07.2026. Теперь модуль читает
структуру дайджеста из data/digest-<дата>.json и рендерит её — вся логика
отправки и форматирования общая с run_daily.py.

Обычный путь — `python3 pipeline/run_daily.py`. Этот скрипт нужен, когда пост
надо переотправить из уже посчитанного дайджеста.
"""
import argparse
import datetime as dt
import json
import pathlib
import sys

from curate import validate_digest
from formatting import build_post, render_digest
from run_daily import DATA_DIR, _date_label, sanitize_alert, send_telegram


def load_digest(path):
    return json.loads(pathlib.Path(path).read_text())


def main(argv=None):
    p = argparse.ArgumentParser(description="Отправить готовый дайджест")
    p.add_argument("digest", nargs="?",
                   help="путь к digest-<дата>.json (по умолчанию — сегодняшний)")
    p.add_argument("--dry-run", action="store_true",
                   help="показать пост и не отправлять")
    args = p.parse_args(argv)

    now = dt.datetime.now(dt.timezone.utc)
    path = args.digest or (DATA_DIR / f"digest-{now.date().isoformat()}.json")
    if not pathlib.Path(path).exists():
        print(f"нет файла дайджеста: {path}", file=sys.stderr)
        return 1

    digest = load_digest(path)
    try:
        # Тот же смоук, что и в основном прогоне: файл мог остаться от сбойной
        # курации, а ручная переотправка — не повод слать читателю мусор.
        validate_digest(digest)
    except ValueError as e:
        print(f"дайджест не прошёл проверку: {e}", file=sys.stderr)
        return 1

    post = build_post(render_digest(digest, _date_label(now)))

    if args.dry_run:
        print(post)
        return 0

    try:
        resp = send_telegram(post)
    except Exception as e:                          # noqa: BLE001
        # Текст исключения может содержать URL с токеном в пути.
        print(sanitize_alert(f"отправка не удалась: {type(e).__name__}: {e}"),
              file=sys.stderr)
        return 1

    print(f"отправлено, message_id={resp.get('message_id')}, {len(post)} символов",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
