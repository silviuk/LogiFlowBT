"""
Main Coordinator Application for LogiFlowBT.
Integrates Edge Detection, Logitech HID++ Switching, Bluetooth Inter-Host Link, and Cursor Repositioning.
"""

import os
import sys
import time
import signal
import argparse
from typing import Optional

from .config import AppConfig, DEFAULT_CONFIG_PATH
from .hidpp import HIDPPMaster
from .edge_detector import ScreenEdgeDetector
from .cursor_manager import CursorManager
from .clipboard import ClipboardManager
from .bt_link import BluetoothLink


class LogiFlowBTApp:
    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or AppConfig.load()
        self.hidpp = HIDPPMaster()
        self.cursor_mgr = CursorManager()
        self.bt_link: Optional[BluetoothLink] = None
        self.edge_detector: Optional[ScreenEdgeDetector] = None

        self._running = False
        self._setup_subsystems()

    def _setup_subsystems(self) -> None:
        # 1. Edge detector
        self.edge_detector = ScreenEdgeDetector(
            trigger_edge=self.config.trigger_edge,
            hold_delay_ms=self.config.hold_delay_ms,
            cooldown_ms=self.config.cooldown_ms,
            on_trigger_callback=self._handle_edge_triggered
        )

        # 2. Bluetooth P2P Link (optional inter-host sync)
        if self.config.bt_p2p_enabled or self.config.bt_peer_address:
            self.bt_link = BluetoothLink(
                host_name=self.config.host_name,
                peer_mac=self.config.bt_peer_address,
                rfcomm_port=self.config.bt_rfcomm_port,
                on_switch_received=self._handle_incoming_switch,
                on_peer_status_changed=self._handle_peer_status_changed
            )

        # Warm up device cache in background so switches execute with 0ms scan delay
        import threading
        threading.Thread(target=lambda: self.hidpp.scan_devices(self.config.devices, force_rescan=True), daemon=True).start()

    def _handle_edge_triggered(self, edge: str, x: int, y: int, ratio: float) -> None:
        """
        Called when cursor dwells at the configured screen border.
        Executes hardware switch instantly with zero blocking.
        """
        print(f"\n[LogiFlowBT] >>> SCREEN BORDER REACHED at ({x}, {y}) (Ratio: {ratio:.2f}) <<<")
        print(f"[LogiFlowBT] Instantly switching MX Keys & mouse to Channel {self.config.target_channel}...")

        # 1. Fire hardware switch immediately in parallel
        results = self.hidpp.switch_all_to_channel(self.config.target_channel, self.config.devices)
        for dev_name, success in results.items():
            status = "SUCCESS" if success else "FAILED"
            print(f"[LogiFlowBT] Device '{dev_name}' -> Channel {self.config.target_channel}: {status}")

        # 2. Async notify partner host over Bluetooth link (non-blocking)
        if self.bt_link and self.bt_link.is_connected:
            def notify_peer():
                clipboard_content = None
                if self.config.sync_clipboard:
                    clipboard_content = ClipboardManager.get_text()
                self.bt_link.notify_switch_out(edge, ratio, clipboard_content)
            import threading
            threading.Thread(target=notify_peer, daemon=True).start()

    def _handle_incoming_switch(self, partner_exit_edge: str, ratio: float, clipboard_text: Optional[str]) -> None:
        """
        Called when partner host notifies that the mouse is switching into this screen.
        """
        print(f"\n[LogiFlowBT] <<< INCOMING TRANSFER from partner (Exit Edge: '{partner_exit_edge}', Ratio: {ratio:.2f}) <<<")

        # 1. Sync clipboard if text received
        if self.config.sync_clipboard and clipboard_text:
            ok = ClipboardManager.set_text(clipboard_text)
            print(f"[LogiFlowBT] Updated local clipboard from partner: {'OK' if ok else 'FAILED'}")

        # 2. Position cursor at entry edge
        bounds = self.edge_detector._screen_bounds if self.edge_detector else {"left": 0, "top": 0, "right": 1920, "bottom": 1080}
        entry_edge = self.config.entry_edge
        if not entry_edge:
            # Opposite of partner's exit edge
            opposites = {"right": "left", "left": "right", "top": "bottom", "bottom": "top"}
            entry_edge = opposites.get(partner_exit_edge, "left")

        self.cursor_mgr.position_cursor_at_entry(entry_edge, ratio, bounds)

    def _handle_peer_status_changed(self, connected: bool) -> None:
        status = "CONNECTED" if connected else "DISCONNECTED"
        print(f"[LogiFlowBT] Partner host Bluetooth link: {status}")

    def scan_devices(self) -> None:
        print("\n=== Scanning for Logitech Devices (VID 0x046D) ===")
        devs = self.hidpp.scan_devices(self.config.devices)
        if not devs:
            print("No matching Logitech Easy-Switch devices found.")
            print("Make sure MX Keys and M370 are connected via Bluetooth or Bolt/Unifying receiver.")
        else:
            print(f"Found {len(devs)} supported device(s):")
            for i, d in enumerate(devs, 1):
                conn_type = d.transport.value
                feat = f"0x{d.change_host_feature_index:02x}" if d.change_host_feature_index else "Auto-detect"
                print(f" [{i}] {d.name}")
                print(f"     Protocol / Transport: {conn_type} (Device Index: 0x{d.device_index:02x})")
                print(f"     Feature 0x1814 Index: {feat}")
        print("===================================================\n")

    def switch_now(self, target_channel: int) -> None:
        print(f"\n[LogiFlowBT] Manually switching all devices to Channel {target_channel}...")
        results = self.hidpp.switch_all_to_channel(target_channel, self.config.devices)
        for dev_name, success in results.items():
            status = "SUCCESS" if success else "FAILED"
            print(f" - {dev_name}: {status}")

    def run(self) -> None:
        self._running = True

        # Handle termination signals
        def sig_handler(signum, frame):
            print("\n[LogiFlowBT] Termination signal received. Stopping...")
            self.stop()
            sys.exit(0)

        try:
            signal.signal(signal.SIGINT, sig_handler)
            signal.signal(signal.SIGTERM, sig_handler)
        except Exception:
            pass

        print(f"==================================================")
        print(f" LogiFlowBT Daemon Running")
        print(f" Host: {self.config.host_name} (Channel {self.config.my_channel})")
        print(f" Target Host Channel: {self.config.target_channel}")
        print(f" Trigger Edge: '{self.config.trigger_edge.upper()}' (Hold: {self.config.hold_delay_ms}ms)")
        print(f" Target Devices: {', '.join(self.config.devices)}")
        if self.config.bt_peer_address:
            print(f" Inter-Host BT Peer: {self.config.bt_peer_address}")
        else:
            print(f" Inter-Host Mode: Autonomous Hardware Edge Switch")
        print(f"==================================================")

        # Start edge detector
        if self.edge_detector:
            self.edge_detector.start()

        # Start Bluetooth link if configured
        if self.bt_link:
            self.bt_link.start()

        # Keep main thread alive
        try:
            while self._running:
                time.sleep(1.0)
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        self._running = False
        if self.edge_detector:
            self.edge_detector.stop()
        if self.bt_link:
            self.bt_link.stop()
        print("[LogiFlowBT] Shutdown complete.")


def interactive_configure(config: AppConfig, path: Optional[str] = None) -> None:
    """
    Terminal-based setup for headless or non-GUI environments.
    """
    cfg_file = path or DEFAULT_CONFIG_PATH
    print("\n=== LogiFlowBT Terminal Configuration ===")
    print(f"Config File: {cfg_file}\n")

    # Current channel
    prompt = f"This computer's Easy-Switch channel [1, 2, or 3] (current: {config.my_channel}): "
    val = input(prompt).strip()
    if val in ("1", "2", "3"):
        config.my_channel = int(val)

    # Target channel
    prompt = f"Partner computer's Easy-Switch channel [1, 2, or 3] (current: {config.target_channel}): "
    val = input(prompt).strip()
    if val in ("1", "2", "3"):
        config.target_channel = int(val)

    # Trigger edge
    prompt = f"Trigger edge to switch to partner [right/left/top/bottom] (current: {config.trigger_edge}): "
    val = input(prompt).strip().lower()
    if val in ("right", "left", "top", "bottom"):
        config.trigger_edge = val

    # Hold delay
    prompt = f"Hold dwell delay in ms [e.g. 250] (current: {config.hold_delay_ms}): "
    val = input(prompt).strip()
    if val.isdigit() and int(val) >= 50:
        config.hold_delay_ms = int(val)

    # Cooldown
    prompt = f"Cooldown after switch in ms [e.g. 2500] (current: {config.cooldown_ms}): "
    val = input(prompt).strip()
    if val.isdigit() and int(val) >= 500:
        config.cooldown_ms = int(val)

    config.save(cfg_file)
    print(f"\n[OK] Configuration successfully saved to {cfg_file}")
    print("You can now start the background service with:")
    print("  python3 -m btsync.app --daemon\n")


def main():
    parser = argparse.ArgumentParser(description="LogiFlowBT - Logitech Flow over Bluetooth & Unifying")
    parser.add_argument("--scan", action="store_true", help="Scan and list connected Logitech devices")
    parser.add_argument("--switch", type=int, choices=[1, 2, 3], help="Immediately switch devices to Channel 1, 2, or 3")
    parser.add_argument("--daemon", action="store_true", help="Run in background daemon mode")
    parser.add_argument("--gui", action="store_true", help="Launch the GUI settings and status window")
    parser.add_argument("--setup", "--configure", dest="setup", action="store_true", help="Interactive terminal configuration")
    parser.add_argument("--config", type=str, help="Path to custom config.json file")

    args = parser.parse_args()
    config = AppConfig.load(args.config)
    app = LogiFlowBTApp(config)

    if args.scan:
        app.scan_devices()
    elif args.switch is not None:
        app.switch_now(args.switch)
    elif args.setup:
        interactive_configure(config, args.config)
    elif args.gui:
        try:
            from .gui import launch_gui
            launch_gui(app)
        except (ImportError, ModuleNotFoundError) as e:
            print("\n" + "=" * 60)
            print("[LogiFlowBT] GUI Error: Tkinter is not installed in this Python environment.")
            print(f"Details: {e}")
            print("=" * 60)
            print("\nHow to fix this on your system:")
            print("  • If using Homebrew on Linux:")
            print("      brew install python-tk@3.14")
            print("  • If using Ubuntu / Debian:")
            print("      sudo apt install -y python3-tk")
            print("  • If using Fedora:")
            print("      sudo dnf install -y python3-tkinter")
            print("  • If using Arch Linux:")
            print("      sudo pacman -S tk")
            print("\nTIP: You can also configure everything directly in terminal without GUI:")
            print("  python3 -m btsync.app --setup")
            print("=" * 60 + "\n")
            sys.exit(1)
    else:
        # Default to daemon mode
        app.run()


if __name__ == "__main__":
    main()
