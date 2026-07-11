# 🛰 trend-engine

A trend-driven content engine that runs locally on macOS (Apple Silicon,
Python 3.11+). It discovers what's trending in your niche, works out *why*,
drafts on-brand posts with a **local** LLM, and either queues them for your
approval **or** runs the whole thing autonomously — generating a video,
publishing it, measuring how it did, and **learning from its own results**.

Everything it needs is **free and open-source** — no paid APIs required.

**Two modes, same engine:**

| Mode | You do | Command |
|------|--------|---------|
| **Assisted** (default) | Review/approve every draft in a local dashboard; assisted publishing | `python run.py run` |
| **Autopilot** (autonomous) | Nothing per-post — automated gates replace the human; auto-generates + posts YouTube Shorts and self-tunes from engagement | `python run.py autopilot-run` |

> ⚠️ **Autopilot posts unreviewed AI-generated content to your real account.**
> It's guarded (a quality/safety gate, a self-critique pass, hard caps, a canary
> ramp, and a kill switch stand in for the human), and it starts in **shadow
> mode** (generates but doesn't upload) so you can watch it before it goes live.
> You still own what it publishes. Start in shadow, read the drafts, then flip to
> live.

```
 discover ──► analyse ──► draft (local LLM) ──► approval queue ──► you approve ──► assisted publish
 (Reddit,     (pandas:     (Ollama:            (SQLite +          (edit/approve/    (export file +
  Trends,      frequency,   llama3.1 or         FastAPI            reject in         clipboard +
  YouTube,     growth,      mistral)            dashboard)         the browser)      open composer)
  RSS)         engagement)
```

---

## What it does

1. **Discover** trending/viral content for your niche from pluggable sources:
   Reddit (PRAW), Google Trends (pytrends), YouTube Data API (free tier), and
   RSS feeds. Robots.txt and per-source rate limits are respected.
2. **Analyse** with pandas — frequency, growth rate vs. recent history, and an
   engagement score — then rank topics. Your logged post performance reweights
   the scoring over time.
3. **Draft** on-brand captions + hashtags with a local LLM via Ollama (free).
   The LLM layer is swappable — a stubbed Anthropic (Claude) adapter is included
   for when you want it.
4. **Queue** drafts into SQLite as `pending`. Review, edit, approve, or reject
   them in a local FastAPI dashboard.
5. **Assist publishing** of approved posts: export a ready-to-post file, copy
   the caption to your clipboard, and (optionally) open the platform composer.
   Official API publishers (Meta Graph, TikTok) are left as clearly-marked stubs.

In **autopilot**, steps 4-5 happen without you: an automated gate approves the
draft, the engine renders a vertical Short (script → TTS voiceover → captioned
video), uploads it to YouTube, then pulls the post's stats and feeds them back
into a learning loop that re-tunes topic scoring and posting choices.

**Safety:** per-source rate limits, randomised run intervals, daily caps, a
canary volume ramp, an automated quality/safety gate, and a global kill switch.

---

## Project layout

```
trend-engine/
├── config.yaml              # niche, brand voice, sources, schedule  (edit this)
├── .env.example             # your free API keys go here (copy to .env)
├── requirements.txt
├── run.py                   # CLI entry point
└── trendengine/
    ├── config.py            # loads config.yaml + .env
    ├── pipeline.py          # the core discover→analyse→draft→queue loop
    ├── scheduler.py         # APScheduler (jittered interval + kill switch)
    ├── db/                  # SQLAlchemy models + SQLite session
    ├── autopilot.py         # the autonomous loop: gate → render → post → learn
    ├── sources/             # pluggable trend sources (reddit, trends, youtube, rss)
    ├── analysis/            # pandas aggregation + scoring (blends learned weights)
    ├── llm/                 # swappable LLM: ollama (default) + anthropic (stub)
    ├── generation/          # prompt building + drafter (bandit-arm aware)
    ├── guardrails/          # automated quality/safety gate (replaces the human)
    ├── media/               # local Short generation: TTS + ffmpeg captioned video
    ├── learning/            # Thompson bandit + ridge weight-learner + stats ingest
    ├── publishers/          # assisted (default), youtube (real), meta/tiktok (stubs)
    ├── dashboard/           # FastAPI approval UI + Jinja templates
    └── utils/               # hashing (dedup), rate limiting, robots, kill switch
```

---

## macOS setup

### 1. Python environment

```bash
cd trend-engine
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Install Ollama and pull a model (the free local LLM)

Ollama runs an open LLM entirely on your Mac — no API key, no cost.

```bash
# Install (Homebrew)
brew install ollama
# ...or download the app from https://ollama.com/download

# Start the Ollama server (leave it running; the app talks to it on :11434)
ollama serve            # or just launch the Ollama.app

# Pull a model (in another terminal). llama3.1 is the default in config.yaml.
ollama pull llama3.1
# Smaller/faster alternative:
#   ollama pull mistral      (then set llm.ollama.model: mistral in config.yaml)
```

Apple Silicon runs these well. `llama3.1` (8B) needs ~8 GB RAM free; `mistral`
is lighter if you're constrained.

### 3. Add your free API keys

```bash
cp .env.example .env
```

Then open `.env` and fill in what you have. Each is **free**; sources with
missing keys are skipped automatically (the app logs a warning and continues).

- **Reddit** — `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`
  <br>TODO: create a free "script" app at <https://www.reddit.com/prefs/apps>.
- **YouTube** — `YOUTUBE_API_KEY`
  <br>TODO: free key in <https://console.cloud.google.com> → enable
  "YouTube Data API v3" (free tier: 10,000 units/day). Then set
  `sources.youtube.enabled: true` in `config.yaml`.
- **Google Trends** — no key needed (pytrends).
- **RSS** — no key needed.

> Grep the codebase for `TODO(user)` to find every spot that expects your own
> keys or wiring.

### 4. Configure your niche and brand

Edit `config.yaml` — set `niche.keywords`, `brand.voice`, which `sources` are
enabled, and the `schedule`. It's commented throughout.

### 5. Verify everything

```bash
python run.py doctor     # shows sources, which keys are present, and Ollama status
python run.py init-db    # create the SQLite database
```

---

## Running it

```bash
# One cycle now (great for testing) — discovers, analyses, and queues drafts.
python run.py once

# Normal use: start the scheduler AND the dashboard together.
python run.py run
#   → open the dashboard at http://127.0.0.1:8765

# Just the dashboard (review the queue without running discovery):
python run.py dashboard
```

### The approval workflow

1. The scheduler runs every `schedule.interval_minutes` (± jitter) and queues
   `pending` drafts.
2. Open **http://127.0.0.1:8765**. For each draft you can **edit** the caption /
   hashtags / attach a media path, then **Approve** or **Reject**. The
   **Insights** tab visualises everything the learning stack knows (bandit
   win-rates, title-model signals, learned vs. config weights, winner styles).
3. On an approved draft, click **Prepare to post**. That:
   - writes a ready-to-post file into `exports/` (caption + hashtags + media),
   - copies the caption+hashtags to your clipboard (macOS `pbcopy`),
   - optionally opens the platform's web composer (`publishing.open_browser`).
4. You post it yourself, then click **Mark as posted** (the *only* way a draft
   becomes `posted`).
5. On the **Performance** page, log the engagement your post earned. The
   analyser feeds that back in, nudging future topic scoring toward what works
   for you (`analysis.performance_learning_rate`).

---

## Autopilot — fully autonomous mode

Autopilot removes the human approver and runs the whole loop itself, posting
**YouTube Shorts** and learning from the results. It's configured under
`autopilot:` / `guardrails:` / `media:` / `youtube:` / `learning:` in
`config.yaml`.

### How a cycle works

```
discover → analyse → for each top topic (within today's canary budget):
   pick bandit arms (caption style, hashtag count, post hour)
   → compose draft with the local LLM
   → AUTOMATED GATE  (length · blocklist · topic-recency dedup · LLM self-critique 1-10)
        ├─ fail → store as rejected, move on
        └─ pass → render a Short (script → TTS → ffmpeg) → upload to YouTube
                  → later: pull stats → reward the learners
```

The **gate is what replaces you.** A draft only posts if it clears length
bounds, a banned-term blocklist, a topic-recency check, and an LLM self-critique
that scores it 1-10 on brand/clarity/honesty/safety (configurable minimum). If
the critique LLM is unreachable, the gate **fails closed** — it will not blind-post.

### Setup (one time)

1. **ffmpeg** (renders the video) and a TTS voice:
   ```bash
   brew install ffmpeg          # required for Shorts
   # TTS: macOS `say` works out of the box (free). For better voices, install
   # Piper (https://github.com/rhasspy/piper), download a .onnx voice, and set
   # media.tts: piper + media.piper_voice in config.yaml.
   ```
2. **YouTube upload auth** (uploading needs OAuth, not just an API key):
   - In Google Cloud Console, create an **OAuth client ID → Desktop app**,
     download the JSON, and point `YOUTUBE_OAUTH_CLIENT_SECRET` at it in `.env`.
   - Run the one-time browser flow:
     ```bash
     python run.py youtube-auth      # opens a browser, caches a refresh token
     ```
   - `python run.py doctor` should now show `youtube: ✓ auth ready`.

   > Quota reality: the free YouTube Data API is ~10,000 units/day and each
   > upload costs ~1,600, so ~5-6 uploads/day is the ceiling. The canary caps
   > stay under it.

### Run it — shadow first, then live

```bash
python run.py bootstrap           # warm-start from public winners (see below) — do this first
# config.yaml starts at autopilot.mode: shadow
python run.py autopilot           # one cycle now: generates + gates, DOES NOT upload
python run.py autopilot-run       # the autonomous scheduler + dashboard (still shadow)
```

Shadow-mode drafts land in the dashboard with status `shadow` — read them, sanity
-check the gate. When you trust it, set `autopilot.mode: live` in `config.yaml`
and restart. It begins at **1 post/day** (`autopilot.canary.start_per_day`) and
ramps by one per day — but only while engagement stays healthy — up to
`max_per_day`.

### Cold-start: bootstrap from public winners first

You don't have to teach it from zero. Before going live, warm-start the learners
from content **that's already out there and already winning** in your niche:

```bash
python run.py bootstrap          # run once (needs a YouTube key and/or Reddit creds)
python run.py bootstrap --force  # re-seed later from a fresher corpus
```

This pulls top-performing public content (YouTube top-by-views, high-upvote
Reddit posts — all via the free **read-only** APIs, no OAuth), maps each winner
onto the bandit's arm space (caption style, hashtag count, post hour), and folds
that evidence — **weighted by how well each piece performed** — into the bandit's
priors. So from post #1 the engine already leans toward what wins in the niche
instead of guessing uniformly.

`python run.py insights` (or the **Insights tab** in the dashboard, which shows
the same thing as bars — title-model coefficients, bandit win-rates, config-vs-
learned topic weights, and winner styles) shows the evidence, e.g.:

```
Bootstrap: done (218 public reference items)
  Winner styles: {'hook_first': 0.71, 'question': 0.58, 'listicle': 0.44, 'bold_claim': 0.31}
```

The same content features (`trendengine/learning/features.py`) are measured on
your own posts too, so the observational prior and your real results speak the
same language — your posts then refine the borrowed prior rather than starting a
separate one.

**Title virality model.** `bootstrap` also fits a small, interpretable model
(`trendengine/learning/title_model.py`) of *which title features correlate with
engagement* in the corpus — title length, whether it contains a number, whether
it's a question, hashtag count. The strongest signals become plain-English hints
that are injected into the draft prompt, so the LLM writes titles shaped like
what actually performs:

```
Title model coefficients: {'has_number': 0.09, 'word_count': 0.09, 'has_question': 0.0, ...}
  • Include a specific number or statistic — numbers correlate with higher engagement here.
  • Use a longer, more descriptive title (more words tend to win here).
```

It re-fits automatically as your own posts land (during `ingest`), blending the
borrowed signal with your real results. It's bounded ridge regression — no
runaway — and only emits a hint once it has enough samples
(`learning.min_samples_to_learn`).

### The learning loop (adapts from its own results)

Nothing here is manual — the engine measures itself and adjusts:

- **Auto-ingest** — `python run.py ingest` (also hourly under `autopilot-run`)
  pulls each live post's views/likes/comments from YouTube into a time-series.
- **Learned scoring weights** — a bounded ridge regression fits engagement on the
  topic features (frequency / growth / engagement) that were true at draft time.
  The learned, normalised weights are **blended over your `config.yaml` weights**,
  with confidence rising as more posts land (`learning.min_samples_to_learn`).
  So ranking drifts toward what actually performs for you.
- **Multi-armed bandit (Thompson sampling)** — for the knobs it controls (caption
  style, hashtag count, post-hour), each post is a "pull" and engagement is the
  reward. Winners get chosen more often; an exploration floor
  (`learning.bandit_explore`) keeps it trying alternatives.
- **Guardrails on the learner** — uniform priors, reward binarised against a
  running median (one viral fluke can't dominate), time-decay of old results, and
  a minimum sample count before anything is acted on.

See what it has learned so far:

```bash
python run.py insights
#  Canary: 2 posts/day
#  Learned weights (from 14 posts): {'frequency': 0.21, 'growth': 0.27, 'engagement': 0.52}
#  Bandit arms:
#    caption_style  hook_first   win_rate=0.61 pulls=9  mean_reward=0.0413
#    ...
```

> Honest expectation-setting: the *posting + learning infrastructure* is solid,
> but auto-generated Shorts from pure free-local tooling (TTS voice + captions
> over a solid background) start **rudimentary**. The upgrade path is in
> `trendengine/media/` — better TTS (Piper), stock/looping footage, or a real
> editor. The `bootstrap` step means the engine starts competent instead of
> blank, but transfer from other creators' results is a *prior*, not proof — your
> own posts still refine it, and the bandit's own-post signal firms up over the
> first few dozen live Shorts.

---

## Safety controls

- **Rate limits** — `sources.<name>.min_interval_seconds` gates each source.
- **Randomised intervals** — `schedule.jitter_seconds` / `autopilot.jitter_seconds`.
- **Daily cap** — `safety.max_drafts_per_day`; autopilot adds a `canary` ramp
  that starts at 1 post/day and only grows while engagement stays healthy.
- **Automated gate** (autopilot) — `guardrails:` blocklist, length bounds,
  topic-recency dedup, and an LLM self-critique threshold. Fails closed.
- **Shadow mode** — `autopilot.mode: shadow` runs everything except the upload.
- **Kill switch** — flip it from the dashboard, or:
  ```bash
  touch .killswitch      # hard-stops discovery AND autopilot
  rm .killswitch         # resume
  ```
  You can also set `safety.global_enabled: false` in `config.yaml`.

---

## Swapping the LLM to Claude (later)

The drafter only talks to the `LLMClient` interface, so switching is config-only:

1. `pip install anthropic`
2. Put `ANTHROPIC_API_KEY=...` in `.env` (from <https://console.anthropic.com/>).
3. In `config.yaml`:
   ```yaml
   llm:
     provider: anthropic
     anthropic:
       model: claude-sonnet-5
   ```

That's it — no code changes. To go back to free/local, set `provider: ollama`.
See `trendengine/llm/anthropic_client.py`.

---

## Publishers

- **`assisted`** (default for the dashboard) — prepare-only: export file +
  clipboard + optional composer. Never posts on its own.
- **`youtube`** (real; used by autopilot) — uploads rendered Shorts via the
  official YouTube Data API. See the Autopilot section for OAuth setup.
- **`meta_graph`, `tiktok`** (stubs) — official, free routes scaffolded with
  step-by-step instructions in their docstrings
  (`trendengine/publishers/meta_graph.py`, `tiktok.py`). Fill in `publish()`,
  add tokens to `.env`, and point `autopilot.publisher` at them to make one the
  autonomous target. Scraping-based posting is intentionally not implemented.

---

## Adding your own trend source

1. Subclass `Source` in `trendengine/sources/base.py` (implement `fetch()` and
   return `TrendItem`s).
2. Give it a unique `name` that matches a key under `sources:` in `config.yaml`.
3. Register it in `SOURCE_REGISTRY` in `trendengine/sources/__init__.py`.

---

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest           # 51 tests, no network required
```

The suite covers hashing/dedup, rate limiting, pandas scoring, the drafter,
the assisted publisher, and the kill switch — plus the autonomous stack: the
Thompson-sampling **bandit** (learns toward a rewarded arm), the ridge
**weight-learner** (favours the predictive feature, stays bounded), the
**quality gate** (rejects short/banned/low-critique drafts, fails closed), the
**Short** ffmpeg command builder, full **autopilot** shadow + live cycles
(gate → post → ingest → reward), the **public-winner bootstrap** (seeds the
bandit toward high-performing niche content before any own posts), and the
**title virality model** (learns the number/length/question/hashtag signal and
flows it into the prompt) — with fakes standing in for the LLM, ffmpeg, and
YouTube.

---

## Notes & limitations

- Google Trends (pytrends) is an unofficial endpoint and can rate-limit or
  change; it fails soft (logged, skipped) without breaking a run.
- Clipboard copy uses `pbcopy` on macOS via `pyperclip`; on a headless machine
  it degrades gracefully (the export file is still written).
- This tool prepares content and assists posting. **You** remain responsible for
  what you publish and for complying with each platform's terms.
