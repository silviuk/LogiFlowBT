"""
Synchronized Channel Switching for Logitech Easy-Switch Peripherals.
Automatically syncs mouse channel when keyboard channel button is pressed, and vice-versa.
Integrates Solaar rules on Linux and direct HID++ event monitoring.
"""

import os
import re
import sys
import glob
import time
import select
import threading
import subprocess
from typing import List, Optional, Tuple

from .hidpp import HIDPPMaster, LogitechDevice


class ButtonSyncManager:
    def __init__(self, hidpp: HIDPPMaster, enabled: bool = True):
        self.hidpp = hidpp
        self.enabled = enabled
        self._running = False
        self._threads: List[threading.Thread] = []
        self._last_switch_time: float = 0.0
        self._cooldown: float = 0.8  # Prevent echo loops between keyboard and mouse

    def start(self) -> None:
        if not self.enabled:
            return
        self._running = True

        # 1. On Linux with Solaar: automatically install rules in ~/.config/solaar/rules.yaml
        if sys.platform.startswith("linux") and self.hidpp._solaar_path:
            self._setup_solaar_rules()

        # 2. Start direct HID++ event listener threads on all devices
        self._start_event_listeners()

    def stop(self) -> None:
        self._running = False

    def _get_keyboards_and_mice(self) -> Tuple[List[LogitechDevice], List[LogitechDevice]]:
        devices = self.hidpp.scan_devices()
        keyboards: List[LogitechDevice] = []
        mice: List[LogitechDevice] = []

        for d in devices:
            name_lower = d.name.lower()
            if any(k in name_lower for k in ["key", "k380", "k780", "craft"]):
                keyboards.append(d)
            elif any(m in name_lower for m in ["mouse", "master", "anywhere", "pop", "m370", "m720", "triathlon"]):
                mice.append(d)
            elif d.device_index == 1:
                # Default first device is often keyboard/mouse
                keyboards.append(d)
            else:
                mice.append(d)

        return keyboards, mice

    def _setup_solaar_rules(self) -> None:
        """
        Creates or updates ~/.config/solaar/rules.yaml to link Easy-Switch buttons.
        """
        keyboards, mice = self._get_keyboards_and_mice()
        if not keyboards or not mice:
            return

        kb_name = keyboards[0].solaar_name or keyboards[0].name
        mouse_name = mice[0].solaar_name or mice[0].name

        rules_dir = os.path.expanduser("~/.config/solaar")
        os.makedirs(rules_dir, exist_ok=True)
        rules_path = os.path.join(rules_dir, "rules.yaml")

        rules_content = f"""%YAML 1.3
---
# LogiFlowBT Auto-Generated Easy-Switch Sync Rules
# Automatically switches mouse ({mouse_name}) when keyboard ({kb_name}) channel button is pressed
- Rule:
  - Key: [Host Switch Channel 1, pressed]
  - Execute: [solaar, config, "{mouse_name}", change-host, '1']
  - Execute: [solaar, config, "{kb_name}", change-host, '1']

- Rule:
  - Key: [Host Switch Channel 2, pressed]
  - Execute: [solaar, config, "{mouse_name}", change-host, '2']
  - Execute: [solaar, config, "{kb_name}", change-host, '2']

- Rule:
  - Key: [Host Switch Channel 3, pressed]
  - Execute: [solaar, config, "{mouse_name}", change-host, '3']
  - Execute: [solaar, config, "{kb_name}", change-host, '3']
"""
        try:
            with open(rules_path, "w", encoding="utf-8") as f:
                f.write(rules_content)
            print(f"[ButtonSync] Configured Solaar linked rules in {rules_path} ({kb_name} <-> {mouse_name})")
        except Exception as e:
            print(f"[ButtonSync] Could not write Solaar rules: {e}")

    def _start_event_listeners(self) -> None:
        """
        Spawns background listener threads reading raw HID++ notifications from peripherals.
        """
        keyboards, mice = self._get_keyboards_and_mice()

        for kb in keyboards:
            t = threading.Thread(target=self._listen_device_events, args=(kb, mice, "Keyboard"), daemon=True)
            t.start()
            self._threads.append(t)

        for mouse in mice:
            t = threading.Thread(target=self._listen_device_events, args=(mouse, keyboards, "Mouse"), daemon=True)
            t.start()
            self._threads.append(t)

    def _listen_device_events(self, source_dev: LogitechDevice, target_devs: List[LogitechDevice], dev_type: str) -> None:
        """
        Listens on a device's raw hidraw endpoints for HID++ Feature 0x1814 notifications.
        """
        if not sys.platform.startswith("linux"):
            return

        # Find candidate /dev/hidraw nodes
        candidate_nodes = [p.decode("utf-8") for p in source_dev.all_paths if p and p.startswith(b"/dev/hidraw")]
        if not candidate_nodes:
            return

        fds = []
        for node in candidate_nodes:
            try:
                fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
                fds.append((fd, node))
            except Exception:
                pass

        if not fds:
            return

        print(f"[ButtonSync] Monitoring {dev_type} '{source_dev.name}' on {[n for _, n in fds]} for channel button presses...")

        try:
            while self._running:
                rlist, _, _ = select.select([fd for fd, _ in fds], [], [], 0.5)
                for fd in rlist:
                    try:
                        data = os.read(fd, 64)
                        if not data or len(data) < 5:
                            continue

                        # HID++ Long Report (0x11)
                        if data[0] == 0x11:
                            feat_idx = data[2]
                            func_or_event = data[3]

                            # Check for Feature 0x1814 (CHANGE_HOST) notification
                            # Feature index is typically 0x09 or source_dev.change_host_feature_index
                            if feat_idx in (source_dev.change_host_feature_index, 0x09, 0x08, 0x0A):
                                # Function 0x10 or notification event reports the channel in byte 4
                                raw_ch = data[4]
                                if raw_ch in (0, 1, 2):
                                    target_ch = raw_ch + 1
                                    now = time.time()
                                    if now - self._last_switch_time > self._cooldown:
                                        self._last_switch_time = now
                                        print(f"\n[ButtonSync] >>> {dev_type} '{source_dev.name}' switched to Channel {target_ch}! <<<")
                                        print(f"[ButtonSync] Automatically switching partner peripherals to Channel {target_ch}...")

                                        for target in target_devs:
                                            threading.Thread(
                                                target=lambda d=target, ch=target_ch: self.hidpp.switch_device_host(d, ch),
                                                daemon=True
                                            ).start()
                    except Exception:
                        pass
        finally:
            for fd, _ in fds:
                try:
                    os.close(fd)
                except Exception:
                    pass
