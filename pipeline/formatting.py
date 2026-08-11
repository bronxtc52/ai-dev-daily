#!/usr/bin/env python3
"""Форматирование дайджеста под Telegram.

Санитайзер — референс из knowledge-base (snippets/telegram-llm-markdown-to-html.md,
инцидент Avicenna-AI 2026-06-11). Порядок правил важен и объяснён построчно:
любое LLM-содержимое обязано пройти через md_to_telegram_html, иначе Telegram
отвергнет сообщение целиком на первом же сыром '<'.
"""
import html
import re

# Жёсткий лимит Telegram на длину сообщения.
TELEGRAM_LIMIT = 4096

SEPARATOR = "\n\n➖➖➖➖➖➖➖➖➖➖\n\n"

_MD_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_MD_HEADER = re.compile(r"(?m)^#{1,6}\s+(.+)$")
_MD_BULLET = re.compile(r"(?m)^(\s*)[-*]\s+")
_MD_ITALIC_STAR = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])")
_MD_ITALIC_UNDER = re.compile(r"(?<!\w)_([^_\n]+)_(?!\w)")
_MD_CODE = re.compile(r"`([^`\n]+)`")


def md_to_telegram_html(text):
    """Экранирует HTML и переводит базовый markdown в Telegram-HTML."""
    s = html.escape(text)              # 1) escape первым: «<3,0 с» больше не роняет парсер
    s = _MD_BOLD.sub(r"<b>\1</b>", s)  # 2) **…** раньше одиночных * — иначе курсив съест половину
    s = _MD_HEADER.sub(r"<b>\1</b>", s)  # 3) Telegram не знает <h1>..<h6>
    s = _MD_BULLET.sub(r"\1• ", s)     # 4) списки до курсива: конфликт по символу *
    s = _MD_ITALIC_STAR.sub(r"<i>\1</i>", s)
    s = _MD_ITALIC_UNDER.sub(r"<i>\1</i>", s)  # lookaround: snake_case не курсивим
    s = _MD_CODE.sub(r"<code>\1</code>", s)
    return s


def link(url, text):
    """Ссылка Telegram-HTML. URL в атрибуте тоже экранируется."""
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(text)}</a>'


def build_post(blocks, limit=TELEGRAM_LIMIT):
    """Собрать пост из готовых блоков, уложившись в лимит Telegram.

    Режем ПО ГРАНИЦАМ БЛОКОВ: срез по символам разорвал бы HTML-тег или
    entity, и Telegram отверг бы сообщение целиком.
    """
    if not blocks:
        raise ValueError("нечего отправлять: список блоков пуст")

    kept = []
    length = 0
    for block in blocks:
        addition = len(block) + (len(SEPARATOR) if kept else 0)
        if length + addition > limit:
            break                      # дальше не влезет — обрываем на целом блоке
        kept.append(block)
        length += addition

    if not kept:
        # Даже первый блок не помещается — обрезаем его по строкам, а не по символам.
        kept = [_truncate_by_lines(blocks[0], limit)]

    return SEPARATOR.join(kept)


def _truncate_by_lines(text, limit):
    """Обрезать по границам строк, чтобы не разорвать тег или entity."""
    lines = text.split("\n")
    out = []
    length = 0
    for line in lines:
        if length + len(line) + 1 > limit:
            break
        out.append(line)
        length += len(line) + 1
    return "\n".join(out) if out else text[:limit]


def render_digest(digest, date_label):
    """Превратить структуру дайджеста в список готовых блоков Telegram-HTML.

    Весь текст от модели проходит через санитайзер — это единственное место,
    где содержимое LLM становится разметкой.
    """
    blocks = [
        f"🗞 <b>AI-DEV ДАЙДЖЕСТ</b>\n<i>{html.escape(date_label)}</i>\n\n"
        "Доброе утро!\n"
        "Каждое утро я прохожусь по миру ИИ-разработки и оставляю только то, "
        "что можно взять и применить сегодня. Без хайпа и воды. Поехали 👇"
    ]

    for n, b in enumerate(digest.get("blocks", []), start=1):
        emoji = b.get("emoji", "🔹")
        title = link(b["url"], b["title"])
        benefit = md_to_telegram_html(b["benefit"])
        blocks.append(f"{emoji} <b>{n}. {title}</b>\n{benefit}")

    radar = digest.get("radar") or []
    if radar:
        lines = ["📡 <b>На радаре</b>"]
        for r in radar:
            note = md_to_telegram_html(r.get("note", ""))
            lines.append(f"• {link(r['url'], r['title'])} — {note}")
        blocks.append("\n".join(lines))

    blocks.append(
        "Выберите одно и внедрите сегодня — этого уже достаточно, "
        "чтобы утро было не зря.")
    return blocks
