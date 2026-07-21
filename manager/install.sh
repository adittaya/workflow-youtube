#!/usr/bin/env bash
set -e

MANAGER_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$MANAGER_DIR")"
BIN="/usr/local/bin/vplink247"
SERVICE="/etc/systemd/system/vplink-manager.service"
MGR_PORT="${MANAGER_PORT:-8888}"

# ── Colors ──────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[ERR]${NC}   $1"; }

# ── Header ──────────────────────────────────────────────
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       VPLink 24/7 Manager — All-in-One Installer  ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# ── Pre-flight checks ───────────────────────────────────
info "Checking system requirements..."

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    err "Python3 is required. Install it: sudo apt install python3"
    exit 1
fi
ok "Python: $($PYTHON --version 2>&1)"

if ! command -v pip3 &>/dev/null && ! $PYTHON -m pip --version &>/dev/null; then
    err "pip is required. Install it: sudo apt install python3-pip"
    exit 1
fi
ok "pip available"

if ! command -v git &>/dev/null; then
    err "git is required. Install it: sudo apt install git"
    exit 1
fi
ok "git: $(git --version 2>&1)"

# ── Install Python deps ─────────────────────────────────
info "Installing Python dependencies..."
PIP_CMD="pip3 install --break-system-packages -q"
$PIP_CMD flask pynacl requests 2>/dev/null ||
    $PYTHON -m pip install --break-system-packages -q flask pynacl requests 2>/dev/null ||
    { warn "Trying without --break-system-packages..."; 
      pip3 install -q flask pynacl requests; }
ok "Python dependencies installed"

# ── Supabase credentials ────────────────────────────────
echo ""
echo -e "${YELLOW}── Supabase Configuration ──${NC}"
info "These are stored as env vars for the manager service."
info "They are set as GitHub secrets in each deployment repo."
echo ""

if [ -n "$SUPABASE_URL" ] && [ -n "$SUPABASE_KEY" ] && [ -n "$SUPABASE_SECRET" ]; then
    ok "SUPABASE credentials found in environment"
else
    read -p "Enter SUPABASE_URL (e.g. https://xyz.supabase.co): " SUPABASE_URL
    read -p "Enter SUPABASE_KEY (anon key): " SUPABASE_KEY
    read -sp "Enter SUPABASE_SECRET (service_role key): " SUPABASE_SECRET
    echo ""
    if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_KEY" ] || [ -z "$SUPABASE_SECRET" ]; then
        err "All three Supabase fields are required"
        exit 1
    fi
fi

# ── Create /etc/default/vplink-manager ───────────────────
ENV_FILE="/etc/default/vplink-manager"
info "Writing environment config to $ENV_FILE"
sudo tee "$ENV_FILE" > /dev/null <<EOF
SUPABASE_URL=$SUPABASE_URL
SUPABASE_KEY=$SUPABASE_KEY
SUPABASE_SECRET=$SUPABASE_SECRET
MANAGER_PORT=$MGR_PORT
MANAGER_HOST=0.0.0.0
MANAGER_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
EOF
sudo chmod 600 "$ENV_FILE"
ok "Environment config saved"

# ── Create vplink247 command ─────────────────────────────
info "Creating global command: vplink247"
sudo tee "$BIN" > /dev/null <<'SCRIPT'
#!/usr/bin/env bash
set -e

MANAGER_DIR="$(dirname "$(dirname "$(realpath "$0")")")/manager"
ENV_FILE="/etc/default/vplink-manager"
SERVICE="vplink-manager"
PORT="${MANAGER_PORT:-8888}"

[ -f "$ENV_FILE" ] && source "$ENV_FILE"

CMD="${1:-terminal}"
shift 2>/dev/null || true

case "$CMD" in
    web|start)
        echo "Starting VPLink Manager Web Interface..."
        if systemctl is-active vplink-manager &>/dev/null 2>&1; then
            echo "Already running (systemd). Open: http://localhost:$PORT"
        elif [ -f /etc/systemd/system/vplink-manager.service ]; then
            sudo systemctl start vplink-manager
            sudo systemctl enable vplink-manager 2>/dev/null
            echo "Service started (systemd)"
            echo "Web UI: http://localhost:$PORT"
        else
            cd "$MANAGER_DIR" && nohup python3 app.py > manager.log 2>&1 &
            echo "PID: $!"
            echo "Web UI: http://localhost:$PORT"
        fi
        ;;
    stop)
        echo "Stopping VPLink Manager..."
        if systemctl is-active vplink-manager &>/dev/null 2>&1; then
            sudo systemctl stop vplink-manager
            echo "Service stopped"
        else
            pkill -f "manager/app.py" 2>/dev/null && echo "Stopped" || echo "Not running"
        fi
        ;;
    restart)
        "$0" stop; sleep 1; "$0" start
        ;;
    status)
        if systemctl is-active vplink-manager &>/dev/null 2>&1; then
            echo "VPLink Manager Web: RUNNING (systemd)"
            systemctl status vplink-manager --no-pager 2>&1 | head -5
        elif pgrep -f "manager/app.py" &>/dev/null; then
            echo "VPLink Manager Web: RUNNING (background PID $(pgrep -f 'manager/app.py'))"
        else
            echo "VPLink Manager Web: STOPPED"
        fi
        echo ""
        echo "Web UI: http://localhost:$PORT"
        echo "Login:  admin / admin"
        echo ""
        echo "Terminal mode: vplink247"
        ;;
    terminal|tui|cli)
        cd "$MANAGER_DIR" && python3 cli.py
        ;;
    open)
        URL="http://localhost:$PORT"
        echo "Opening $URL ..."
        command -v xdg-open &>/dev/null && xdg-open "$URL" 2>/dev/null
        command -v open &>/dev/null && open "$URL" 2>/dev/null
        echo "Or visit: $URL"
        ;;
    logs)
        if systemctl is-active vplink-manager &>/dev/null 2>&1; then
            sudo journalctl -u vplink-manager -n 50 --no-pager "$@"
        else
            if [ -f "$MANAGER_DIR/manager.log" ]; then
                tail -n 50 "$MANAGER_DIR/manager.log"
            else
                echo "No log file found"
            fi
        fi
        ;;
    update)
        echo "Updating VPLink Manager..."
        cd "$MANAGER_DIR/.." && git pull
        echo "Update complete. Restart web: vplink247 restart"
        ;;
    install)
        cd "$MANAGER_DIR" && sudo bash install.sh
        ;;
    passwd)
        echo "Changing admin password..."
        cd "$MANAGER_DIR"
        python3 -c "
import sqlite3, hashlib, secrets, hmac
db = sqlite3.connect('manager.db')
pw = '$1'
if not pw: pw = __import__('random').choice(__import__('string').ascii_letters)*6 + '123'
salt = secrets.token_hex(16)
h = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 100000)
db.execute('UPDATE users SET password_hash=? WHERE username=?', (f'{salt}\${h.hex()}', 'admin'))
db.commit()
print(f'Password updated to: {pw}')
"
        ;;
    status|deploy|accounts|scan|credentials)
        # Pass through to CLI
        cd "$MANAGER_DIR" && python3 cli.py "$CMD"
        ;;
    *)
        echo "VPLink 24/7 Manager — Control Command"
        echo ""
        echo "Usage: vplink247 <command>"
        echo ""
        echo "  (no args)    Terminal mode — interactive menu"
        echo "  web|start    Start web interface"
        echo "  stop         Stop web interface"
        echo "  restart      Restart web interface"
        echo "  status       Show deployment status (terminal)"
        echo "  open         Open web UI in browser"
        echo "  logs         Show web server logs"
        echo "  update       Pull latest code from GitHub"
        echo "  install      Re-run the installer"
        echo "  passwd       Change admin password"
        echo "  accounts     List GitHub accounts"
        echo "  scan         Scan account for existing repos"
        echo "  credentials  View stored credentials"
        echo ""
        echo "Web UI: http://localhost:$PORT"
        echo "Login:  admin / admin"
        ;;
esac
SCRIPT
sudo chmod +x "$BIN"
ok "Global command created: vplink247"

# ── Create systemd service ───────────────────────────────
info "Setting up systemd service..."
sudo tee "$SERVICE" > /dev/null <<EOF
[Unit]
Description=VPLink 24/7 Manager
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$MANAGER_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$PYTHON $MANAGER_DIR/app.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload 2>/dev/null || true
ok "systemd service created: vplink-manager"

# ── Start service ───────────────────────────────────────
echo ""
info "Starting VPLink Manager..."
sudo systemctl enable vplink-manager 2>/dev/null && sudo systemctl start vplink-manager 2>/dev/null && {
    ok "Service started via systemd"
} || {
    warn "Could not start via systemd. Starting in background..."
    cd "$MANAGER_DIR" && nohup $PYTHON app.py > manager.log 2>&1 &
    echo "PID: $!"
}

# ── Done ─────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║        INSTALLATION COMPLETE!                    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}Web UI:${NC}     http://localhost:$MGR_PORT"
echo -e "  ${CYAN}Login:${NC}      admin / admin"
echo -e "  ${CYAN}Command:${NC}    vplink247          (terminal interactive mode)"
echo -e "  ${CYAN}Web UI:${NC}      vplink247 web      (start web interface)"
echo -e "  ${CYAN}Status:${NC}      vplink247 status   (terminal status view)"
echo ""
echo -e "  ${YELLOW}Change password:${NC}  vplink247 passwd <new_password>"
echo ""

# ── Create a quick config note ──────────────────────────
cat <<EOF | sudo tee /etc/vplink-welcome.txt > /dev/null
╔══════════════════════════════════════════════╗
║          VPLink 24/7 Manager                 ║
╠══════════════════════════════════════════════╣
║ Web UI:  http://localhost:$MGR_PORT             ║
║ Login:   admin / admin                       ║
║                                              ║
║ Commands:                                    ║
║   vplink247            Terminal interactive   ║
║   vplink247 web        Start web interface    ║
║   vplink247 stop       Stop web interface     ║
║   vplink247 status     Status overview        ║
║   vplink247 open       Open in browser        ║
║   vplink247 logs       View logs              ║
║   vplink247 update     Pull latest code       ║
╚══════════════════════════════════════════════╝
EOF
