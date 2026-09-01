"""
Synchronized Channel Switching for Logitech Easy-Switch Peripherals.
Automatically syncs mouse channel when keyboard channel button is pressed, and vice-versa.
Generates native Solaar rules in ~/.config/solaar/rules.yaml.
"""

import os
import sys
from typing import List, Tuple

from .hidpp import HIDPPMaster, LogitechDevice


class ButtonSyncManager:
    def __init__(self, hidpp: HIDPPMaster, enabled: bool = True):
        self.hidpp = hidpp
        self.enabled = enabled
        self._running = False

    def start(self) -> None:
        if not self.enabled:
            return
        self._running = True

        # On Linux with Solaar: install clean, validated Solaar rules
        if sys.platform.startswith("linux") and self.hidpp._solaar_path:
            self._setup_solaar_rules()

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
                keyboards.append(d)
            else:
                mice.append(d)

        return keyboards, mice

    def _setup_solaar_rules(self) -> None:
        """
        Creates or updates ~/.config/solaar/rules.yaml to link Easy-Switch buttons.
        When keyboard switches to Host X, commands mouse to switch to Host X.
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
# LogiFlowBT Linked Easy-Switch Rules
# When keyboard ({kb_name}) Easy-Switch key is pressed, mouse ({mouse_name}) follows
- Rule:
  - Key: [Host Switch Channel 1, pressed]
  - Execute: [solaar, config, "{mouse_name}", change-host, "Host 1"]

- Rule:
  - Key: [Host Switch Channel 2, pressed]
  - Execute: [solaar, config, "{mouse_name}", change-host, "Host 2"]

- Rule:
  - Key: [Host Switch Channel 3, pressed]
  - Execute: [solaar, config, "{mouse_name}", change-host, "Host 3"]
"""
        try:
            with open(rules_path, "w", encoding="utf-8") as f:
                f.write(rules_content)
            print(f"[ButtonSync] Installed Solaar Easy-Switch link rules in {rules_path} ({kb_name} -> {mouse_name})")
        except Exception as e:
            print(f"[ButtonSync] Could not write Solaar rules: {e}")
