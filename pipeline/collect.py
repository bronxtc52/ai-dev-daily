#!/usr/bin/env python3
"""Collector for ai-dev-daily-search: gather fresh candidates from X, Exa, GitHub.

Все ключи тянутся из Azure Key Vault через config.secret(), в код/argv не попадают.
Выход: candidates.json — список кандидатов для курации.
"""
import json, urllib.request, urllib.parse, sys
from datetime import datetime, timedelta, timezone

from config import secret

X_BEARER = secret("X_BEARER_TOKEN")
EXA_KEY  = secret("EXA_API_KEY")
GH_TOKEN = secret("GITHUB_TOKEN")

# В проде брать datetime.now(timezone.utc); зафиксировано для воспроизводимости прогона.
today = datetime(2026,7,19,tzinfo=timezone.utc)
since = today - timedelta(days=3)
since_date = since.strftime("%Y-%m-%d")

cands = []
def add(src, title, url, date=None, extra=None):
    cands.append({"source":src,"title":(title or "").strip(),"url":url,
                  "date":date,"extra":extra})

# ---------- X.com recent search ----------
def x_search(q, n=15):
    url = "https://api.twitter.com/2/tweets/search/recent?" + urllib.parse.urlencode({
        "query": q, "max_results": n,
        "tweet.fields":"created_at,public_metrics,author_id",
        "expansions":"author_id","user.fields":"username,name"})
    req = urllib.request.Request(url, headers={"Authorization":f"Bearer {X_BEARER}"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=30))
    except Exception as e:
        print(f"[X] err {q!r}: {e}", file=sys.stderr); return
    users = {u["id"]:u for u in d.get("includes",{}).get("users",[])}
    for t in d.get("data",[]):
        m = t.get("public_metrics",{})
        score = m.get("like_count",0)+m.get("retweet_count",0)*2+m.get("bookmark_count",0)
        u = users.get(t.get("author_id"),{})
        add("X/@"+u.get("username","?"), t["text"][:280],
            f"https://x.com/{u.get('username','i')}/status/{t['id']}",
            t.get("created_at"), {"score":score,"metrics":m})

X_QUERIES = [
    '("Claude Code" OR "claude code skill" OR "claude code subagent") (release OR workflow OR tip OR skill OR hook) -is:retweet -is:reply lang:en',
    '("Codex CLI" OR AGENTS.md) (workflow OR agent OR tip OR release) -is:retweet -is:reply lang:en',
    '("MCP server" OR "Model Context Protocol") (release OR new OR built OR launch) -is:retweet -is:reply lang:en',
    '("local LLM" OR "on-device AI" OR "Apple Silicon") (model OR app OR tool OR runs) -is:retweet -is:reply lang:en',
]
for q in X_QUERIES: x_search(q)

# ---------- Exa neural search ----------
def exa(q, n=8):
    body = json.dumps({"query":q,"numResults":n,"type":"auto",
                       "startPublishedDate":since_date,
                       "contents":{"text":{"maxCharacters":300}}}).encode()
    req = urllib.request.Request("https://api.exa.ai/search", data=body,
            headers={"x-api-key":EXA_KEY,"Content-Type":"application/json"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=45))
    except Exception as e:
        print(f"[Exa] err {q!r}: {e}", file=sys.stderr); return
    for r in d.get("results",[]):
        add("Exa", r.get("title"), r.get("url"), r.get("publishedDate"),
            {"snippet":(r.get("text") or "")[:200]})

EXA_QUERIES = [
    "practical hands-on guide using Claude Code or Codex CLI coding agents new workflow",
    "new MCP server integration release for AI coding agents",
    "local on-device AI tool Apple Silicon no cloud practical case study",
    "AI agent skill anti-slop design workflow developer tooling",
]
for q in EXA_QUERIES: exa(q)

# ---------- GitHub recent/trending ----------
def gh(q, n=10):
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode({
        "q": q, "sort":"stars","order":"desc","per_page":n})
    req = urllib.request.Request(url, headers={
        "Authorization":f"token {GH_TOKEN}","Accept":"application/vnd.github+json"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=30))
    except Exception as e:
        print(f"[GH] err {q!r}: {e}", file=sys.stderr); return
    for r in d.get("items",[]):
        add("GitHub", f"{r['full_name']} — {r.get('description','')}", r["html_url"],
            r.get("created_at"), {"stars":r.get("stargazers_count"),
            "pushed":r.get("pushed_at")})

GH_QUERIES = [
    f"mcp server OR claude-code OR codex agent created:>{since_date}",
    f"AI agent skill OR coding-agent OR local-llm created:>{since_date}",
]
for q in GH_QUERIES: gh(q)

print(f"[collected] {len(cands)} candidates", file=sys.stderr)
out = __file__.rsplit("/",2)[0] + "/data/candidates.json"
json.dump(cands, open(out,"w"), ensure_ascii=False, indent=1)
print(f"[saved] {out}", file=sys.stderr)
