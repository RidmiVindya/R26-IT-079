#!/usr/bin/env bash
#
# Smart Karawala - Raspberry Pi Auto-Installer
# Runs on the Raspberry Pi to set up Python venv, dependencies, and systemd service.
#
set -e

INSTALL_DIR="/home/$USER/oven_bridge"
echo "==> Setting up Oven Bridge in $INSTALL_DIR..."

mkdir -p "$INSTALL_DIR"
cp pi_oven_bridge.py "$INSTALL_DIR/"
cp requirements.txt "$INSTALL_DIR/"

cd "$INSTALL_DIR"
if [ ! -d ".venv" ]; then
    echo "==> Creating Python virtual environment..."
    python3 -m venv .venv
fi

echo "==> Installing dependencies..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "==> Configuring systemd auto-start service..."
sudo sed -i "s/User=pi/User=$USER/g" oven-bridge.service 2>/dev/null || true
sudo cp oven-bridge.service /etc/systemd/system/oven-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable oven-bridge.service
sudo systemctl restart oven-bridge.service

echo ""
echo "=========================================================="
echo " Smart Karawala Oven Bridge successfully installed!       "
echo " Service Status: sudo systemctl status oven-bridge       "
echo " Live Logs:      journalctl -u oven-bridge -f             "
echo " Test URL:       http://localhost:5000/api/telemetry     "
echo "=========================================================="
