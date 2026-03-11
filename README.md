# Raspberry Pi Productivity Dashboard

A Toggl-powered productivity screensaver for **RetroPie** Raspberry Pis. After a period of inactivity, EmulationStation is replaced by a full-screen dashboard showing your tracked work hours, project breakdown, productivity debt, and historical comparisons.

> **RetroPie only.** The screensaver system hooks into EmulationStation. A plain Raspberry Pi without RetroPie would need a different idle trigger.

![Dashboard preview](preview.png)

---

## What it shows

- **Today** — hours tracked vs daily target, progress bar, debt
- **Projects today** — breakdown by Toggl project
- **This week** — per-day bar chart with target markers
- **Past 4 weeks** — actual vs target comparison
- **Debt** — today and accumulated week deficit

Targets: 5h on weekdays, 2h on weekends.

---

## Requirements

- Raspberry Pi running **RetroPie** (tested on Pi 4/5, Raspberry Pi OS Bookworm)
- A **Toggl** account with an API token
- A USB gamepad connected to the Pi
- Internet access from the Pi

---

## Installation

### 1. Clone the repo

```bash
ssh pi@<your-pi-ip>
cd ~/Projects
git clone https://github.com/yourusername/raspberry-dashboard.git dashboard
cd dashboard
```

### 2. Install Python dependencies

The project uses **system Python 3** (not a venv) because the system pygame ships with a compatible SDL version.

```bash
pip3 install matplotlib requests pyyaml --break-system-packages
```

### 3. Create your config

```bash
cp config.yaml.example config.yaml
nano config.yaml
```

Fill in your Toggl API token and workspace ID:
- **API token**: Toggl → Settings → Profile → API Token (bottom of page)
- **Workspace ID**: Toggl → Settings → Workspaces → click your workspace → the number in the URL

Set your timezone (IANA format, e.g. `Europe/Vienna`, `America/New_York`).

### 4. Hook into EmulationStation screensaver

```bash
mkdir -p ~/.emulationstation/scripts/screensaver-start
ln -sf ~/Projects/dashboard/screensaver_start.sh \
       ~/.emulationstation/scripts/screensaver-start/dashboard.sh
chmod +x ~/Projects/dashboard/screensaver_start.sh
```

### 5. Set up the autostart supervisor

```bash
echo "/home/pi/Projects/dashboard/supervisor.sh" \
  > /opt/retropie/configs/all/autostart.sh
chmod +x ~/Projects/dashboard/supervisor.sh
```

> This replaces the default `emulationstation #auto` line. The supervisor starts ES and manages the screensaver lifecycle.

### 6. (Optional) Add as a manual launch from ES Ports menu

```bash
mkdir -p ~/RetroPie/roms/ports
cat > ~/RetroPie/roms/ports/Dashboard.sh << 'EOF'
#!/bin/bash
cd /home/pi/Projects/dashboard
python3 dashboard.py
EOF
chmod +x ~/RetroPie/roms/ports/Dashboard.sh
```

### 7. Configure screensaver timeout in EmulationStation

In EmulationStation → UI Settings → Screensaver Settings:
- Set **Screensaver After** to your preferred idle time (e.g. 5 minutes)

Or edit directly:
```bash
sed -i 's/<int name="ScreenSaverTime" value="[^"]*" \/>/<int name="ScreenSaverTime" value="300000" \/>/' \
  ~/.emulationstation/es_settings.cfg
```

### 8. Reboot

```bash
sudo reboot
```

After reboot, EmulationStation will start via the supervisor. Leave it idle for your configured screensaver time and the dashboard will appear.

---

## Gamepad controls

| Button | Action |
|--------|--------|
| **Start** (button 9) | Dismiss dashboard, return to ES |
| **L1** (button 6) | Previous screen |
| **R1** (button 7) | Next screen |

Button numbers are for generic USB gamepads. If your controller differs, update `config.yaml`:

```yaml
dashboard:
  exit_button: 9
  prev_screen_button: 6
  next_screen_button: 7
```

To find your button numbers, check `/tmp/supervisor.log` while the dashboard is running — button events are logged there.

---

## How it works

### The tty1 problem

SDL2 requires DRM master on the Pi's HDMI controller (`/dev/dri/card1`) to render fullscreen. DRM master is only granted to processes running in an active physical session (tty1). Processes launched via SSH cannot get DRM master and SDL silently falls back to an offscreen (invisible) renderer.

**Solution:** `supervisor.sh` is launched by RetroPie's autologin on tty1. It owns the tty1 session, so any process it spawns (including the dashboard) inherits the session and can claim DRM master.

### Screensaver flow

```
ES idle → screensaver-start event
  → screensaver_start.sh writes /tmp/dashboard_trigger, kills ES
  → supervisor (tty1) detects ES exit + trigger file
  → launches python3 dashboard.py (tty1 context → DRM master → display works)
  → user presses Start → dashboard exits
  → supervisor restarts ES
```

---

## Project structure

```
dashboard.py          # pygame main loop + matplotlib rendering
toggl.py              # Toggl API client
metrics.py            # debt, targets, weekly/historical calculations
supervisor.sh         # tty1 loop: ES → dashboard → ES
screensaver_start.sh  # ES event hook: triggers supervisor handoff
pyproject.toml        # dependency manifest (uv)
config.yaml.example   # config template (copy to config.yaml)
```

---

## Adding new screens

Define a new renderer:

```python
def render_my_screen(data: dict, W: int, H: int) -> pygame.Surface:
    # create and return a pygame.Surface
    ...
```

Add it to the `screens` list in `dashboard.py`:

```python
screens = [render, render_my_screen]
```

L1/R1 cycle through screens automatically.
