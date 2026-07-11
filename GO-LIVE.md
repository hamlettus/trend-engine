# Go-live checklist

The exact ordered path from here to your first live, paid clip. Do the phases in
order — each unlocks the next. ⏱ = rough time, 👤 = only you can do it,
🤖 = the app does it.

> Golden rule: stay in **shadow mode** (generates but doesn't upload) until you've
> watched a few runs in the dashboard and like what you see. Then flip to live.

---

## Phase 0 — Accounts (👤 ~30–45 min total)

- [ ] **Oracle Cloud** free account — the server. (Needs a card for ID check; the
      Always Free tier isn't charged.) → cloud.oracle.com
- [ ] **Groq** free API key — the LLM + Whisper. → console.groq.com/keys
- [ ] **A clipping campaign to join** — where the *authorized* content + pay come
      from (e.g. a Whop clipping program, or a direct deal with a creator). You
      can start Phase 1–3 without this, but you can't earn until you have it.

> Platform accounts (YouTube etc.) come in Phase 5 — you don't need them yet.

---

## Phase 1 — Stand up the server (👤 ~20 min, mostly waiting)

Pick your host guide:
- Oracle Cloud (free, if their card check accepts you): **`deploy/PHONE-SETUP.md`**
- ~$6/mo VPS via PayPal (DigitalOcean etc.): **`deploy/VPS-SETUP.md`** ← use this
  if Oracle rejected your card

Then (Oracle path shown; the VPS guide has its own equivalents):

- [ ] Create the Ubuntu VM (Ampere, ~12 GB RAM) and note its public IP.
- [ ] In the browser Cloud Shell, paste the one-line installer.
- [ ] Screenshot the dashboard URL + password it prints.
- [ ] Open the dashboard port (or set up Tailscale for private access).
- [ ] Open the dashboard in your phone, log in. **You should see the empty queue.**

✅ Checkpoint: the dashboard loads on your phone.

---

## Phase 2 — Keys & settings (👤 ~10 min)

In the Cloud Shell:

```bash
nano ~/trend-engine/.env      # paste GROQ_API_KEY=...  (save: Ctrl-O, Enter, Ctrl-X)
nano ~/trend-engine/config.yaml   # set:  llm:\n  provider: groq
sudo systemctl restart trend-engine
```

- [ ] `GROQ_API_KEY` set in `.env`
- [ ] `llm.provider: groq` in `config.yaml` (so you don't need the local model)
- [ ] Restarted the service

✅ Checkpoint: `cd ~/trend-engine && .venv/bin/python run.py doctor` shows
`groq … ready`.

---

## Phase 3 — Prove the pipeline in shadow (👤 5 min + 🤖)

Warm up the learning with public winners, then dry-run a clip on YOUR OWN test
video (or any video you have the right to use) to confirm cuts + captions look
right — **no uploading yet**.

- [ ] `.venv/bin/python run.py bootstrap` (learns from public top performers)
- [ ] Add a test campaign to `campaigns.yaml` with **your own** video as the
      source, `authorized: true`, and an honest note.
- [ ] Trigger it from the dashboard **Campaigns** tab → **Run (shadow)**.
- [ ] Watch the **Queue** — clips should appear. Play them. Check the 9:16 crop,
      subtitles, and caption/credit.

✅ Checkpoint: you're looking at real vertical clips with captions in the queue.

---

## Phase 4 — Get a real authorized campaign (👤 — the real starting gun)

- [ ] Join a clipping program / close a creator deal.
- [ ] Put its **authorized source video(s)**, **per-view rate**, **required
      hashtags**, **@credit**, and any **tracking tag** into `campaigns.yaml`.
- [ ] Set `authorized: true` + an `authorization_note` naming the program/license.

> Until this exists, everything downstream is just rehearsal. This is the step
> that turns the machine into income.

---

## Phase 5 — YouTube auth + your first LIVE clip (👤 ~15 min + 🤖)

- [ ] Create a Google Cloud OAuth client (Desktop app) → download the JSON →
      point `YOUTUBE_OAUTH_CLIENT_SECRET` at it in `.env`. (README → Autopilot.)
- [ ] `.venv/bin/python run.py youtube-auth` → open the link on your phone, approve.
- [ ] `doctor` shows `youtube … ready`.
- [ ] In `config.yaml` set `autopilot.mode: live`, restart the service.
- [ ] Dashboard → Campaigns → **Run** with **upload live** checked.

✅ Checkpoint: a clip is live on YouTube. 🎉 Log its link if the campaign needs it.

---

## Phase 6 — Let it run itself (👤 2 min)

- [ ] In `config.yaml`, list your campaign under `autopilot.clip_campaigns: [...]`.
- [ ] Confirm `autopilot.canary.start_per_day` (begins at 1/day, ramps up while
      engagement stays healthy) and restart.
- [ ] Check the **Insights** tab over the next days: earnings, bandit win-rates,
      and the title model should start moving.

Now it clips, posts, measures, and learns on its own — you just review and steer.

---

## Phase 7 — Add platforms later (👤, when approved)

- [ ] Apply for **TikTok** Content Posting API and/or **Meta** Reels (Graph API) —
      these take days of review.
- [ ] Wire up `publish()` in the matching stub (`trendengine/publishers/`), add
      the platform to a campaign's `platforms`. (Ping me — I'll implement it.)

---

## When something breaks

The **first live run will probably hit one snag** (a yt-dlp quirk, an ffmpeg
flag, an API scope). That's expected. Grab the log and send it to me:

```bash
journalctl -u trend-engine -n 100 --no-pager
```

Paste that (or any error) into our chat and I'll fix it fast.

---

### The one-line reality check
Phases 1–3, 5–6 are mostly **tapping and pasting**. Phase **4** (real authorized
campaigns) and the Phase 5/7 **platform approvals** are the parts only you can do,
and they're what actually decide whether this earns.
