#!/bin/bash
# Runs on tty1 (via autostart.sh) — the key that gives DRM master access.
# Loops: ES → (idle trigger) → dashboard → ES → ...

DASHBOARD_DIR="/home/pi/Projects/dashboard"
TRIGGER="/tmp/dashboard_trigger"
UV="/home/pi/.local/bin/uv"

while true; do
    rm -f "$TRIGGER"

    echo "[supervisor] starting EmulationStation"
    TERM=linux emulationstation

    if [ -f "$TRIGGER" ]; then
        echo "[supervisor] screensaver triggered — launching dashboard"
        rm -f "$TRIGGER"
        cd "$DASHBOARD_DIR"
        python3 -u dashboard.py > /tmp/supervisor.log 2>&1
        echo "[supervisor] dashboard exited"
    else
        echo "[supervisor] ES exited normally — restarting"
    fi
done
