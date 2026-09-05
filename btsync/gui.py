"""
Modern Graphical User Interface for LogiFlowBT built with CustomTkinter.
Provides a sleek, modern dark/light desktop experience on Windows and Linux.
Optimized for Linux X11/Wayland with pixel-perfect font and geometry rendering.
"""

import sys
import threading
from typing import Optional, List

try:
    import customtkinter as ctk
    from tkinter import messagebox
except ImportError:
    import tkinter as ctk
    from tkinter import messagebox

from .config import AppConfig
from .hidpp import HIDPPMaster, LogitechDevice

IS_LINUX = sys.platform.startswith("linux")
# On Linux X11, canvas corner masks can cause jagged notch artifacts; use crisp flat geometry
BTN_RADIUS = 0 if IS_LINUX else 6
CARD_RADIUS = 0 if IS_LINUX else 8


def get_ui_font(size: int, weight: str = "normal") -> ctk.CTkFont:
    """
    Returns high-quality anti-aliased font suitable for current OS.
    Avoids hardcoding 'Segoe UI' on Linux which causes fallback to pixelated bitmap fonts.
    """
    if IS_LINUX:
        return ctk.CTkFont(size=size, weight=weight)
    return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)


class LogiFlowBTGUI:
    def __init__(self, root: ctk.CTk, app_instance=None):
        self.root = root
        self.app = app_instance
        self.config = self.app.config if self.app else AppConfig.load()
        self.hidpp = HIDPPMaster()

        # CustomTkinter styling
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        self.root.title("LogiFlowBT - Logitech Flow over Bluetooth & Unifying")
        self.root.geometry("700x780")
        self.root.minsize(620, 700)

        self._build_ui()
        self._load_config_values()
        self._refresh_devices_async()

    def _build_ui(self) -> None:
        # Main container with padding
        self.main_container = ctk.CTkFrame(self.root, corner_radius=CARD_RADIUS, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=20, pady=20)

        # Header Frame
        header = ctk.CTkFrame(self.main_container, corner_radius=CARD_RADIUS)
        header.pack(fill="x", pady=(0, 15), ipady=8)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", padx=15, pady=5)

        title_lbl = ctk.CTkLabel(
            title_box,
            text="LogiFlowBT",
            font=get_ui_font(22, "bold")
        )
        title_lbl.pack(anchor="w")

        subtitle_lbl = ctk.CTkLabel(
            title_box,
            text="Logitech Flow over Bluetooth & Unifying (MX Keys & M370 / MX Master)",
            font=get_ui_font(12),
            text_color="#9e9e9e"
        )
        subtitle_lbl.pack(anchor="w")

        # Service Status Pill & Toggle Button
        status_box = ctk.CTkFrame(header, fg_color="transparent")
        status_box.pack(side="right", padx=15, pady=5)

        self.status_badge = ctk.CTkLabel(
            status_box,
            text="STOPPED",
            font=get_ui_font(11, "bold"),
            fg_color="#3e2723",
            text_color="#ef5350",
            corner_radius=BTN_RADIUS,
            width=95,
            height=30
        )
        self.status_badge.pack(side="left", padx=(0, 10))

        self.toggle_btn = ctk.CTkButton(
            status_box,
            text="Start Service",
            font=get_ui_font(12, "bold"),
            corner_radius=BTN_RADIUS,
            width=130,
            height=32,
            command=self._toggle_daemon
        )
        self.toggle_btn.pack(side="right")

        # Tabview for modular settings
        self.tabs = ctk.CTkTabview(self.main_container, corner_radius=CARD_RADIUS)
        self.tabs.pack(fill="both", expand=True, pady=(0, 15))

        self.tab_flow = self.tabs.add("  Screen & Switching  ")
        self.tab_devices = self.tabs.add("  Connected Devices  ")
        self.tab_bt = self.tabs.add("  Bluetooth Inter-Host Link  ")

        self._build_flow_tab(self.tab_flow)
        self._build_devices_tab(self.tab_devices)
        self._build_bt_tab(self.tab_bt)

        # Bottom Action Bar
        bottom_bar = ctk.CTkFrame(self.main_container, fg_color="transparent")
        bottom_bar.pack(fill="x")

        self.save_btn = ctk.CTkButton(
            bottom_bar,
            text="Save Configuration",
            font=get_ui_font(13, "bold"),
            fg_color="#2e7d32",
            hover_color="#1b5e20",
            corner_radius=BTN_RADIUS,
            command=self._save_config,
            height=38,
            width=160
        )
        self.save_btn.pack(side="right", padx=5)

        self.test_btn = ctk.CTkButton(
            bottom_bar,
            text="Test Switch Channel Now",
            font=get_ui_font(13),
            corner_radius=BTN_RADIUS,
            command=self._test_switch,
            height=38,
            width=190
        )
        self.test_btn.pack(side="right", padx=5)

    def _build_flow_tab(self, parent) -> None:
        # Easy-Switch Channel Card
        ch_card = ctk.CTkFrame(parent, corner_radius=CARD_RADIUS)
        ch_card.pack(fill="x", padx=5, pady=8, ipady=5)

        ctk.CTkLabel(
            ch_card,
            text="Easy-Switch Channel Mapping",
            font=get_ui_font(14, "bold")
        ).pack(anchor="w", padx=15, pady=(10, 8))

        row1 = ctk.CTkFrame(ch_card, fg_color="transparent")
        row1.pack(fill="x", padx=15, pady=6)
        ctk.CTkLabel(row1, text="This Computer (Current Channel):", font=get_ui_font(13)).pack(side="left")
        self.my_ch_var = ctk.StringVar(value="Channel 1")
        self.my_ch_menu = ctk.CTkOptionMenu(
            row1,
            variable=self.my_ch_var,
            values=["Channel 1", "Channel 2", "Channel 3"],
            corner_radius=BTN_RADIUS,
            width=140
        )
        self.my_ch_menu.pack(side="right")

        # Hardware Easy-Switch Button Sync
        self.sync_btn_switch = ctk.CTkSwitch(
            ch_card,
            text="Link Channel Buttons (Keyboard button switches mouse & vice-versa)",
            font=get_ui_font(12),
            corner_radius=BTN_RADIUS
        )
        self.sync_btn_switch.pack(anchor="w", padx=15, pady=(10, 2))

        ctk.CTkLabel(
            ch_card,
            text="Note: Logitech keyboard buttons switch radio state in hardware without host events.",
            font=get_ui_font(10),
            text_color="#9e9e9e"
        ).pack(anchor="w", padx=15, pady=(0, 8))

        # Screen Border Channel Routing Card
        edge_card = ctk.CTkFrame(parent, corner_radius=CARD_RADIUS)
        edge_card.pack(fill="x", padx=5, pady=8, ipady=5)

        ctk.CTkLabel(
            edge_card,
            text="Screen Border Channel Routing",
            font=get_ui_font(14, "bold")
        ).pack(anchor="w", padx=15, pady=(10, 2))

        ctk.CTkLabel(
            edge_card,
            text="Select target Easy-Switch channel when cursor reaches each screen border:",
            font=get_ui_font(11),
            text_color="#b0bec5"
        ).pack(anchor="w", padx=15, pady=(0, 8))

        channel_options = ["Disabled", "Channel 1", "Channel 2", "Channel 3"]
        self.edge_vars = {}
        self.edge_menus = {}

        border_rows = [
            ("Left Border", "left"),
            ("Right Border", "right"),
            ("Top Border", "top"),
            ("Bottom Border", "bottom")
        ]
        for edge_title, edge_key in border_rows:
            erow = ctk.CTkFrame(edge_card, fg_color="transparent")
            erow.pack(fill="x", padx=15, pady=4)
            ctk.CTkLabel(erow, text=f"{edge_title} (Switch to):", font=get_ui_font(13)).pack(side="left")
            evar = ctk.StringVar(value="Disabled")
            menu = ctk.CTkOptionMenu(
                erow,
                variable=evar,
                values=channel_options,
                corner_radius=BTN_RADIUS,
                width=140
            )
            menu.pack(side="right")
            self.edge_vars[edge_key] = evar
            self.edge_menus[edge_key] = menu

        delay_header = ctk.CTkFrame(edge_card, fg_color="transparent")
        delay_header.pack(fill="x", padx=15, pady=(8, 0))
        ctk.CTkLabel(delay_header, text="Hold Delay (Anti-Accidental Dwell):", font=get_ui_font(13)).pack(side="left")
        self.hold_lbl = ctk.CTkLabel(delay_header, text="250 ms", font=get_ui_font(12, "bold"), text_color="#64b5f6")
        self.hold_lbl.pack(side="right")

        self.hold_slider = ctk.CTkSlider(
            edge_card,
            from_=50,
            to=1000,
            number_of_steps=19,
            command=self._on_hold_slider_change
        )
        self.hold_slider.pack(fill="x", padx=15, pady=(6, 8))

        cd_row = ctk.CTkFrame(edge_card, fg_color="transparent")
        cd_row.pack(fill="x", padx=15, pady=6)
        ctk.CTkLabel(cd_row, text="Cooldown after switch (ms):", font=get_ui_font(13)).pack(side="left")
        self.cooldown_entry = ctk.CTkEntry(cd_row, width=140, corner_radius=BTN_RADIUS, placeholder_text="2500")
        self.cooldown_entry.pack(side="right")

    def _build_devices_tab(self, parent) -> None:
        top_bar = ctk.CTkFrame(parent, fg_color="transparent")
        top_bar.pack(fill="x", padx=5, pady=(5, 10))

        ctk.CTkLabel(
            top_bar,
            text="Detected Logitech Hardware",
            font=get_ui_font(14, "bold")
        ).pack(side="left", anchor="w")

        self.rescan_btn = ctk.CTkButton(
            top_bar,
            text="Rescan Devices",
            font=get_ui_font(12),
            corner_radius=BTN_RADIUS,
            width=130,
            command=self._refresh_devices_async
        )
        self.rescan_btn.pack(side="right")

        # Scrollable container for detected devices
        self.device_list_frame = ctk.CTkScrollableFrame(parent, corner_radius=CARD_RADIUS, height=280)
        self.device_list_frame.pack(fill="both", expand=True, padx=5, pady=5)

        note_box = ctk.CTkFrame(parent, corner_radius=CARD_RADIUS, fg_color="#1e1e1e")
        note_box.pack(fill="x", padx=5, pady=8, ipady=6)
        ctk.CTkLabel(
            note_box,
            text="Supports Logitech MX Keys, M370, POP Mouse, MX Master 3/3S, M720 Triathlon, and all Easy-Switch devices across Bluetooth, Unifying, and Bolt receivers.",
            font=get_ui_font(11),
            text_color="#b0bec5",
            wraplength=580
        ).pack(padx=12)

    def _build_bt_tab(self, parent) -> None:
        bt_card = ctk.CTkFrame(parent, corner_radius=CARD_RADIUS)
        bt_card.pack(fill="x", padx=5, pady=8, ipady=5)

        ctk.CTkLabel(
            bt_card,
            text="Peer-to-Peer Inter-Host Sync (Zero Local Network)",
            font=get_ui_font(14, "bold")
        ).pack(anchor="w", padx=15, pady=(10, 8))

        self.p2p_switch = ctk.CTkSwitch(
            bt_card,
            text="Enable Bluetooth RFCOMM Peer Link (Cursor Alignment & Clipboard)",
            font=get_ui_font(13),
            corner_radius=BTN_RADIUS,
            command=self._on_p2p_toggle
        )
        self.p2p_switch.pack(anchor="w", padx=15, pady=8)

        mac_row = ctk.CTkFrame(bt_card, fg_color="transparent")
        mac_row.pack(fill="x", padx=15, pady=6)
        ctk.CTkLabel(mac_row, text="Partner Bluetooth MAC Address:", font=get_ui_font(13)).pack(side="left")
        self.peer_mac_entry = ctk.CTkEntry(mac_row, width=180, corner_radius=BTN_RADIUS, placeholder_text="00:11:22:33:44:55")
        self.peer_mac_entry.pack(side="right")

        port_row = ctk.CTkFrame(bt_card, fg_color="transparent")
        port_row.pack(fill="x", padx=15, pady=6)
        ctk.CTkLabel(port_row, text="RFCOMM Channel / Port:", font=get_ui_font(13)).pack(side="left")
        self.port_entry = ctk.CTkEntry(port_row, width=90, corner_radius=BTN_RADIUS, placeholder_text="4")
        self.port_entry.pack(side="right")

        self.clip_switch = ctk.CTkSwitch(
            bt_card,
            text="Synchronize text clipboard over Bluetooth upon edge crossing",
            font=get_ui_font(13),
            corner_radius=BTN_RADIUS
        )
        self.clip_switch.pack(anchor="w", padx=15, pady=8)

        desc_box = ctk.CTkFrame(parent, corner_radius=CARD_RADIUS, fg_color="#1e1e1e")
        desc_box.pack(fill="x", padx=5, pady=8, ipady=6)
        ctk.CTkLabel(
            desc_box,
            text="Autonomous Mode vs Bluetooth Sync:\n"
                 "- Autonomous Mode (Partner MAC empty): Switches hardware whenever cursor reaches the border with ZERO inter-PC connection.\n"
                 "- Bluetooth Sync Mode: Directly pairs the two computers over Bluetooth RFCOMM to align cursor entry height and synchronize clipboard text without Wi-Fi.",
            font=get_ui_font(11),
            text_color="#b0bec5",
            justify="left",
            wraplength=580
        ).pack(padx=12)

    def _on_hold_slider_change(self, value: float) -> None:
        ms = int(value)
        self.hold_lbl.configure(text=f"{ms} ms")

    def _on_p2p_toggle(self) -> None:
        enabled = bool(self.p2p_switch.get())
        state = "normal" if enabled else "disabled"
        self.peer_mac_entry.configure(state=state)
        self.port_entry.configure(state=state)

    def _load_config_values(self) -> None:
        self.my_ch_var.set(f"Channel {self.config.my_channel}")

        for edge_key, evar in self.edge_vars.items():
            ch = self.config.get_target_channel_for_edge(edge_key)
            if ch is not None:
                evar.set(f"Channel {ch}")
            else:
                evar.set("Disabled")

        hold_ms = self.config.hold_delay_ms
        self.hold_slider.set(hold_ms)
        self.hold_lbl.configure(text=f"{hold_ms} ms")

        self.cooldown_entry.delete(0, "end")
        self.cooldown_entry.insert(0, str(self.config.cooldown_ms))

        if self.config.bt_p2p_enabled:
            self.p2p_switch.select()
        else:
            self.p2p_switch.deselect()

        self.peer_mac_entry.delete(0, "end")
        if self.config.bt_peer_address:
            self.peer_mac_entry.insert(0, self.config.bt_peer_address)

        self.port_entry.delete(0, "end")
        self.port_entry.insert(0, str(self.config.bt_rfcomm_port))

        if self.config.sync_clipboard:
            self.clip_switch.select()
        else:
            self.clip_switch.deselect()

        if self.config.sync_easy_switch_buttons:
            self.sync_btn_switch.select()
        else:
            self.sync_btn_switch.deselect()

        self._on_p2p_toggle()

    def _save_config(self) -> None:
        try:
            self.config.my_channel = int(self.my_ch_var.get().split()[-1])
            new_edges = {}
            for edge_key, evar in self.edge_vars.items():
                val = evar.get()
                if val == "Disabled":
                    new_edges[edge_key] = None
                else:
                    new_edges[edge_key] = int(val.split()[-1])
            self.config.edge_channels = new_edges

            active = self.config.get_active_edges()
            if active:
                self.config.trigger_edge = active[0]
                self.config.target_channel = self.config.get_target_channel_for_edge(active[0]) or 2

            self.config.hold_delay_ms = int(self.hold_slider.get())
            self.config.cooldown_ms = int(self.cooldown_entry.get() or "2500")
            self.config.bt_p2p_enabled = bool(self.p2p_switch.get())
            self.config.bt_peer_address = self.peer_mac_entry.get().strip()
            self.config.bt_rfcomm_port = int(self.port_entry.get() or "4")
            self.config.sync_clipboard = bool(self.clip_switch.get())
            self.config.sync_easy_switch_buttons = bool(self.sync_btn_switch.get())
            self.config.save()

            if self.app and self.app.edge_detector:
                self.app.edge_detector.active_edges = self.config.get_active_edges()
                self.app.edge_detector.hold_delay_ms = self.config.hold_delay_ms
                self.app.edge_detector.cooldown_ms = self.config.cooldown_ms

            messagebox.showinfo("LogiFlowBT", "Settings successfully saved!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save settings: {e}")

    def _refresh_devices_async(self) -> None:
        self.rescan_btn.configure(state="disabled", text="Scanning...")

        def worker():
            devs = self.hidpp.scan_devices(self.config.devices, force_rescan=True)
            self.root.after(0, lambda: self._populate_devices(devs))

        threading.Thread(target=worker, daemon=True).start()

    def _populate_devices(self, devs: List[LogitechDevice]) -> None:
        for child in self.device_list_frame.winfo_children():
            child.destroy()

        if not devs:
            empty_lbl = ctk.CTkLabel(
                self.device_list_frame,
                text="No supported Logitech devices detected.\nMake sure MX Keys and mouse are connected.",
                font=get_ui_font(12),
                text_color="#9e9e9e"
            )
            empty_lbl.pack(pady=30)
        else:
            for d in devs:
                card = ctk.CTkFrame(self.device_list_frame, corner_radius=CARD_RADIUS, fg_color="#2b2b2b")
                card.pack(fill="x", padx=5, pady=4, ipady=4)

                left = ctk.CTkFrame(card, fg_color="transparent")
                left.pack(side="left", padx=10)

                ctk.CTkLabel(
                    left,
                    text=d.name,
                    font=get_ui_font(13, "bold")
                ).pack(anchor="w")

                f_str = f"0x{d.change_host_feature_index:02x}" if d.change_host_feature_index else "Auto"
                ctk.CTkLabel(
                    left,
                    text=f"Slot/Index: 0x{d.device_index:02x} | CHANGE_HOST Feature: {f_str}",
                    font=get_ui_font(11),
                    text_color="#b0bec5"
                ).pack(anchor="w")

                # Protocol Badge
                badge_color = "#1565c0" if d.transport.value == "Bluetooth" else "#e65100"
                badge = ctk.CTkLabel(
                    card,
                    text=d.transport.value.upper(),
                    font=get_ui_font(10, "bold"),
                    fg_color=badge_color,
                    corner_radius=BTN_RADIUS,
                    width=85,
                    height=24
                )
                badge.pack(side="right", padx=12)

        self.rescan_btn.configure(state="normal", text="Rescan Devices")

    def _test_switch(self) -> None:
        active_edges = self.config.get_active_edges()
        target = 2
        if active_edges:
            target = self.config.get_target_channel_for_edge(active_edges[0]) or 2
        elif self.config.target_channel:
            target = self.config.target_channel

        if messagebox.askyesno("Confirm Switch", f"Send switch command for all devices to Channel {target}?"):
            res = self.hidpp.switch_all_to_channel(target, self.config.devices)
            status_text = "\n".join([f"• {k}: {'OK' if v else 'FAILED'}" for k, v in res.items()])
            messagebox.showinfo("Switch Results", status_text or "No devices found.")

    def _toggle_daemon(self) -> None:
        if self.app and self.app._running:
            self.app.stop()
            self.status_badge.configure(
                text="STOPPED",
                fg_color="#3e2723",
                text_color="#ef5350"
            )
            self.toggle_btn.configure(text="Start Service", fg_color="#1976d2")
        elif self.app:
            self._save_config()
            self.app._setup_subsystems()
            threading.Thread(target=self.app.run, daemon=True).start()
            self.status_badge.configure(
                text="ACTIVE",
                fg_color="#1b5e20",
                text_color="#81c784"
            )
            self.toggle_btn.configure(text="Stop Service", fg_color="#d32f2f")


def launch_gui(app_instance=None):
    root = ctk.CTk()
    gui = LogiFlowBTGUI(root, app_instance)
    root.mainloop()
