# Run trend-engine from your phone (Path A: free always-on server)

Your phone is the **remote control**, not the engine. The app runs 24/7 on a
free cloud server; you review, trigger, and monitor it from your phone's browser.
Total cost: **$0** (Oracle Cloud Free Tier). Everything below is done on your
phone.

---

## What you'll end up with

- A free Linux server that runs the whole app forever (survives reboots).
- A password-protected dashboard you open in your phone browser to approve clips,
  trigger campaigns, and watch earnings.

---

## Step 1 — Create a free Oracle Cloud account (~10 min)

1. In your phone browser go to **cloud.oracle.com** → **Start for free**.
2. Sign up. It asks for a card **for identity verification only** — the
   Always Free resources don't charge. Pick a home region near you.

> Why Oracle: their "Always Free" tier includes an Arm VM with up to 4 cores and
> **24 GB RAM** — enough to run the local LLM — at no cost. Other free tiers
> either sleep or lack the RAM.

## Step 2 — Create the server (~5 min)

1. In the Oracle console (hamburger menu) → **Compute** → **Instances** →
   **Create instance**.
2. **Image and shape** → change shape to **Ampere (VM.Standard.A1.Flex)**, set
   ~2 OCPU / 12 GB (or 4/24 if available). Image: **Canonical Ubuntu 22.04**.
3. Under **Networking**, leave defaults but make sure **"Assign a public IPv4
   address"** is on.
4. **Add SSH keys** → choose **"No SSH keys"** is *not* available; instead pick
   **"Generate a key pair for me"** and tap **Save private key** (you won't
   really need it — we use Cloud Shell next).
5. Tap **Create**. Wait until the instance is **Running**. Note its **Public IP**.

## Step 3 — Run the one-line installer (~10 min, mostly waiting)

1. In the Oracle console top bar, tap the **`>_` Cloud Shell** icon. This opens a
   Linux terminal **in your browser** — no SSH app needed.
2. Connect Cloud Shell to your instance, or just SSH from it:
   ```
   ssh ubuntu@YOUR_PUBLIC_IP
   ```
   (Accept the key prompt. If it asks for a key, use the one you saved in Step 2
   via Cloud Shell's upload, or enable Cloud Shell's "instance access".)
3. Paste this single line and press enter:
   ```
   curl -fsSL https://raw.githubusercontent.com/hamlettus/trend-engine/main/deploy/setup.sh | bash
   ```
4. It installs Python, ffmpeg, Ollama, pulls the model, and starts the service.
   When it finishes it prints your **dashboard URL and password** — screenshot
   that.

## Step 4 — Open the dashboard port (~2 min)

1. Oracle console → your instance → **Virtual Cloud Network** → **Security
   Lists** → the default list → **Add Ingress Rule**:
   - Source CIDR: `0.0.0.0/0`
   - IP Protocol: **TCP**, Destination Port: **8765**
2. Also allow it through the server firewall (paste in the SSH session):
   ```
   sudo iptables -I INPUT 6 -p tcp --dport 8765 -j ACCEPT
   sudo netfilter-persistent save 2>/dev/null || true
   ```

> **More secure option (recommended):** instead of Steps 4, use **Tailscale** so
> the dashboard is never public. Make a free account at tailscale.com, install
> the Tailscale app on your phone, create an **auth key** in its admin console,
> and re-run the installer with it:
> ```
> TAILSCALE_AUTHKEY=tskey-xxxx curl -fsSL .../deploy/setup.sh | bash
> ```
> Then open the dashboard at the server's Tailscale IP — only your devices can
> reach it, no open ports.

## Step 5 — Use it from your phone

1. Open **`http://YOUR_PUBLIC_IP:8765`** (or the Tailscale IP) in your phone
   browser. Log in with `admin` and the generated password.
2. **Campaigns** tab → trigger a clip run. **Queue** → review clips.
   **Insights** → watch earnings and what it's learning.
3. Bookmark it / add to home screen for one-tap access.

---

## Adding your keys and campaigns (from the phone)

Everything the app needs lives in two files on the server. Edit them in the SSH
session (Cloud Shell), then restart:

```
nano ~/trend-engine/.env            # API keys (Reddit, YouTube, dashboard pw)
nano ~/trend-engine/campaigns.yaml  # your authorized clip campaigns
sudo systemctl restart trend-engine
```

- **YouTube upload auth** (needed to publish): run once and follow the link it
  prints (open it in your phone browser to approve):
  ```
  cd ~/trend-engine && .venv/bin/python run.py youtube-auth
  ```

## Handy commands (paste in the SSH session)

```
journalctl -u trend-engine -f                      # live logs
sudo systemctl restart trend-engine                # restart after config changes
cd ~/trend-engine && git pull && sudo systemctl restart trend-engine   # update
```

## Honest notes

- **Platform API approval is the real wait**, not the server: YouTube uploads
  work quickly; TikTok and Meta Reels publishing require developer accounts and
  app review (days). YouTube is the fastest path to your first live clip.
- The Always Free Arm capacity is popular; if "out of capacity" appears at
  Step 2, try a different availability domain or retry later.
- Keep `autopilot.mode: shadow` until you've watched a few runs in the dashboard;
  flip to `live` only when you trust what it's producing.
