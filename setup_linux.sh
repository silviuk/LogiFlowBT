#!/bin/bash
set -e

echo "=== LogiFlowBT Linux Setup ==="

# 1. Install udev rule for raw HID++ Logitech device access without root
echo "[1/4] Configuring udev rules for Logitech devices..."
UDEV_RULE_FILE="/etc/udev/rules.d/99-logitech-hidpp.rules"
if [ ! -f "$UDEV_RULE_FILE" ]; then
    echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", MODE="0666"' | sudo tee "$UDEV_RULE_FILE" > /dev/null
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    echo "  Installed $UDEV_RULE_FILE successfully."
else
    echo "  $UDEV_RULE_FILE already exists."
fi

# 2. Check recommendations
echo "[2/4] Checking optional utilities (xdotool, xclip, solaar)..."
for cmd in xdotool xclip solaar; do
    if command -v $cmd &> /dev/null; then
        echo "  [OK] $cmd is installed."
    else
        echo "  [INFO] $cmd not found. Optional, but recommended: sudo apt install -y $cmd"
    fi
done

# 3. Install Python dependencies
echo "[3/4] Installing Python requirements..."
pip3 install --user hidapi customtkinter

# 4. Create systemd user service
echo "[4/4] Setting up systemd user service (optional autostart)..."
SERVICE_DIR="$HOME/.config/systemd/user"
mkdir -p "$SERVICE_DIR"
cat << 'EOF' > "$SERVICE_DIR/logiflowbt.service"
[Unit]
Description=LogiFlowBT - Logitech Flow over Bluetooth
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -m btsync.app --daemon
WorkingDirectory=%h/btsync
Restart=always
RestartSec=3

[Install]
WantedBy=graphical-session.target
EOF

echo ""
echo "=== Setup Completed Successfully! ==="
echo "To test device scanning: python3 -m btsync.app --scan"
echo "To launch settings GUI:  python3 -m btsync.app --gui"
echo "To enable autostart:     systemctl --user enable --now logiflowbt.service"
