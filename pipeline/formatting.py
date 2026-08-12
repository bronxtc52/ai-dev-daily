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


def tg_length(text):
    """Длина в единицах, которыми меряет Telegram — UTF-16 code units.

    len() в Python считает code points, а эмодзи вне BMP (🗞 🏗 📡 👇) весят
    два юнита: пост на 4090 «символов» может оказаться за лимитом.
    """
    return len(text.encode("utf-16-le")) // 2


def link(url, text):
    """Ссылка Telegram-HTML с экранированием текста и URL."""
    return link_html(url, html.escape(text))


def link_html(url, inner_html):
    """Ссылка, текст которой УЖЕ прошёл санитайзер."""
    return f'<a href="{html.escape(url, quote=True)}">{inner_html}</a>'


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
        addition = tg_length(block) + (tg_length(SEPARATOR) if kept else 0)
        if length + addition > limit:
            break                      # дальше не влезет — обрываем на целом блоке
        kept.append(block)
        length += addition

    if not kept:
        # Даже первый блок не помещается целиком — режем его безопасно.
        kept = [_safe_truncate(blocks[0], limit)]

    return SEPARATOR.join(kept)


_TAG = re.compile(r"<(/?)(b|i|u|s|a|code|pre)\b[^>]*>")


def _safe_truncate(text, limit):
    """Обрезать текст, не оставив разорванного тега или незакрытой пары.

    Сначала пробуем границы строк. Если переносов нет вовсе (один гигантский
    блок), режем по символам и чиним хвост: убираем оборванный тег и дозакрываем
    всё, что осталось открытым, — иначе Telegram отвергнет сообщение целиком.
    """
    lines = text.split("\n")
    if len(lines) > 1:
        out, length = [], 0
        for line in lines:
            if length + tg_length(line) + 1 > limit:
                break
            out.append(line)
            length += tg_length(line) + 1
        if out:
            return _close_open_tags("\n".join(out))

    cut = text
    while tg_length(cut) > limit:
        cut = cut[:max(1, int(len(cut) * limit / max(tg_length(cut), 1)))]

    # Дозакрытие тегов добавляет символы уже ПОСЛЕ подсчёта, поэтому ужимаем,
    # пока итоговая строка вместе с закрывающими тегами не уложится в лимит.
    result = _close_open_tags(_drop_dangling_tag(cut))
    while tg_length(result) > limit and cut:
        overflow = tg_length(result) - limit
        cut = cut[:max(0, len(cut) - max(overflow, 1))]
        result = _close_open_tags(_drop_dangling_tag(cut))
    return result


def _drop_dangling_tag(text):
    """Выбросить тег, обрубленный посередине."""
    last_open = text.rfind("<")
    return text[:last_open] if last_open > text.rfind(">") else text


def _close_open_tags(text):
    """Дозакрыть теги, оставшиеся открытыми после обрезки."""
    stack = []
    for closing, name in _TAG.findall(text):
        if closing:
            if stack and stack[-1] == name:
                stack.pop()
        else:
            stack.append(name)
    return text + "".join(f"</{name}>" for name in reversed(stack))


def _safe_emoji(value, fallback="🔹"):
    """Поле emoji приходит от модели — впускаем максимум пару безопасных символов."""
    s = str(value or "").strip()
    if not s or len(s) > 4 or any(c in s for c in "<>&\"'"):
        return fallback
    return html.escape(s)


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
        # ВСЁ, что пришло от модели, идёт через санитайзер — включая emoji:
        # одна угловая скобка в любом из этих полей уронит парсер Telegram,
        # и пост не будет доставлен целиком.
        emoji = _safe_emoji(b.get("emoji"))
        # Заголовок и так внутри <b>: вложенный одноимённый тег от модели
        # снимаем, чтобы не проверять на живом парсере Telegram.
        title_html = md_to_telegram_html(str(b["title"])).replace(
            "<b>", "").replace("</b>", "")
        title = link_html(b["url"], title_html)
        benefit = md_to_telegram_html(str(b["benefit"]))
        blocks.append(f"{emoji} <b>{n}. {title}</b>\n{benefit}")

    radar = digest.get("radar") or []
    if radar:
        lines = ["📡 <b>На радаре</b>"]
        for r in radar:
            url = r.get("url")
            if not url:
                continue               # радар необязателен: дефектный пункт пропускаем
            note = md_to_telegram_html(str(r.get("note", "")))
            title_html = md_to_telegram_html(str(r.get("title") or url))
            lines.append(f"• {link_html(url, title_html)}"
                         + (f" — {note}" if note else ""))
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    blocks.append(
        "Выберите одно и внедрите сегодня — этого уже достаточно, "
        "чтобы утро было не зря.")
    return blocks
