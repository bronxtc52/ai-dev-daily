"""Критерии приёмки 2, 3, 4, 7 — форматирование LLM-текста под Telegram.

Оракул для ожиданий — не наш код, а документация Telegram Bot API (список
поддерживаемых тегов) и разбор инцидента в knowledge-base
(snippets/telegram-llm-markdown-to-html.md). Все ожидания записаны литералами.
"""
import re

import pytest

from formatting import build_post, md_to_telegram_html, TELEGRAM_LIMIT


# --- Критерий 2: markdown-жирный не должен уходить звёздочками ---------------

def test_bold_becomes_b_tag():
    assert md_to_telegram_html("**жирный**") == "<b>жирный</b>"


def test_bold_inside_sentence():
    # Живой ответ Perplexity 2026-08-11 содержал именно такую разметку.
    assert md_to_telegram_html(
        "Вышел **Kimi Code CLI** сегодня"
    ) == "Вышел <b>Kimi Code CLI</b> сегодня"


def test_markdown_header_becomes_bold_line():
    # Telegram не знает <h1>..<h6>, поэтому заголовок передаём жирной строкой.
    assert md_to_telegram_html("## Итоги дня") == "<b>Итоги дня</b>"


def test_bullet_becomes_dot():
    assert md_to_telegram_html("- первый\n- второй") == "• первый\n• второй"


# --- Критерий 3: сырой '<' обязан доставиться, а не уронить парсер ------------

def test_raw_less_than_is_escaped():
    # «Bad Request: can't parse entities» — сообщение теряется целиком.
    assert md_to_telegram_html("латентность <3,0 с") == "латентность &lt;3,0 с"


def test_ampersand_is_escaped():
    assert md_to_telegram_html("Кофе & код") == "Кофе &amp; код"


def test_escape_happens_before_markdown_conversion():
    # Если escape сделать ПОСЛЕ конвертации, наши же теги превратятся в &lt;b&gt;.
    out = md_to_telegram_html("**<script>**")
    assert out == "<b>&lt;script&gt;</b>"


# --- Критерий 4: подчёркивания в идентификаторах — не курсив ------------------

def test_snake_case_is_not_italic():
    assert md_to_telegram_html("зови send_post_now") == "зови send_post_now"


def test_real_italic_still_works():
    assert md_to_telegram_html("_правда_") == "<i>правда</i>"


# --- Критерий 7: усечение по границам блоков, без разрыва тегов ---------------

def _tags_balanced(html_text):
    """Независимая от реализации проверка парности тегов Telegram."""
    stack = []
    for kind, name in re.findall(r"<(/?)(b|i|u|s|a|code|pre)\b[^>]*>", html_text):
        if kind == "":
            stack.append(name)
        else:
            if not stack or stack.pop() != name:
                return False
    return not stack


def test_long_post_fits_telegram_limit():
    blocks = [f"<b>Блок {i}</b>\nПодробности пункта номер {i}. " + "x" * 300
              for i in range(40)]
    post = build_post(blocks)
    assert len(post) <= TELEGRAM_LIMIT


def test_truncation_does_not_split_tags():
    blocks = [f"<b>Заголовок {i}</b>\n" + "содержимое " * 60 for i in range(40)]
    post = build_post(blocks)
    assert _tags_balanced(post), "усечение разорвало HTML-тег — Telegram отвергнет пост"


def test_truncation_keeps_whole_blocks():
    # Режем по границам блоков: уцелевший блок присутствует целиком.
    blocks = [f"<b>Блок {i}</b>\n" + "текст " * 100 for i in range(40)]
    post = build_post(blocks)
    assert "<b>Блок 0</b>" in post
    for i in range(40):
        marker = f"<b>Блок {i}</b>"
        if marker in post:
            assert f"<b>Блок {i}</b>\n" + "текст " * 100 in post, (
                f"блок {i} попал в пост обрезанным")


def test_short_post_is_not_truncated():
    blocks = ["<b>Один</b>\nкоротко", "<b>Два</b>\nтоже коротко"]
    post = build_post(blocks)
    assert "<b>Один</b>" in post and "<b>Два</b>" in post


def test_build_post_rejects_empty_digest():
    # Пустой пост слать нельзя (см. критерий 9) — это ошибка, а не пустая строка.
    with pytest.raises(ValueError):
        build_post([])
