# Источники для ежедневного поиска прикладных AI-dev новостей

> Список источников под ваш промт «Ежедневный поиск прикладных AI-dev новостей».
> Ядро тем: кодинг-агенты (Codex, Claude Code, Cursor, Aider, Gemini CLI), скиллы/субагенты/хуки,
> MCP-серверы, локальный/on-device AI (Apple Silicon), dev-воркфлоу и железо под агентов.
> Для каждого раздела указаны прямые ссылки и, где есть, RSS/Atom-фиды — их можно завести в ридер
> (Inoreader, Feedly, NetNewsWire) или скормить scheduled-агенту напрямую.

Легенда: 🟢 = официальный первоисточник · 🔵 = агрегатор/трекер · 🟡 = сообщество/автор · 📡 = есть RSS

---

## 1. Официальные changelog и блоги инструментов (первоисточники — самый высокий приоритет)

Здесь появляются релизы фич из первых рук. Это ядро вашего дайджеста.

### Кодинг-агенты и CLI

| Источник | Ссылка | RSS |
|---|---|---|
| 🟢 **Claude Code changelog** (официальный) | [code.claude.com/docs/en/changelog](https://code.claude.com/docs/en/changelog) · [.md версия](https://code.claude.com/docs/en/changelog.md) | Anthropic теперь публикует официальный RSS для Claude Code |
| 🔵 **CCWatch** — трекер релизов Claude Code | [ccwatch.net](https://ccwatch.net) | 📡 [ccwatch.net/feed.xml](https://ccwatch.net/feed.xml) · [JSON](https://ccwatch.net/feed.json) |
| 🟢 **OpenAI Codex changelog** (официальный, переехал) | [learn.chatgpt.com/docs/changelog](https://learn.chatgpt.com/docs/changelog) | — |
| 🟢 **Codex releases на GitHub** (версия за версией) | [github.com/openai/codex/releases](https://github.com/openai/codex/releases) | 📡 [releases.atom](https://github.com/openai/codex/releases.atom) |
| 🔵 **Codex Insider** — разбор каждого релиза Codex | [codexinsider.com/releases](https://codexinsider.com/releases/) | — |
| 🟢 **Cursor changelog** | [cursor.com/changelog](https://cursor.com/changelog) | 📡 [cursor.com/rss.xml](https://cursor.com/rss.xml) |
| 🟢 **Cursor blog** | [cursor.com/blog](https://cursor.com/blog) | 📡 [cursor.com/rss.xml](https://cursor.com/rss.xml) |
| 🔵 **Changes.Watch — Cursor** (release notes + реакции) | [changes.watch/products/cursor](https://www.changes.watch/products/cursor) | 📡 есть на странице |
| 🟢 **GitHub Copilot changelog** | [github.blog/changelog/label/copilot](https://github.blog/changelog/label/copilot/) | 📡 [github.blog/changelog/feed](https://github.blog/changelog/feed/) |
| 🟢 **Aider blog / release notes** | [aider.chat/blog](https://aider.chat/blog/) · [releases](https://github.com/Aider-AI/aider/releases) | 📡 [releases.atom](https://github.com/Aider-AI/aider/releases.atom) |
| 🟢 **Gemini CLI releases** | [github.com/google-gemini/gemini-cli/releases](https://github.com/google-gemini/gemini-cli/releases) | 📡 [releases.atom](https://github.com/google-gemini/gemini-cli/releases.atom) |
| 🟢 **Windsurf (Codeium) changelog** | [windsurf.com/changelog](https://windsurf.com/changelog) | — |

### Провайдеры моделей (блоги)

| Источник | Ссылка | RSS |
|---|---|---|
| 🟢 **OpenAI News** | [openai.com/news](https://openai.com/news/) | 📡 [openai.com/news/rss.xml](https://openai.com/news/rss.xml) |
| 🟢 **Anthropic News** | [anthropic.com/news](https://www.anthropic.com/news) | 📡 неофиц. зеркало: [Olshansk/rss-feeds → anthropic_news](https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml) |
| 🟢 **Anthropic Engineering** | [anthropic.com/engineering](https://www.anthropic.com/engineering) | 📡 [Olshansk → anthropic_engineering](https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_engineering.xml) |
| 🟢 **Google AI blog** | [blog.google/technology/ai](https://blog.google/technology/ai/) | 📡 [blog.google/technology/ai/rss](https://blog.google/technology/ai/rss/) |
| 🟢 **Hugging Face blog** | [huggingface.co/blog](https://huggingface.co/blog) | 📡 [huggingface.co/blog/feed.xml](https://huggingface.co/blog/feed.xml) |
| 🟢 **Ollama blog** (локальный инференс) | [ollama.com/blog](https://ollama.com/blog) | 📡 [Olshansk → ollama](https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_ollama.xml) |

> 💡 Полезный репозиторий: [Olshansk/rss-feeds](https://github.com/Olshansk/rss-feeds) — генерирует RSS для блогов без официальных лент (Anthropic, OpenAI research, Ollama и др.).

---

## 2. MCP (Model Context Protocol)

| Источник | Ссылка | RSS |
|---|---|---|
| 🟢 **MCP официальный блог** | [blog.modelcontextprotocol.io](https://blog.modelcontextprotocol.io/) · [архив](https://blog.modelcontextprotocol.io/archives/) | 📡 обычно `/feed` или `/rss.xml` на Ghost/статик-движке |
| 🟢 **Official MCP Registry** (каталог серверов) | [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io/) · [docs](https://registry.modelcontextprotocol.io/docs) | — (есть API для отслеживания новых серверов) |
| 🟢 **MCP Registry на GitHub** | [github.com/modelcontextprotocol/registry](https://github.com/modelcontextprotocol/registry) | 📡 releases/commits.atom |
| 🟢 **GitHub MCP Registry** | [github.com/mcp](https://github.com/mcp) · [анонс](https://github.blog/changelog/2025-09-16-github-mcp-registry-the-fastest-way-to-discover-ai-tools/) | — |
| 🟡 **awesome-mcp-servers** (кураторский список) | [github.com/punkpeye/awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) | 📡 [commits.atom](https://github.com/punkpeye/awesome-mcp-servers/commits/main.atom) |
| 🟡 **modelcontextprotocol/servers** (референс-серверы) | [github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | 📡 commits/releases.atom |

---

## 3. GitHub — trending, релизы, awesome-списки

GitHub — главный источник «собрал сам / вышел новый инструмент». Настраивается через Atom-фиды.

### Trending и релизы

- 🟢 **GitHub Trending (daily)** — [github.com/trending?since=daily](https://github.com/trending?since=daily). Официального RSS нет, но есть зеркала:
  - 📡 [mshibanami/GitHubTrendingRSS](https://mshibanami.github.io/GitHubTrendingRSS/) — trending по языкам в RSS.
- 🟢 **Отслеживание релизов любого репозитория**: добавьте `.atom` к URL релизов —
  например `https://github.com/OWNER/REPO/releases.atom` (работает для codex, aider, cursor-CLI, gemini-cli и т.д.).
- 🟢 **Отслеживание тегов/коммитов**: `.../tags.atom`, `.../commits/main.atom`.

### Кураторские списки (следить за коммитами через `.atom`)

| Список | Ссылка |
|---|---|
| 🟡 **awesome-claude-code** (команды, хуки, воркфлоу) | [github.com/hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) |
| 🟡 **awesome-claude-skills** | [github.com/ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills) |
| 🟡 **awesome-mcp-servers** | [github.com/punkpeye/awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) |
| 🟡 **awesome-cursor / cursor.directory** | [cursor.directory](https://cursor.directory) |
| 🟡 **awesome-local-ai** (локальный инференс) | [github.com/janhq/awesome-local-ai](https://github.com/janhq/awesome-local-ai) |

---

## 4. Reddit — сабреддиты и их RSS

Reddit отдаёт RSS почти для всего: добавьте `.rss` к URL сабреддита или поиска.
Формат: `https://www.reddit.com/r/SUBREDDIT/new/.rss` (новое) или `/top/.rss?t=day` (топ за день).

| Сабреддит | Ссылка | RSS (новое) |
|---|---|---|
| r/LocalLLaMA (локальный инференс — ключевой) | [reddit.com/r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/) | 📡 [/r/LocalLLaMA/new/.rss](https://www.reddit.com/r/LocalLLaMA/new/.rss) |
| r/ClaudeAI | [reddit.com/r/ClaudeAI](https://www.reddit.com/r/ClaudeAI/) | 📡 [/new/.rss](https://www.reddit.com/r/ClaudeAI/new/.rss) |
| r/ChatGPTCoding | [reddit.com/r/ChatGPTCoding](https://www.reddit.com/r/ChatGPTCoding/) | 📡 [/new/.rss](https://www.reddit.com/r/ChatGPTCoding/new/.rss) |
| r/cursor | [reddit.com/r/cursor](https://www.reddit.com/r/cursor/) | 📡 [/new/.rss](https://www.reddit.com/r/cursor/new/.rss) |
| r/OpenAI | [reddit.com/r/OpenAI](https://www.reddit.com/r/OpenAI/) | 📡 [/new/.rss](https://www.reddit.com/r/OpenAI/new/.rss) |
| r/LocalLLM | [reddit.com/r/LocalLLM](https://www.reddit.com/r/LocalLLM/) | 📡 [/new/.rss](https://www.reddit.com/r/LocalLLM/new/.rss) |
| r/selfhosted | [reddit.com/r/selfhosted](https://www.reddit.com/r/selfhosted/) | 📡 [/new/.rss](https://www.reddit.com/r/selfhosted/new/.rss) |
| r/macapps | [reddit.com/r/macapps](https://www.reddit.com/r/macapps/) | 📡 [/new/.rss](https://www.reddit.com/r/macapps/new/.rss) |
| r/MachineLearning | [reddit.com/r/MachineLearning](https://www.reddit.com/r/MachineLearning/) | 📡 [/new/.rss](https://www.reddit.com/r/MachineLearning/new/.rss) |
| r/artificial | [reddit.com/r/artificial](https://www.reddit.com/r/artificial/) | 📡 [/new/.rss](https://www.reddit.com/r/artificial/new/.rss) |

> 💡 Поиск по ключевым словам тоже даёт RSS:
> `https://www.reddit.com/search.rss?q=MCP+server&sort=new` — узкий фильтр под ядро тем.
> Для «умных» фидов топ-постов (Reddit/Lemmy/HN/Lobsters) — [upvote-rss](https://github.com/johnwarne/upvote-rss).

---

## 5. Hacker News (с фильтрами под ядро тем)

Официальный RSS — только фронт-пейдж. Для точечных фильтров используйте **hnrss.org**:

| Что | RSS |
|---|---|
| 🟢 Front page (официальный) | 📡 [news.ycombinator.com/rss](https://news.ycombinator.com/rss) |
| 🔵 Ключевое слово + порог голосов | 📡 `https://hnrss.org/newest?q=Claude+Code&points=50` |
| 🔵 MCP-серверы | 📡 `https://hnrss.org/newest?q=MCP&points=30` |
| 🔵 Локальный AI / Apple Silicon | 📡 `https://hnrss.org/newest?q=local+LLM&points=30` |
| 🔵 Show HN (кейсы «собрал сам») | 📡 [hnrss.org/show](https://hnrss.org/show) |
| 🔵 Комбинация фильтров | 📡 `https://hnrss.org/newest?q=AI+agent&points=100&comments=20` |

Документация фидов: [hnrss.github.io](https://hnrss.github.io/) · Расширенный поиск: [hn.algolia.com](https://hn.algolia.com).

---

## 6. Lobsters и dev.to (тематические теги — с RSS)

| Источник | Ссылка | RSS |
|---|---|---|
| 🟡 **Lobsters — тег `ai`** | [lobste.rs/t/ai](https://lobste.rs/t/ai) | 📡 [lobste.rs/t/ai.rss](https://lobste.rs/t/ai.rss) |
| 🟡 **Lobsters — тег `ml`** | [lobste.rs/t/ml](https://lobste.rs/t/ml) | 📡 [lobste.rs/t/ml.rss](https://lobste.rs/t/ml.rss) |
| 🟡 **dev.to — тег `#ai`** | [dev.to/t/ai](https://dev.to/t/ai) | 📡 [dev.to/feed/tag/ai](https://dev.to/feed/tag/ai) |
| 🟡 **dev.to — тег `#llm`** | [dev.to/t/llm](https://dev.to/t/llm) | 📡 [dev.to/feed/tag/llm](https://dev.to/feed/tag/llm) |
| 🟡 **dev.to — тег `#mcp`** | [dev.to/t/mcp](https://dev.to/t/mcp) | 📡 [dev.to/feed/tag/mcp](https://dev.to/feed/tag/mcp) |

---

## 7. Инженерные блоги, newsletters и Substack (авторская конкретика)

| Автор / издание | О чём | Ссылка | RSS |
|---|---|---|---|
| 🟢 **Simon Willison** (№1 для практиков LLM-tooling) | ежедневные заметки, разборы, CLI-инструменты | [simonwillison.net](https://simonwillison.net) | 📡 [simonwillison.net/atom/everything](https://simonwillison.net/atom/everything/) |
| 🟢 **Latent Space** (swyx) — AI Engineer | агенты, инфра, кодинг-тулзы | [latent.space](https://www.latent.space) | 📡 [latent.space/feed](https://www.latent.space/feed) |
| 🟢 **The Pragmatic Engineer** (Gergely Orosz) | AI-инжиниринг, воркфлоу | [pragmaticengineer.com](https://www.pragmaticengineer.com) | 📡 [newsletter.pragmaticengineer.com/feed](https://newsletter.pragmaticengineer.com/feed) |
| 🟢 **Ahead of AI** (Sebastian Raschka) | архитектура LLM, hands-on | [magazine.sebastianraschka.com](https://magazine.sebastianraschka.com) | 📡 [/feed](https://magazine.sebastianraschka.com/feed) |
| 🔵 **TLDR AI** | быстрый ежедневный дайджест | [tldr.tech/ai](https://tldr.tech/ai) | email |
| 🔵 **Ben's Bites** | продукты и тулзы под сборку | [bensbites.com](https://www.bensbites.com) | email |
| 🔵 **Import AI** (Jack Clark) | еженедельный контекст | [importai.substack.com](https://importai.substack.com) | 📡 [/feed](https://importai.substack.com/feed) |

---

## 8. X / Twitter — аккаунты практиков и мейнтейнеров

Треды с фичами из первых рук. Для RSS через ридер используйте мосты (Nitter-инстансы,
[RSS.app](https://rss.app), [Nitter](https://github.com/zedeus/nitter) self-host) — прямого RSS у X нет.

### Ядро — практики LLM/агентов
- [@karpathy](https://x.com/karpathy) — Андрей Карпаты, образовательная конкретика по LLM
- [@simonw](https://x.com/simonw) — Simon Willison, лучший follow для LLM-tooling
- [@swyx](https://x.com/swyx) — AI Engineer, Latent Space
- [@steipete](https://x.com/steipete) — Peter Steinberger, agent-tooling, эксперименты с кодинг-агентами
- [@_akhaliq](https://x.com/_akhaliq) — свежие пейперы и релизы
- [@hwchase17](https://x.com/hwchase17) — Harrison Chase, LangChain
- [@jerryjliu0](https://x.com/jerryjliu0) — Jerry Liu, LlamaIndex

### Официальные каналы инструментов
- [@Codex_Changelog](https://x.com/Codex_Changelog) — авто-анонсы релизов Codex CLI
- [@cursor_ai](https://x.com/cursor_ai) — Cursor
- [@AnthropicAI](https://x.com/AnthropicAI) · [@claudeai](https://x.com/claudeai) — Anthropic / Claude
- [@OpenAIDevs](https://x.com/OpenAIDevs) — OpenAI для разработчиков
- [@ollama](https://x.com/ollama) — локальный инференс
- [@LocalLLaMAsub](https://x.com/LocalLLaMAsub) — зеркало r/LocalLLaMA

### Локальный / on-device (Apple Silicon)
- [@awnihannun](https://x.com/awnihannun) — MLX (Apple), локальный инференс на Apple Silicon
- [@reach_vb](https://x.com/reach_vb) — Vaibhav Srivastav (HF), локальные модели, on-device
- [@ggerganov](https://x.com/ggerganov) — llama.cpp / whisper.cpp

> 💡 Готовые кураторские списки для калибровки: [daily.dev — AI engineers to follow](https://daily.dev/blog/best-ai-engineers-to-follow-on-x/) · [KDnuggets — 10 accounts for LLM updates](https://www.kdnuggets.com/10-best-x-twitter-accounts-to-follow-for-llm-updates).

---

## 9. YouTube — разборы и кейсы (есть RSS по каналу)

YouTube отдаёт RSS: `https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID`.
Подборка каналов по AI-кодингу (Cursor, Copilot, Claude Code, vibe-coding): [Developer Educators — 10 AI coding channels](https://developereducators.com/blog/best-ai-coding-youtube-channels/).
Берите только видео с текстовым описанием/сутью — по вашему анти-фильтру.

---

## 10. Русскоязычные ресурсы

### Telegram-каналы (для разработчиков и по LLM/агентам)
- **AI for Devs** — [@ai_for_devs](https://t.me/ai_for_devs) — ассистенты, плагины, IDE, практические кейсы
- **Хабр / ML & AI** — [@habr_ai](https://t.me/habr_ai) — аннотации статей Хабра по ИИ
- **LLM под капотом** — разработка продуктов на LLM, разборы кейсов (искать в каталогах ниже)
- **эйай ньюз** — обзоры научных статей и новостей
- **addmeto** (Григорий Бакунов) — IT-новости со ссылками на первоисточники
- **AGI and RL** — [@agi_and_rl](https://t.me/agi_and_rl) — агенты, RL, исследования
- **Сиолошная**, **gonzo_ML**, **Data Secrets** — технические разборы (в каталогах)

Каталоги для поиска и подписки:
- [DevBox — Telegram-каналы по LLM, AI и ML](https://devbox.tools/ru/blog/146-telegram-kanaly-i-chaty-po-llm-ai-i-machine-learning/)
- [goq/telegram-list (GitHub)](https://github.com/goq/telegram-list) — большой каталог IT/ML-каналов
- [РБК Тренды — топ-10 каналов про ИИ](https://trends.rbc.ru/trends/social/cmrm/68abfbba9a7947743b95f729)

> 💡 У публичных Telegram-каналов есть веб-версия `https://t.me/s/КАНАЛ` — её можно
> завести в RSS через мост [RSSHub](https://docs.rsshub.app/) (`/telegram/channel/КАНАЛ`).

### Сайты и агрегаторы
- **Habr — хабы AI / ML / Программирование** — [habr.com/ru/hubs/artificial_intelligence](https://habr.com/ru/hubs/artificial_intelligence/) · 📡 [/rss/hubs/artificial_intelligence](https://habr.com/ru/rss/hubs/artificial_intelligence/all/)
- **Habr — новости** про кодинг-агентов (пример: [Claude Code Channels](https://habr.com/ru/news/1012558/))
- **vc.ru — раздел AI** — [vc.ru/ai](https://vc.ru/ai) · 📡 [vc.ru/rss/all](https://vc.ru/rss/all)

---

## Как это применить (практика)

1. **Минимальный набор для scheduled-агента** (первоисточники, дают 70% ценности):
   Claude Code changelog (CCWatch RSS) · Codex releases.atom · Cursor rss.xml · MCP registry ·
   r/LocalLLaMA + r/ClaudeAI (.rss) · hnrss с фильтрами · Simon Willison atom · Latent Space feed.

2. **RSS-ридер как хаб**: заведите все 📡-фиды в Inoreader/Feedly/NetNewsWire, сгруппируйте по
   папкам (Официальные · Reddit · HN · Блоги · RU). Агент читает OPML-экспорт или тянет фиды напрямую.

3. **X и Telegram** — через мосты (Nitter / RSSHub), либо агент открывает веб-версии
   (`t.me/s/...`, профили X) и применяет ваш анти-фильтр к постам.

4. **GitHub-релизы** отслеживайте через `.atom` — самый надёжный сигнал «вышла новая версия/инструмент».

---

## 11. Что реально использует сервис `ai-dev-daily-search` (движки сбора)

> Добавлено 19.07.2026 по итогам пробного боевого прогона. Раздел выше — это каталог
> первоисточников; здесь — конкретные API-движки, через которые сервис до них дотягивается.
> Ключи разрешаются через `pipeline/config.py` (env → Azure Key Vault), см. `.env.example`.

| Движок | Логический ключ | Роль | Лимит |
|---|---|---|---|
| **X.com API v2** (recent search) | `X_BEARER_TOKEN` | Свежие твиты практиков «из первых рук» | 450 запросов / 15 мин |
| **Exa** (нейропоиск) | `EXA_API_KEY` | Смысловой поиск статей/блогов, фильтр по дате | — |
| **Firecrawl** | `FIRECRAWL_API_KEY` | Поиск + скрейп страниц (Reddit, HN, блоги, JS/SPA) | — |
| **GitHub Search API** | `GITHUB_TOKEN` | Свежие репо/релизы (`created:>`, `pushed:>`) | высокий |
| **Brave Search** | `BRAVE_API_KEY` | Резервный веб-поиск | — |
| **Perplexity** | `PERPLEXITY_API_KEY` | Поиск + синтез с источниками (сводный канал) | — |
| **Claude** (курация/формат) | `ANTHROPIC_API_KEY` | Фильтр по критериям, дедуп, вывод от имени автора | — |
| **Telegram** (доставка) | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Отправка дайджеста получателю | — |

### Первоисточники пробного дайджеста (19.07.2026)

1. Anthropic — крупные миграции кода через Claude Code — https://claude.com/blog/ai-code-migration
2. Рой Claude Code + Codex (tmux + git worktrees) — https://dev.to/bokuwalily/swarming-claude-code-and-codex-in-parallel-running-multiple-agents-at-once-with-tmux-and-git-1fej
3. Skills + Hooks + Subagents: первый agent-loop — https://www.braingrid.ai/blog/skills-hooks-subagents-first-agent-loop
4. MCP в Claude Code: минимальный сетап и когда пропустить — https://dev.to/rulestack/mcp-servers-in-claude-code-the-minimal-setup-and-when-you-should-skip-mcp-entirely-1499
5. Hallmark — open-source anti-slop дизайн-скилл (Together AI) — https://dev.to/terminalchai/hallmark-together-ai-open-sources-an-anti-ai-slop-tool-for-web-design-3nkb
6. Дев-воркфлоу 24/7 на Mac Mini — https://dev.to/samhartley_dev/i-automated-my-entire-dev-workflow-with-ai-agents-running-247-on-a-mac-mini-1ikc

**На радаре:** Kimi Code CLI (Moonshot) — https://x.com/0xPascual/status/2078748095555440910 · klaatcode ★139 — https://github.com/KlaatAI/klaatcode
