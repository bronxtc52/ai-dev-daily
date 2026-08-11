#!/usr/bin/env python3
"""Сбор кандидатов для дайджеста: X.com, Exa, GitHub.

Модуль импортируется без секретов и без сети: ключи разрешаются лениво, в момент
вызова конкретного источника. Иначе тесты и --dry-run требовали бы Key Vault.
"""
import json
import logging
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from config import secret

log = logging.getLogger(__name__)

HTTP_TIMEOUT = 30          # на один вызов; общий потолок прогона — в run_daily
DEFAULT_WINDOW_DAYS = 3
RETRY_ATTEMPTS = 3


def window_start(now, days=DEFAULT_WINDOW_DAYS):
    """Начало окна свежести в формате YYYY-MM-DD."""
    return (now - timedelta(days=days)).strftime("%Y-%m-%d")


def with_retry(fn, attempts=RETRY_ATTEMPTS, base_delay=1.0):
    """Повторить вызов при транзиентном сбое.

    Разовый таймаут или 5xx не должен уводить сервис в постоянную деградацию —
    сначала ретраи с нарастающей паузой, и только потом решение о деградации.
    """
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:                      # noqa: BLE001 — решает вызывающий
            last = e
            if i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
    raise last


def _get_json(url, headers, data=None, timeout=HTTP_TIMEOUT):
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ---------- источники --------------------------------------------------------

def x_search(query, n=15):
    """Свежие твиты практиков через X.com recent search."""
    token = secret("X_BEARER_TOKEN")
    url = "https://api.twitter.com/2/tweets/search/recent?" + urllib.parse.urlencode({
        "query": query, "max_results": n,
        "tweet.fields": "created_at,public_metrics,author_id",
        "expansions": "author_id", "user.fields": "username,name"})
    d = _get_json(url, {"Authorization": f"Bearer {token}"})

    users = {u["id"]: u for u in d.get("includes", {}).get("users", [])}
    out = []
    for t in d.get("data", []):
        m = t.get("public_metrics", {})
        u = users.get(t.get("author_id"), {})
        handle = u.get("username", "i")
        out.append({
            "source": f"X/@{handle}",
            "title": t["text"][:280],
            "url": f"https://x.com/{handle}/status/{t['id']}",
            "date": t.get("created_at"),
            "extra": {"score": m.get("like_count", 0) + m.get("retweet_count", 0) * 2
                               + m.get("bookmark_count", 0), "metrics": m},
        })
    return out


def exa_search(query, n=8, since_date=None):
    """Смысловой поиск статей и блогов."""
    key = secret("EXA_API_KEY")
    body = json.dumps({
        "query": query, "numResults": n, "type": "auto",
        "startPublishedDate": since_date,
        "contents": {"text": {"maxCharacters": 300}}}).encode()
    d = _get_json("https://api.exa.ai/search",
                  {"x-api-key": key, "Content-Type": "application/json"},
                  data=body, timeout=45)
    return [{"source": "Exa", "title": r.get("title"), "url": r.get("url"),
             "date": r.get("publishedDate"),
             "extra": {"snippet": (r.get("text") or "")[:200]}}
            for r in d.get("results", [])]


def github_search(query, n=10):
    """Свежие репозитории и релизы."""
    token = secret("GITHUB_TOKEN")
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode({
        "q": query, "sort": "stars", "order": "desc", "per_page": n})
    d = _get_json(url, {"Authorization": f"token {token}",
                        "Accept": "application/vnd.github+json"})
    return [{"source": "GitHub",
             "title": f"{r['full_name']} — {r.get('description', '')}",
             "url": r["html_url"], "date": r.get("created_at"),
             "extra": {"stars": r.get("stargazers_count"), "pushed": r.get("pushed_at")}}
            for r in d.get("items", [])]


# ---------- запросы ----------------------------------------------------------

def build_queries(since_date):
    return {
        "x": [
            '("Claude Code" OR "claude code skill" OR "claude code subagent") '
            '(release OR workflow OR tip OR skill OR hook) -is:retweet -is:reply lang:en',
            '("Codex CLI" OR AGENTS.md) (workflow OR agent OR tip OR release) '
            '-is:retweet -is:reply lang:en',
            '("MCP server" OR "Model Context Protocol") (release OR new OR built OR launch) '
            '-is:retweet -is:reply lang:en',
            '("local LLM" OR "on-device AI" OR "Apple Silicon") '
            '(model OR app OR tool OR runs) -is:retweet -is:reply lang:en',
        ],
        "exa": [
            "practical hands-on guide using Claude Code or Codex CLI coding agents new workflow",
            "new MCP server integration release for AI coding agents",
            "local on-device AI tool Apple Silicon no cloud practical case study",
            "AI agent skill anti-slop design workflow developer tooling",
        ],
        "github": [
            f"mcp server OR claude-code OR codex agent created:>{since_date}",
            f"AI agent skill OR coding-agent OR local-llm created:>{since_date}",
        ],
    }


def gather(sources, queries):
    """Собрать кандидатов со всех источников.

    Падение одного источника не отменяет утренний дайджест — работаем на
    частичных данных. Но если не выжил ни один, отправлять нечего: это ошибка.
    """
    out = []
    alive = 0
    for name, fn in sources.items():
        source_ok = False
        for q in queries.get(name, []):
            try:
                out.extend(fn(q))
                source_ok = True
            except Exception as e:                  # noqa: BLE001
                log.warning("источник %s: запрос отброшен (%s)", name, type(e).__name__)
        if source_ok:
            alive += 1

    if alive == 0:
        raise RuntimeError("ни один источник не ответил — собирать нечего")
    return out


def collect_candidates(now=None, days=DEFAULT_WINDOW_DAYS):
    """Точка входа для оркестратора."""
    now = now or datetime.now(timezone.utc)
    since = window_start(now, days)
    queries = build_queries(since)
    # Ретраи живут здесь, а не внутри gather: транзиентный сбой лечится повтором,
    # и только исчерпав попытки, источник считается мёртвым для этого прогона.
    sources = {
        "x": lambda q: with_retry(lambda: x_search(q)),
        "exa": lambda q: with_retry(lambda: exa_search(q, since_date=since)),
        "github": lambda q: with_retry(lambda: github_search(q)),
    }
    cands = gather(sources, queries)
    log.info("собрано кандидатов: %d (окно с %s)", len(cands), since)
    return cands


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    import pathlib
    items = collect_candidates()
    out_path = pathlib.Path(__file__).resolve().parent.parent / "data" / "candidates.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(items, ensure_ascii=False, indent=1))
    print(f"[saved] {out_path} ({len(items)})", file=sys.stderr)
