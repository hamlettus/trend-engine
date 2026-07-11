#!/usr/bin/env bash
#
# trend-engine one-shot deploy for a fresh Ubuntu server
# (built for Oracle Cloud Free Tier — Ampere ARM or x86 — but works on any
#  Ubuntu 22.04/24.04 VM). Run it once; it installs everything, sets up the
# app as an auto-restarting service, and prints how to reach the dashboard.
#
# From the Oracle Cloud Shell (or any SSH), paste ONE line:
#
#   curl -fsSL https://raw.githubusercontent.com/hamlettus/trend-engine/main/deploy/setup.sh | bash
#
# Optional environment overrides:
#   OLLAMA_MODEL=mistral        (default: llama3.1)
#   TAILSCALE_AUTHKEY=tskey-...  (installs Tailscale for private phone access)
#   REPO=https://github.com/you/trend-engine
#
set -euo pipefail

REPO="${REPO:-https://github.com/hamlettus/trend-engine}"
APP_DIR="${APP_DIR:-$HOME/trend-engine}"
MODEL="${OLLAMA_MODEL:-llama3.1}"
PORT="${DASHBOARD_PORT:-8765}"
# ollama (local LLM, needs ~8GB RAM) or groq (free hosted, runs on a tiny box).
LLM_PROVIDER="${LLM_PROVIDER:-ollama}"

log() { echo -e "\n\033[1;36m==> $*\033[0m"; }

log "Installing system packages (python, ffmpeg, git)…"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip ffmpeg git curl openssl

if [ "$LLM_PROVIDER" = "ollama" ]; then
  log "Installing Ollama (local LLM)…"
  if ! command -v ollama >/dev/null 2>&1; then
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  sudo systemctl enable --now ollama 2>/dev/null || true
  log "Pulling model '$MODEL' (this can take a few minutes)…"
  ollama pull "$MODEL"
else
  log "Using hosted LLM ($LLM_PROVIDER) — skipping Ollama (no local model needed)."
fi

log "Fetching the app…"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"

log "Setting up the Python environment…"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install -r requirements.txt

log "Configuring…"
[ -f .env ] || cp .env.example .env
if [ "$LLM_PROVIDER" = "ollama" ]; then
  # Point the local model at the pulled one.
  sed -i "s/^\(\s*model:\s*\).*llama3.1.*/\1\"$MODEL\"/" config.yaml || true
else
  # Switch config to the hosted provider (e.g. groq).
  sed -i "s/^\(\s*provider:\s*\)\"ollama\"/\1\"$LLM_PROVIDER\"/" config.yaml || true
  if [ "$LLM_PROVIDER" = "groq" ] && ! grep -q "^GROQ_API_KEY=." .env; then
    echo "  ⚠ GROQ_API_KEY is not set in .env yet — add it before drafting will work."
  fi
fi
# Generate a dashboard password if one isn't set.
if ! grep -q "^DASHBOARD_PASSWORD=." .env; then
  PW="$(openssl rand -base64 12)"
  if grep -q "^DASHBOARD_PASSWORD=" .env; then
    sed -i "s#^DASHBOARD_PASSWORD=.*#DASHBOARD_PASSWORD=${PW}#" .env
  else
    echo "DASHBOARD_PASSWORD=${PW}" >> .env
  fi
  echo "DASHBOARD_GENERATED_PW=${PW}" > "$APP_DIR/.dashboard_password.txt"
fi
grep -q "^DASHBOARD_USER=" .env || echo "DASHBOARD_USER=admin" >> .env

.venv/bin/python run.py init-db

# Optional: Tailscale for private, no-open-ports access from your phone.
if [ -n "${TAILSCALE_AUTHKEY:-}" ]; then
  log "Installing Tailscale…"
  curl -fsSL https://tailscale.com/install.sh | sh
  sudo tailscale up --authkey "$TAILSCALE_AUTHKEY" --hostname trend-engine || true
fi

log "Installing the auto-restarting service…"
sudo tee /etc/systemd/system/trend-engine.service >/dev/null <<EOF
[Unit]
Description=trend-engine (dashboard + autopilot + learning)
After=network-online.target ollama.service
Wants=network-online.target

[Service]
User=${USER}
WorkingDirectory=${APP_DIR}
Environment=DASHBOARD_HOST=0.0.0.0
Environment=DASHBOARD_PORT=${PORT}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/python run.py autopilot-run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now trend-engine

IP="$(curl -fsSL https://api.ipify.org 2>/dev/null || echo YOUR_SERVER_IP)"
PW_LINE="$(grep '^DASHBOARD_PASSWORD=' .env | cut -d= -f2-)"

cat <<DONE

\033[1;32m✔ trend-engine is running.\033[0m

  Dashboard:  http://${IP}:${PORT}
  Login:      admin  /  ${PW_LINE}

Next:
  • If you used Tailscale, open the dashboard at your server's Tailscale IP
    instead of the public one (no firewall change needed).
  • Otherwise, open port ${PORT} in your Oracle "Security List" (see
    deploy/PHONE-SETUP.md) — the password above protects it.
  • Add your API keys by editing ${APP_DIR}/.env, then: sudo systemctl restart trend-engine
  • Logs:    journalctl -u trend-engine -f
  • Update:  cd ${APP_DIR} && git pull && sudo systemctl restart trend-engine
DONE
