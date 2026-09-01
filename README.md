# LogiFlowBT

Seamless cross-platform (Windows & Linux) software that transfers your **Logitech MX Keys** keyboard and **Logitech M370 / POP Mouse** between two hosts when the mouse cursor reaches the border of the screen—just like **Logitech Flow**, but operating **autonomously over Bluetooth and Unifying receivers** without requiring any local network!

---

## Why LogiFlowBT?

Official Logitech Flow has two significant limitations:
1. **No Linux Support**: Logitech Options+ is not available on Linux.
2. **Network Dependency**: Official Flow mandates that both computers share the same Wi-Fi/LAN subnet with open ports, which fails on VPNs, corporate firewalls, or isolated PCs.

**LogiFlowBT** eliminates both limitations:
- **Autonomous Multi-Protocol Support**: Automatically detects and switches your Logitech devices whether they are connected via **Direct Bluetooth**, **Unifying Receivers**, **Logi Bolt Receivers**, or a combination (e.g. keyboard on Unifying receiver and mouse on Bluetooth).
- **Logitech HID++ 2.0 Feature `0x1814` (`CHANGE_HOST`)**: Issues hardware channel switch commands directly to all connected Easy-Switch peripherals simultaneously.
- **Dual Operating Modes**: Can operate completely autonomously on each host with **zero inter-PC connection**, or link the two hosts peer-to-peer over **Bluetooth RFCOMM** for cursor entry alignment and clipboard sync without any LAN/Wi-Fi connection.

---

## Autonomous Multi-Protocol Architecture

You don't need to specify whether your devices are paired via Bluetooth or a Unifying receiver:

```
+-----------------------------------------------------------------------------------+
|                            LogiFlowBT Autonomous Engine                           |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  [ Screen Edge Detector ] ===> triggers when cursor dwells on screen border       |
|                                                                                   |
|  [ Autonomous Dispatcher ]                                                        |
|         |                                                                         |
|         +---> If connected via Bluetooth:                                         |
|         |     Sends 20-byte Long HID++ Report (0x11) on UsagePage 0xFF43          |
|         |                                                                         |
|         +---> If connected via Unifying Receiver:                                 |
|         |     - Sends 20-byte Long Report (0x11) on Endpoint Col02                |
|         |     - Sends 7-byte Short Report (0x10) on Endpoint Col01 (fallback)     |
|         |                                                                         |
|         +---> If connected via Logi Bolt Receiver:                                |
|               Sends 20-byte Long Report (0x11) to Bolt paired device index        |
|                                                                                   |
|  ===> MX Keys & M370 Mouse switch Easy-Switch channels simultaneously!            |
+-----------------------------------------------------------------------------------+
```

---

## Operating Modes

### Mode 1: Autonomous Edge Switch (Zero Inter-PC Connection)
- **How it works**:
  - Run LogiFlowBT on Host 1 (e.g. Windows) with Trigger Edge set to `Right` and Target Channel set to `2`.
  - Run LogiFlowBT on Host 2 (e.g. Linux) with Trigger Edge set to `Left` and Target Channel set to `1`.
- When your mouse cursor dwells against the right edge of Host 1, Host 1 commands both MX Keys and M370 (over Bluetooth or Unifying) to jump to Channel 2.
- When working on Host 2, moving the mouse to the left edge causes Host 2 to command the devices back to Channel 1.
- **Requirement**: Zero inter-PC communication! The devices handle the RF switch between the computers.

### Mode 2: Bluetooth Inter-Host Sync (RFCOMM)
- In addition to hardware channel switching, the two hosts link peer-to-peer over Bluetooth RFCOMM:
  - **Cursor Entry Coordinate Alignment**: Smooth transition where the cursor arrives at the exact relative height ($Y$-ratio) where it left the previous screen.
  - **Clipboard Sync**: Automatically synchronizes copied text between Windows and Linux.

---

## Quick Start Guide

### 1. Windows Setup

1. Open PowerShell or Command Prompt in the `btsync` directory.
2. Run the setup script:
   ```cmd
   setup_windows.bat
   ```
   Or manually install dependencies:
   ```cmd
   python -m pip install hidapi bleak
   ```
3. Verify device detection (shows Bluetooth, Unifying, and Bolt devices):
   ```cmd
   python -m btsync.app --scan
   ```
4. Launch the graphical interface:
   ```cmd
   run_gui.bat
   ```
   Or run the background daemon:
   ```cmd
   run_daemon.bat
   ```

### 2. Linux Setup

1. Open terminal in the `btsync` folder.
2. Run the Linux setup script:
   ```bash
   chmod +x setup_linux.sh
   ./setup_linux.sh
   ```
   *Note: This configures the `/etc/udev/rules.d/99-logitech-hidpp.rules` file to grant non-root access to raw Logitech HID++ devices across both Unifying receivers and Bluetooth.*
3. Verify device detection:
   ```bash
   python3 -m btsync.app --scan
   ```
4. Run the daemon:
   ```bash
   python3 -m btsync.app --daemon
   ```
   Or enable automatic startup on login via systemd:
   ```bash
   systemctl --user enable --now logiflowbt.service
   ```

---

## Configuration (`config.json`)

Settings can be modified via the GUI (`python -m btsync.app --gui`) or by editing `config.json`:
- **Windows location**: `%APPDATA%\LogiFlowBT\config.json`
- **Linux location**: `~/.config/logiflowbt/config.json`

```json
{
    "host_name": "Windows Laptop",
    "my_channel": 1,
    "target_channel": 2,
    "trigger_edge": "right",
    "entry_edge": "left",
    "hold_delay_ms": 250,
    "cooldown_ms": 2500,
    "devices": [
        "MX Keys",
        "M370",
        "POP",
        "Triathlon",
        "M720",
        "MX Master",
        "Mouse"
    ],
    "bt_p2p_enabled": false,
    "bt_peer_address": "",
    "sync_clipboard": false
}
```

### Key Parameters:
- `my_channel`: Easy-Switch channel (1, 2, or 3) on the current computer.
- `target_channel`: Easy-Switch channel on the partner computer.
- `trigger_edge`: `"right"`, `"left"`, `"top"`, or `"bottom"`.
- `hold_delay_ms`: Dwell time (in milliseconds) before triggering to prevent accidental switches while aiming for window borders or scrollbars (default: `250`).
- `cooldown_ms`: Delay after a switch before a new trigger is accepted to avoid immediate bounce-back.
- `bt_peer_address`: Bluetooth MAC address of partner host (optional, leave empty for Autonomous mode).

---

## CLI Usage

```text
usage: python -m btsync.app [-h] [--scan] [--switch {1,2,3}] [--daemon] [--gui] [--config CONFIG]

LogiFlowBT - Logitech Flow over Bluetooth & Unifying for MX Keys & M370

options:
  -h, --help            show this help message and exit
  --scan                Scan and list connected Logitech devices across Bluetooth & Unifying
  --switch {1,2,3}      Immediately switch devices to Channel 1, 2, or 3
  --daemon              Run in background daemon mode
  --gui                 Launch the GUI settings and status window
  --config CONFIG       Path to custom config.json file
```
