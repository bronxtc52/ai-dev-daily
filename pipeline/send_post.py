#!/usr/bin/env python3
"""Send AI-dev digest as a polished Telegram post in Arman's voice (benefit-framed).

Финальная версия подачи (сессия 19.07.2026):
- личный канал: без самопредставления
- каждый пункт — через ВЫГОДУ читателя («Что вам это даёт: …»)
- без вопроса-концовки и без подписи
Секреты — из Key Vault через config.secret(), в код не хардкодятся.
"""
import urllib.request, urllib.parse, json, html, sys

from config import secret

TOKEN = secret("TELEGRAM_BOT_TOKEN")
CHAT  = secret("TELEGRAM_CHAT_ID")

def link(url, text): return f"<a href=\"{url}\">{html.escape(text)}</a>"
def block(n, emoji, title, url, body):
    return f"{emoji} <b>{n}. {link(url, title)}</b>\n{html.escape(body)}"

parts = []
parts.append(
 "🗞 <b>AI-DEV ДАЙДЖЕСТ</b>\n"
 "<i>суббота, 19 июля</i>\n\n"
 "Доброе утро!\n"
 "Каждое утро я прохожусь по миру ИИ-разработки и оставляю только то, что можно "
 "взять и применить сегодня. Без хайпа и воды. Поехали 👇")

parts.append(block(1,"🏗","Anthropic показала, как сама двигает большие миграции кода",
 "https://claude.com/blog/ai-code-migration",
 "Что вам это даёт: готовый метод провести крупный рефактор или миграцию в своём проекте "
 "и не сломать всё по дороге. Задачу режут на куски, дают агенту чёткие границы, проверяют "
 "на масштабе — вы экономите дни ручной работы и снижаете риск."))

parts.append(block(2,"🧵","Запускаем Claude Code и Codex роем, а не по одному",
 "https://dev.to/bokuwalily/swarming-claude-code-and-codex-in-parallel-running-multiple-agents-at-once-with-tmux-and-git-1fej",
 "Что вам это даёт: способ гонять несколько агентов параллельно и не путаться в ветках. "
 "На практике — больше задач за то же время. Схема на tmux и git worktrees повторяется по шагам."))

parts.append(block(3,"🔧","Скиллы, хуки и субагенты: собираем первый цикл агента",
 "https://www.braingrid.ai/blog/skills-hooks-subagents-first-agent-loop",
 "Что вам это даёт: разберётесь, из чего собрать агента под себя. Это контроль — агент "
 "работает по-вашему, а не как из коробки, и вы меньше переделываете за ним потом."))

parts.append(block(4,"🔌","MCP в Claude Code: когда подключать — и когда не надо",
 "https://dev.to/rulestack/mcp-servers-in-claude-code-the-minimal-setup-and-when-you-should-skip-mcp-entirely-1499",
 "Что вам это даёт: поймёте, когда MCP реально нужен, а когда только усложняет проект. "
 "Сэкономите время и не потащите в дело лишнее — редкий честный разбор без продажи."))

parts.append(block(5,"🎨","Hallmark — открытый скилл против «одинакового» ИИ-дизайна",
 "https://dev.to/terminalchai/hallmark-together-ai-open-sources-an-anti-ai-slop-tool-for-web-design-3nkb",
 "Что вам это даёт: ваши сайты и интерфейсы перестанут выглядеть «сгенерированными». "
 "Скилл задаёт вкус ещё до кода, ставится в агента бесплатно — на выходе продукт, который "
 "не стыдно показать клиенту."))

parts.append(block(6,"🖥","Станция из Mac Mini, где агенты работают круглосуточно",
 "https://dev.to/samhartley_dev/i-automated-my-entire-dev-workflow-with-ai-agents-running-247-on-a-mac-mini-1ikc",
 "Что вам это даёт: идея, как из недорогого Mac собрать всегда-включённую станцию и снять "
 "с себя рутину. Реальный кейс от первого лица — освобождает ваше время каждый день."))

parts.append(
 "📡 <b>На радаре</b>\n"
 f"• {link('https://x.com/0xPascual/status/2078748095555440910','Kimi Code CLI')} от Moonshot — "
 "открытый «клон» Claude Code: один бинарь, субагенты.\n"
 f"• {link('https://github.com/KlaatAI/klaatcode','klaatcode')} ★139 — свежий терминальный агент.")

parts.append(
 "Выберите одно и внедрите сегодня — этого уже достаточно, чтобы утро было не зря.")

sep = "\n\n➖➖➖➖➖➖➖➖➖➖\n\n"
msg = sep.join(parts)

def send(text):
    data = urllib.parse.urlencode({
        "chat_id":CHAT,"text":text,"parse_mode":"HTML",
        "disable_web_page_preview":"true"}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data)
    r = json.load(urllib.request.urlopen(req, timeout=30))
    return r.get("ok"), r.get("description","")

if __name__ == "__main__":
    ok, desc = send(msg)
    print(f"ok={ok} {desc} · {len(msg)} chars", file=sys.stderr)
    sys.exit(0 if ok else 1)
