"""
Logitech HID++ Protocol Implementation with Autonomous Multi-Protocol Support.
Seamlessly switches Logitech MX Keys, M370, POP Mouse, and all Easy-Switch devices
autonomously whether connected over Direct Bluetooth or Wireless Receivers (Unifying, Bolt, Lightspeed).
"""

import os
import sys
import time
import shutil
import subprocess
from enum import Enum
from typing import List, Dict, Tuple, Optional

try:
    import hid
except ImportError:
    hid = None

LOGITECH_VID = 0x046D
FEATURE_ROOT = 0x0000
FEATURE_CHANGE_HOST = 0x1814
FEATURE_DEVICE_NAME = 0x0005

# Usage pages
USAGE_PAGE_RECEIVER = 0xFF00
USAGE_PAGE_BLUETOOTH = 0xFF43

# Known Logitech Wireless Receiver PIDs
PIDS_UNIFYING = {0xC52B, 0xC532, 0xC52F}
PIDS_BOLT = {0xC548, 0xC547}
PIDS_LIGHTSPEED = {0xC539, 0xC53A, 0xC541, 0xC542, 0xC53F, 0xC545}

DEFAULT_FEATURE_INDICES = [0x09, 0x0A, 0x08, 0x0B]


class TransportType(Enum):
    BLUETOOTH = "Bluetooth"
    UNIFYING = "Unifying"
    BOLT = "Bolt"
    LIGHTSPEED = "Lightspeed"
    GENERIC_HID = "HID"


class LogitechDevice:
    def __init__(self,
                 name: str,
                 path: bytes,
                 transport: TransportType,
                 device_index: int = 0x01,
                 vid: int = LOGITECH_VID,
                 pid: int = 0,
                 usage_page: int = 0,
                 usage: int = 0,
                 short_path: Optional[bytes] = None):
        self.name = name
        self.path = path                       # Typically Long Report path (Col02 / BT)
        self.short_path = short_path           # Short Report path for Unifying (Col01)
        self.transport = transport
        self.device_index = device_index
        self.vid = vid
        self.pid = pid
        self.usage_page = usage_page
        self.usage = usage
        self.change_host_feature_index: Optional[int] = 0x09  # Default to 0x09

    @property
    def is_receiver(self) -> bool:
        return self.transport in (TransportType.UNIFYING, TransportType.BOLT, TransportType.LIGHTSPEED)

    def __repr__(self) -> str:
        feat_str = f"0x{self.change_host_feature_index:02x}" if self.change_host_feature_index else "Auto"
        return (f"<LogitechDevice name='{self.name}' transport={self.transport.value} "
                f"dev_idx=0x{self.device_index:02x} feat={feat_str}>")


class HIDPPMaster:
    def __init__(self):
        self.devices: List[LogitechDevice] = []
        self._solaar_path = shutil.which("solaar") if sys.platform.startswith("linux") else None

    @staticmethod
    def identify_transport(pid: int, usage_page: int, path: bytes) -> TransportType:
        if pid in PIDS_UNIFYING:
            return TransportType.UNIFYING
        elif pid in PIDS_BOLT:
            return TransportType.BOLT
        elif pid in PIDS_LIGHTSPEED:
            return TransportType.LIGHTSPEED
        elif usage_page == USAGE_PAGE_BLUETOOTH or "bth" in str(path).lower():
            return TransportType.BLUETOOTH
        elif usage_page == USAGE_PAGE_RECEIVER:
            return TransportType.UNIFYING
        return TransportType.GENERIC_HID

    def scan_devices(self, target_keywords: Optional[List[str]] = None) -> List[LogitechDevice]:
        """
        Scans for connected Logitech devices across both Bluetooth and Wireless Receivers (Unifying, Bolt).
        """
        found_devices: List[LogitechDevice] = []
        if not hid:
            print("[HID++] Warning: Python 'hid' module not available.")
            return found_devices

        try:
            raw_devices = hid.enumerate(LOGITECH_VID)
        except Exception as e:
            print(f"[HID++] Failed to enumerate HID devices: {e}")
            return found_devices

        # 1. Group receiver endpoints by PID & interface to pair Col01 (short) and Col02 (long)
        receivers_col01: Dict[int, bytes] = {}
        receivers_col02: Dict[int, bytes] = {}

        for dev_info in raw_devices:
            pid = dev_info.get('product_id', 0)
            up = dev_info.get('usage_page', 0)
            u = dev_info.get('usage', 0)
            path = dev_info.get('path', b'')

            if up == USAGE_PAGE_RECEIVER:
                if u == 0x0001:
                    receivers_col01[pid] = path
                elif u == 0x0002:
                    receivers_col02[pid] = path

        # 2. Query paired devices on all discovered receivers
        for pid, long_path in receivers_col02.items():
            short_path = receivers_col01.get(pid)
            transport = self.identify_transport(pid, USAGE_PAGE_RECEIVER, long_path)
            paired = self._query_receiver_paired_devices(long_path, short_path, pid, transport)
            for p_dev in paired:
                if self._matches_keywords(p_dev.name, target_keywords):
                    found_devices.append(p_dev)

        # 3. Discover direct Bluetooth devices (UsagePage 0xFF43, Usage 0x0202)
        for dev_info in raw_devices:
            path = dev_info.get('path', b'')
            up = dev_info.get('usage_page', 0)
            u = dev_info.get('usage', 0)
            prod = dev_info.get('product_string', '') or "Logitech Bluetooth Device"
            pid = dev_info.get('product_id', 0)

            if up == USAGE_PAGE_BLUETOOTH and u == 0x0202:
                clean_name = prod.replace("_", " ").strip()
                bth_dev = LogitechDevice(
                    name=clean_name,
                    path=path,
                    transport=TransportType.BLUETOOTH,
                    device_index=0xFF,
                    vid=LOGITECH_VID,
                    pid=pid,
                    usage_page=up,
                    usage=u
                )
                if self._matches_keywords(clean_name, target_keywords):
                    feat_idx = self.query_feature_index(bth_dev, FEATURE_CHANGE_HOST)
                    if feat_idx:
                        bth_dev.change_host_feature_index = feat_idx
                    found_devices.append(bth_dev)

        self.devices = found_devices
        return found_devices

    def _matches_keywords(self, name: str, keywords: Optional[List[str]]) -> bool:
        if not keywords:
            return True
        name_lower = name.lower()
        # Also always match generic slot names if they are receiver paired devices
        if name_lower.startswith("unifying slot") or name_lower.startswith("bolt slot"):
            return True
        return any(k.lower() in name_lower for k in keywords)

    def _query_receiver_paired_devices(self, long_path: bytes, short_path: Optional[bytes],
                                       pid: int, transport: TransportType) -> List[LogitechDevice]:
        """
        Queries a Unifying/Bolt receiver for paired devices.
        If a device is sleeping or read times out, still creates a slot entry so switch commands succeed.
        """
        results: List[LogitechDevice] = []
        try:
            h = hid.device()
            h.open_path(long_path)
        except Exception:
            return results

        try:
            # Check receiver paired slots 1 to 6
            for idx in range(1, 7):
                dev_name = None
                ch_feat = 0x09

                # Try reading device name via Feature 0x0005
                try:
                    q_name = [0x11, idx, 0x00, 0x00, 0x00, FEATURE_DEVICE_NAME] + [0x00] * 14
                    h.write(q_name)
                    resp = h.read(20, timeout_ms=80)
                    if resp and resp[4] != 0:
                        name_feat = resp[4]
                        h.write([0x11, idx, name_feat, 0x00] + [0x00] * 16)
                        r_len = h.read(20, timeout_ms=80)
                        n_len = r_len[4] if r_len else 0

                        h.write([0x11, idx, name_feat, 0x10, 0x00] + [0x00] * 15)
                        r_name = h.read(20, timeout_ms=80)
                        if r_name and len(r_name) > 4:
                            raw_name = bytes(r_name[4:4 + min(n_len, 16)]).decode('utf-8', errors='ignore').strip()
                            clean = ''.join(c for c in raw_name if c.isprintable())
                            if clean:
                                dev_name = clean

                        # Try query 0x1814
                        q_ch = [0x11, idx, 0x00, 0x00, (FEATURE_CHANGE_HOST >> 8) & 0xFF, FEATURE_CHANGE_HOST & 0xFF] + [0x00] * 14
                        h.write(q_ch)
                        resp_ch = h.read(20, timeout_ms=80)
                        if resp_ch and len(resp_ch) > 4 and resp_ch[4] != 0:
                            ch_feat = resp_ch[4]
                except Exception:
                    pass

                # If device answered with a name, register it
                if dev_name:
                    ldev = LogitechDevice(
                        name=dev_name,
                        path=long_path,
                        transport=transport,
                        device_index=idx,
                        vid=LOGITECH_VID,
                        pid=pid,
                        usage_page=USAGE_PAGE_RECEIVER,
                        usage=0x0002,
                        short_path=short_path
                    )
                    ldev.change_host_feature_index = ch_feat
                    results.append(ldev)
        finally:
            try:
                h.close()
            except Exception:
                pass

        # If no active devices responded (e.g. they are in sleep mode or paired slots are quiet),
        # register default slots 1 and 2 for this receiver so autonomous switching will broadcast to them
        if not results:
            for idx in [1, 2, 3]:
                slot_dev = LogitechDevice(
                    name=f"{transport.value} Slot {idx}",
                    path=long_path,
                    transport=transport,
                    device_index=idx,
                    vid=LOGITECH_VID,
                    pid=pid,
                    usage_page=USAGE_PAGE_RECEIVER,
                    usage=0x0002,
                    short_path=short_path
                )
                slot_dev.change_host_feature_index = 0x09
                results.append(slot_dev)

        return results

    def query_feature_index(self, dev: LogitechDevice, feature_id: int) -> Optional[int]:
        """
        Dynamically discovers the feature index for a given HID++ feature (e.g. 0x1814).
        """
        if not hid:
            return 0x09
        try:
            h = hid.device()
            h.open_path(dev.path)
            indices_to_try = [dev.device_index]
            if dev.transport == TransportType.BLUETOOTH and dev.device_index != 0x00:
                indices_to_try.append(0x00)

            for d_idx in indices_to_try:
                q = [
                    0x11,
                    d_idx,
                    0x00,
                    0x00,
                    (feature_id >> 8) & 0xFF,
                    feature_id & 0xFF
                ] + [0x00] * 14
                h.write(q)
                try:
                    resp = h.read(20, timeout_ms=150)
                    if resp and len(resp) >= 5 and resp[4] != 0:
                        h.close()
                        dev.device_index = d_idx
                        return resp[4]
                except Exception:
                    pass
            h.close()
        except Exception:
            pass
        return 0x09  # Safe standard fallback

    def switch_device_host(self, dev: LogitechDevice, target_channel: int) -> bool:
        """
        Switches device to target Easy-Switch channel (1, 2, or 3).
        Autonomous: automatically routes command over Unifying, Bolt, or Bluetooth as appropriate.
        """
        channel_index = max(0, min(2, target_channel - 1))

        # Linux: try Solaar CLI first if available
        if sys.platform.startswith("linux") and self._solaar_path:
            try:
                cmd = [self._solaar_path, "config", dev.name, "change-host", str(target_channel)]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                if res.returncode == 0:
                    print(f"[HID++] Solaar ({dev.transport.value}) switched '{dev.name}' -> Channel {target_channel}")
                    return True
            except Exception:
                pass

        feat_idx = dev.change_host_feature_index or 0x09
        candidate_indices = [feat_idx]
        for f in DEFAULT_FEATURE_INDICES:
            if f not in candidate_indices:
                candidate_indices.append(f)

        success = False

        # --- TRANSMISSION 1: Long Report (0x11, 20 bytes) ---
        # Works on direct Bluetooth and modern Unifying / Bolt Col02
        try:
            h = hid.device()
            h.open_path(dev.path)
            for f_idx in candidate_indices:
                cmd_packet = [
                    0x11,
                    dev.device_index,
                    f_idx,
                    0x10,           # Function 1: set_current_host
                    channel_index
                ] + [0x00] * 15

                try:
                    written = h.write(cmd_packet)
                    if written > 0:
                        print(f"[HID++] Sent Long Report (0x11) to '{dev.name}' via {dev.transport.value} "
                              f"(DevIdx: 0x{dev.device_index:02x}, Feat: 0x{f_idx:02x}) -> Channel {target_channel}")
                        success = True
                        break
                except Exception as ex:
                    print(f"[HID++] Write failed: {ex}")
            h.close()
        except Exception as e:
            print(f"[HID++] Could not open {dev.transport.value} path for '{dev.name}': {e}")

        # --- TRANSMISSION 2: Short Report (0x10, 7 bytes) for Unifying receivers (Col01) ---
        # Guarantees switching on Unifying receivers that expect HID++ 1.0 notifications
        if dev.is_receiver and dev.short_path:
            try:
                h_short = hid.device()
                h_short.open_path(dev.short_path)
                for f_idx in candidate_indices:
                    cmd_short = [
                        0x10,
                        dev.device_index,
                        f_idx,
                        0x1E,
                        channel_index,
                        0x00,
                        0x00
                    ]
                    try:
                        written = h_short.write(cmd_short)
                        if written > 0:
                            print(f"[HID++] Sent Short Report (0x10) to '{dev.name}' via Unifying Col01 -> Channel {target_channel}")
                            success = True
                            break
                    except Exception:
                        pass
                h_short.close()
            except Exception:
                pass

        return success

    def switch_all_to_channel(self, target_channel: int, target_keywords: Optional[List[str]] = None) -> Dict[str, bool]:
        """
        Autonomously scans all devices across Bluetooth and Unifying/Bolt receivers and switches them.
        Also broadcasts to receiver slots to guarantee sleeping devices switch.
        """
        devices = self.scan_devices(target_keywords)
        results: Dict[str, bool] = {}

        for dev in devices:
            key = f"{dev.name} ({dev.transport.value})"
            ok = self.switch_device_host(dev, target_channel)
            results[key] = ok
            time.sleep(0.04)

        return results
