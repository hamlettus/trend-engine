# Run trend-engine on a cheap VPS (PayPal — no Oracle, no card hassle)

Oracle's card check rejecting you? Use a normal VPS instead. This guide uses
**DigitalOcean** (beginner-friendly, takes **PayPal**, usually gives new users
**$200 free credit** for 60 days). **Vultr, Hetzner, and Linode** work
identically — all take PayPal; just create an Ubuntu server and run the same
installer.

Because we use **Groq** (free hosted LLM), a tiny/cheap server is plenty — no
need for the big-RAM box Oracle was for. Everything is done from your phone.

Cost: ~**$6/month** (or **$0** while DigitalOcean's free credit lasts).

---

## Step 1 — Sign up (👤 ~5 min)

1. Phone browser → **digitalocean.com** → **Sign up**.
2. When it asks for payment, choose **PayPal** (avoids the card problem). New
   accounts usually get **$200 credit / 60 days** — that's months of free running.

## Step 2 — Create the server ("Droplet") (👤 ~3 min)

1. **Create → Droplets**.
2. **Choose an image:** Ubuntu **24.04 (LTS)**.
3. **Choose a region** near you.
4. **Size:** Basic → Regular → **$6/mo (1 GB / 1 vCPU)** is the sweet spot
   (the $4 512 MB works but is tight for video). 2 GB ($12) is comfy if you'll
   clip a lot.
5. **Authentication:** pick **Password** (easier from a phone than SSH keys) and
   set a strong root password — save it.
6. **Create Droplet.** When it's ready, note its **public IP**.

## Step 3 — Open the in-browser terminal (👤 ~1 min)

1. Open your Droplet → **Access** → **Launch Droplet Console**. This is a Linux
   terminal **in your browser** — no SSH app needed.
2. Log in as **root** with the password you set.

## Step 4 — Run the one-line installer (👤 paste, then ~5 min wait)

Paste this (note the `LLM_PROVIDER=groq` — it skips the local model):

```
curl -fsSL https://raw.githubusercontent.com/hamlettus/trend-engine/main/deploy/setup.sh | LLM_PROVIDER=groq bash
```

It installs Python + ffmpeg, sets up the app as an auto-restarting service, and
prints your **dashboard URL + password**. Screenshot that.

## Step 5 — Add your Groq key (👤 ~2 min)

```
nano /root/trend-engine/.env      # set GROQ_API_KEY=...   (save: Ctrl-O, Enter, Ctrl-X)
sudo systemctl restart trend-engine
```

Free key from **console.groq.com/keys**. Check it worked:
```
cd /root/trend-engine && .venv/bin/python run.py doctor    # should show: groq … ready
```

## Step 6 — Open the dashboard from your phone (👤 ~1 min)

- DigitalOcean droplets have **no cloud firewall by default**, so just open:
  **`http://YOUR_DROPLET_IP:8765`** in your phone browser and log in with `admin`
  and the generated password.
- If you added a DO **Cloud Firewall**, add an inbound rule: **TCP 8765**.

> **More secure (recommended):** use **Tailscale** so the dashboard is never
> public. Free account at tailscale.com, install the phone app, make an auth key,
> and re-run the installer with it:
> ```
> curl -fsSL .../deploy/setup.sh | LLM_PROVIDER=groq TAILSCALE_AUTHKEY=tskey-xxxx bash
> ```
> Then open the dashboard at the server's Tailscale IP — only your devices reach it.

---

## Provider swap-ins (all take PayPal)

| Provider | Cheapest usable | Notes |
|----------|-----------------|-------|
| **DigitalOcean** | $6/mo (1 GB) | $200/60-day credit; easiest UI; browser console |
| **Vultr** | $5/mo (1 GB) | also takes crypto; "View Console" in browser |
| **Hetzner** | ~€4/mo (2 GB!) | best value; may ask for ID on new accounts |
| **Linode/Akamai** | $5/mo (1 GB) | Google Pay/PayPal; "Launch LISH Console" |

For any of them: create an **Ubuntu 22.04/24.04** server, open its browser
console, and run the same Step 4 command. The installer is provider-agnostic.

## From here

Continue with **[`GO-LIVE.md`](../GO-LIVE.md)** from **Phase 3** (you've now done
Phases 1–2). Manage the server with:

```
journalctl -u trend-engine -f                                       # live logs
sudo systemctl restart trend-engine                                 # after edits
cd /root/trend-engine && git pull && sudo systemctl restart trend-engine   # update
```
