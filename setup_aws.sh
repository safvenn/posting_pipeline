#!/usr/bin/env bash
# ==============================================================================
# setup_aws.sh — 1-Click AWS EC2 Setup for Autonomous Google Flow Video Worker
# ==============================================================================
# Runs on Ubuntu 20.04 / 22.04 / 24.04 (AWS EC2).
# Prepares the server to run headless Playwright Chromium and the Flow automation
# 24/7 without needing your laptop to be open or running.
#
# Usage:
#   chmod +x setup_aws.sh
#   ./setup_aws.sh
# ==============================================================================

set -euo pipefail

WORKER_DIR="/home/ubuntu/flow-worker"
VENV_DIR="${WORKER_DIR}/venv"
VIDEOS_DIR="/tmp/flow_videos"
COOKIE_PATH="/home/ubuntu/flow_cookies.json"
CRON_SCHEDULE="30 3,5,6 * * *"   # 03:30, 05:30, 06:30 UTC = 09:00 AM, 11:00 AM, 12:00 PM IST (Asia/Kolkata)

echo "======================================================================"
echo "🚀 Setting up Autonomous Google Flow Worker on AWS EC2"
echo "======================================================================"

# ------------------------------------------------------------------------------
# 1. RAM & Swap Check (Critical for t2.micro / t3.micro to avoid OOM)
# ------------------------------------------------------------------------------
TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
TOTAL_RAM_MB=$((TOTAL_RAM_KB / 1024))
echo "→ Detected System RAM: ${TOTAL_RAM_MB} MB"

if [ "${TOTAL_RAM_MB}" -lt 2000 ]; then
    SWAP_EXISTS=$(swapon --show | wc -l)
    if [ "${SWAP_EXISTS}" -le 1 ]; then
        echo "⚠️  RAM is under 2GB. Creating a 2GB swapfile to prevent Chromium OOM crash..."
        sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
        sudo chmod 600 /swapfile
        sudo mkswap /swapfile
        sudo swapon /swapfile
        if ! grep -q "/swapfile" /etc/fstab; then
            echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
        fi
        echo "✅ 2GB Swap activated successfully."
    else
        echo "✓ Swap is already active."
    fi
fi

# ------------------------------------------------------------------------------
# 2. Install OS Dependencies for Headless Chromium & Python
# ------------------------------------------------------------------------------
echo "→ Updating package manager and installing dependencies..."
sudo apt-get update -y
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    wget \
    cron

# Install asound library (handles Ubuntu 24.04 libasound2t64 vs 22.04 libasound2)
sudo apt-get install -y libasound2t64 || sudo apt-get install -y libasound2 || true

# ------------------------------------------------------------------------------
# 3. Setup Worker Directory & Virtual Environment
# ------------------------------------------------------------------------------
echo "→ Setting up directory structure at ${WORKER_DIR}..."
mkdir -p "${WORKER_DIR}"
mkdir -p "${VIDEOS_DIR}"
chmod 777 "${VIDEOS_DIR}"

if [ ! -d "${VENV_DIR}" ]; then
    echo "→ Creating Python virtual environment..."
    python3 -m venv "${VENV_DIR}"
fi

echo "→ Installing Python packages (playwright, httpx)..."
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install playwright httpx python-dotenv

echo "→ Installing Playwright Chromium browser binary & system deps..."
"${VENV_DIR}/bin/playwright" install chromium
sudo "${VENV_DIR}/bin/playwright" install-deps chromium || true

# ------------------------------------------------------------------------------
# 4. Create Daily Execution Script (run_daily.sh)
# ------------------------------------------------------------------------------
RUNNER_SCRIPT="${WORKER_DIR}/run_daily.sh"
cat << 'EOF' > "${RUNNER_SCRIPT}"
#!/usr/bin/env bash
# Flow Auto-Generation Worker Runner (9:00 AM, 11:00 AM, 12:00 PM IST)
set -a
[ -f /home/ubuntu/flow-worker/.env ] && . /home/ubuntu/flow-worker/.env
set +a

WORKER_DIR="/home/ubuntu/flow-worker"
VENV_PYTHON="${WORKER_DIR}/venv/bin/python"
LOG_FILE="${WORKER_DIR}/worker.log"
LOCK_FILE="/tmp/flow_worker.lock"

# Concurrency Guard: prevent overlapping worker runs
exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
    echo "[$(date -u)] Flow worker is already running. Skipping trigger." >> "${LOG_FILE}"
    exit 0
fi

export FLOW_COOKIE_FILE="${FLOW_COOKIE_FILE:-/home/ubuntu/flow_cookies.json}"
export FLOW_DOWNLOAD_DIR="${FLOW_DOWNLOAD_DIR:-/tmp/flow_videos}"
export PIPELINE_URL="${PIPELINE_URL:-https://posting-pipeline.onrender.com}"

echo "==========================================================" >> "${LOG_FILE}"
echo "Triggered Flow Worker at $(date -u) (UTC)" >> "${LOG_FILE}"
echo "==========================================================" >> "${LOG_FILE}"

cd "${WORKER_DIR}"
"${VENV_PYTHON}" auto_generate_worker.py \
    --pipeline-url "${PIPELINE_URL}" \
    --api-key "${API_KEY}" \
    --channel "${CHANNEL:-the_indian_kitchen}" \
    --max-videos "${MAX_VIDEOS:-1}" \
    >> "${LOG_FILE}" 2>&1

EXIT_CODE=$?
echo "Worker exited with code ${EXIT_CODE} at $(date -u)" >> "${LOG_FILE}"
exit ${EXIT_CODE}
EOF

chmod +x "${RUNNER_SCRIPT}"
echo "✅ Runner script created at ${RUNNER_SCRIPT}."

# ------------------------------------------------------------------------------
# 5. Setup Default .env Configuration
# ------------------------------------------------------------------------------
ENV_FILE="${WORKER_DIR}/.env"
if [ ! -f "${ENV_FILE}" ]; then
    cat << EOF > "${ENV_FILE}"
# Flow Worker Settings
PIPELINE_URL=https://posting-pipeline.onrender.com
API_KEY=
CHANNEL=the_indian_kitchen
MAX_VIDEOS=1
FLOW_COOKIE_FILE=/home/ubuntu/flow_cookies.json
FLOW_DOWNLOAD_DIR=/tmp/flow_videos

# Email Alert Settings (sent when Google Flow cookies expire)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
NOTIFICATION_EMAIL_TO=
EOF
    echo "✅ Created default config at ${ENV_FILE}"
fi

# ------------------------------------------------------------------------------
# 6. Configure Daily Cron Jobs & Pre-warm Pings (09:00 AM, 11:00 AM, 12:00 PM IST)
# ------------------------------------------------------------------------------
sudo systemctl enable cron
sudo systemctl start cron

# Pre-warm Render container 2 minutes before worker runs so cold start is eliminated
WARMUP_SCHEDULE="28 3,5,6 * * *"  # 03:28, 05:28, 06:28 UTC = 08:58, 10:58, 11:58 AM IST
WARMUP_CMD="${WARMUP_SCHEDULE} curl -s -m 90 https://posting-pipeline.onrender.com/api/health >/dev/null 2>&1"
CRON_CMD="${CRON_SCHEDULE} ${RUNNER_SCRIPT} >> ${WORKER_DIR}/cron.log 2>&1"

EXISTING_CRON=$(crontab -l 2>/dev/null || true)
FILTERED_CRON=$(echo "${EXISTING_CRON}" | grep -v "run_daily.sh" | grep -v "api/health" || true)
printf "%s\n%s\n%s\n" "${FILTERED_CRON}" "${WARMUP_CMD}" "${CRON_CMD}" | sed '/^$/d' | crontab -

echo "✅ Cron & Warmup configured for 09:00 AM, 11:00 AM, 12:00 PM IST (03:30, 05:30, 06:30 UTC):"
crontab -l | grep -E "run_daily.sh|api/health"

echo "======================================================================"
echo "🎉 AWS Worker Setup Complete!"
echo "======================================================================"
echo "Next steps:"
echo "1. On your laptop, export cookies: python export_cookies.py"
echo "2. Copy flow_cookies.json to: ${COOKIE_PATH}"
echo "3. Copy flow_playwright.py & auto_generate_worker.py to: ${WORKER_DIR}/"
echo "4. Test manually anytime on AWS with: ${RUNNER_SCRIPT}"
echo "======================================================================"
