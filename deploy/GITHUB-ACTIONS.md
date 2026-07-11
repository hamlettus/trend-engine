# Run trend-engine free on GitHub Actions (no server, no card)

The free path. It runs on GitHub's own computers, on a schedule, using the
account you already have. There's no live dashboard — instead each run writes a
summary you read on your phone in the **GitHub mobile app**, and the clips come
out as downloadable artifacts. Everything below is done on **github.com** or the
GitHub app.

Cost: **$0.** No card, no server, no signup beyond GitHub.

---

## One-time setup (👤 ~5 min, all on your phone)

### 1. Add your Groq key as a secret

1. Get a free key at **console.groq.com/keys**.
2. On github.com, open your repo → **Settings** → **Secrets and variables** →
   **Actions** → **New repository secret**.
3. Name: `GROQ_API_KEY`  ·  Value: your key  ·  **Add secret**.

### 2. Turn on Actions

1. Repo → **Actions** tab. If it asks, **enable workflows**.
2. You'll see the **clip** workflow. It runs automatically every 6 hours, or you
   can tap **Run workflow** to run it now.

That's it — it's live. With no campaign configured yet it runs harmlessly (makes
nothing); add one next.

### 3. Add an authorized campaign

Edit **`campaigns.yaml`** right on github.com (open the file → ✏️ pencil →
commit): set your authorized source video(s), rate, hashtags, `@credit`, and
`authorized: true` + a note. Then in **`config.yaml`** add its id under
`autopilot.clip_campaigns: ["your-id"]` and commit.

Next run, it'll clip that source.

---

## Where you see results (on your phone)

- **Summary:** open **`state/SUMMARY.md`** in the repo (GitHub app) — last run,
  recent clips, estimated earnings, and what it's learning. It refreshes itself
  every run.
- **The actual clip files:** Actions tab → the latest **clip** run → scroll to
  **Artifacts** → download `clips` (kept 7 days).

---

## Going live (posting), later

It starts in **shadow mode** — it makes clips but posts nothing, so you can check
them first. To actually post:

1. Set `autopilot.mode: live` in `config.yaml`.
2. Add the platform's posting credentials as more repository **secrets** (e.g.
   YouTube). ⚠️ Authorizing YouTube uploads needs a one-time login that's awkward
   phone-only — ping me and we'll do that step together (a device-code login you
   approve on your phone).

Until then, download the clips from Artifacts and post the good ones yourself.

---

## Good to know

- **Free minutes:** public repos get unlimited Actions minutes; private repos get
  2,000 min/month — plenty for a few runs a day. (Make the repo public in
  Settings if you ever run low; your secrets stay private either way.)
- **Schedule:** change the `cron:` line in `.github/workflows/clip.yml` to run
  more/less often. GitHub sometimes delays scheduled runs a few minutes under
  load — normal.
- **It remembers between runs:** state (what it's seen, learned, earned) is saved
  back into the repo's `state/` folder automatically.

## When something breaks

Actions tab → the failed run → open the step that's red → copy the error → paste
it to me and I'll fix it.
