#!/bin/bash
# Called by ES on screensaver-start event.
# Signals the supervisor (running on tty1) to take over, then kills ES.
exec > /tmp/dashboard.log 2>&1
echo "screensaver-start fired at $(date)"

touch /tmp/dashboard_trigger

ES_BINARY="/opt/retropie/supplementary/emulationstation/emulationstation"
kill -9 $(pgrep -f "$ES_BINARY") 2>/dev/null
echo "ES killed — supervisor will launch dashboard"
