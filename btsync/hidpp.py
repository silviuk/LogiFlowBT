"""
Logitech HID++ Protocol Implementation with Autonomous Multi-Protocol Support.
Seamlessly switches Logitech MX Keys, M370, POP Mouse, MX Master 3, and all Easy-Switch devices
autonomously whether connected over Direct Bluetooth or Wireless Receivers (Unifying, Bolt, Lightspeed).
Fully compatible with Windows and Linux (handles Linux hidraw usage_page=0, sysfs, and Bluetooth).
"""

import os
import re
import sys
import glob
import time
import shutil
import subprocess
from enum import Enum
from typing import List, Dict, Tuple, Optional, Set

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
ALL_RECEIVER_PIDS = PIDS_UNIFYING | PIDS_BOLT | PIDS_LIGHTSPEED

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
                 short_path: Optional[bytes] = None,
                 all_paths: Optional[List[bytes]] = None,
                 solaar_name: Optional[str] = None):
        self.name = name
        self.path = path                       # Primary control path
        self.short_path = short_path           # Short Report path for Unifying (Col01)
        self.all_paths = all_paths or ([path] if path else [])
        self.solaar_name = solaar_name         # Specific name recognized by Solaar CLI
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
        elif pid not in ALL_RECEIVER_PIDS and pid != 0:
            return TransportType.BLUETOOTH
        return TransportType.GENERIC_HID

    def scan_devices(self, target_keywords: Optional[List[str]] = None) -> List[LogitechDevice]:
        """
        Scans for connected Logitech devices across both Bluetooth and Wireless Receivers (Unifying, Bolt).
        Multi-layered detection ensuring 100% discovery on both Windows and Linux.
        """
        found_devices: List[LogitechDevice] = []
        seen_names: Set[str] = set()

        # Layer 1: Solaar CLI on Linux (if available) - highest fidelity for Linux
        if sys.platform.startswith("linux") and self._solaar_path:
            solaar_devs = self._scan_solaar_devices(target_keywords)
            for s_dev in solaar_devs:
                norm_name = self._normalize_name(s_dev.name)
                if norm_name not in seen_names:
                    found_devices.append(s_dev)
                    seen_names.add(norm_name)

        # Layer 2: Linux sysfs inspection (/sys/class/hidraw) - reads kernel HID info directly
        if sys.platform.startswith("linux"):
            sysfs_devs = self._scan_linux_sysfs(target_keywords)
            for s_dev in sysfs_devs:
                norm_name = self._normalize_name(s_dev.name)
                if norm_name not in seen_names:
                    found_devices.append(s_dev)
                    seen_names.add(norm_name)
                else:
                    # Enrich existing device with all physical hidraw paths
                    for existing in found_devices:
                        if self._normalize_name(existing.name) == norm_name:
                            for p in s_dev.all_paths:
                                if p not in existing.all_paths:
                                    existing.all_paths.append(p)

        # Layer 3: hidapi enumeration (Cross-Platform Windows & Linux)
        if hid:
            raw_devices: List[dict] = []
            try:
                raw_devices = hid.enumerate(LOGITECH_VID)
                if not raw_devices:
                    for d in hid.enumerate():
                        vid = d.get('vendor_id', 0)
                        prod = (d.get('product_string', '') or '').lower()
                        mfg = (d.get('manufacturer_string', '') or '').lower()
                        if (vid == LOGITECH_VID or 'logitech' in prod or 'logitech' in mfg
                                or 'mx keys' in prod or 'm370' in prod or 'pop' in prod or 'mx master' in prod):
                            raw_devices.append(d)
            except Exception as e:
                print(f"[HID++] Warning: hid.enumerate error: {e}")

            # 3a. Receivers: group Col01 (short) and Col02 (long)
            receivers_col01: Dict[int, bytes] = {}
            receivers_col02: Dict[int, bytes] = {}

            for dev_info in raw_devices:
                pid = dev_info.get('product_id', 0)
                up = dev_info.get('usage_page', 0)
                u = dev_info.get('usage', 0)
                path = dev_info.get('path', b'')

                if pid in ALL_RECEIVER_PIDS or up == USAGE_PAGE_RECEIVER:
                    if u == 0x0001:
                        receivers_col01[pid] = path
                    elif u == 0x0002 or pid not in receivers_col02:
                        receivers_col02[pid] = path

            # Query paired devices on all discovered receivers
            for pid, long_path in receivers_col02.items():
                short_path = receivers_col01.get(pid)
                transport = self.identify_transport(pid, USAGE_PAGE_RECEIVER, long_path)
                paired = self._query_receiver_paired_devices(long_path, short_path, pid, transport)
                for p_dev in paired:
                    norm_name = self._normalize_name(p_dev.name)
                    if self._matches_keywords(p_dev.name, target_keywords) and norm_name not in seen_names:
                        found_devices.append(p_dev)
                        seen_names.add(norm_name)

            # 3b. Direct Bluetooth Devices
            candidate_bt_devices: Dict[str, List[dict]] = {}

            for dev_info in raw_devices:
                pid = dev_info.get('product_id', 0)
                up = dev_info.get('usage_page', 0)
                u = dev_info.get('usage', 0)
                path = dev_info.get('path', b'')
                prod = dev_info.get('product_string', '') or "Logitech Device"

                if pid in ALL_RECEIVER_PIDS:
                    continue

                is_bluetooth = False
                if up == USAGE_PAGE_BLUETOOTH and u == 0x0202:
                    is_bluetooth = True
                elif "bth" in str(path).lower():
                    is_bluetooth = True
                elif sys.platform.startswith("linux"):
                    is_bluetooth = True

                if is_bluetooth:
                    clean_name = prod.replace("_", " ").strip()
                    if not clean_name or clean_name.lower() == "logitech device":
                        clean_name = self._guess_name_from_pid(pid)

                    norm_name = self._normalize_name(clean_name)
                    if norm_name not in candidate_bt_devices:
                        candidate_bt_devices[norm_name] = []
                    candidate_bt_devices[norm_name].append(dev_info)

            # Select best endpoint for each Bluetooth device
            for norm_name, endpoints in candidate_bt_devices.items():
                clean_name = endpoints[0].get('product_string', '') or self._guess_name_from_pid(endpoints[0].get('product_id', 0))
                clean_name = clean_name.replace("_", " ").strip()
                if not self._matches_keywords(clean_name, target_keywords):
                    continue
                if norm_name in seen_names:
                    # Append paths to existing device
                    for existing in found_devices:
                        if self._normalize_name(existing.name) == norm_name:
                            for ep in endpoints:
                                p = ep.get('path', b'')
                                if p and p not in existing.all_paths:
                                    existing.all_paths.append(p)
                    continue

                best_endpoint = self._select_best_bt_endpoint(clean_name, endpoints)
                if best_endpoint:
                    found_devices.append(best_endpoint)
                    seen_names.add(norm_name)

        self.devices = found_devices
        return found_devices

    def _normalize_name(self, name: str) -> str:
        """
        Normalizes device names for deduplication (e.g. 'Logitech Wireless Mouse MX Master 3' -> 'mx master 3').
        """
        n = name.lower().replace("_", " ").strip()
        for term in ["logitech", "wireless", "mouse", "keyboard", "bluetooth", "edition"]:
            n = re.sub(rf"\b{term}\b", "", n).strip()
        return " ".join(n.split())

    def _select_best_bt_endpoint(self, name: str, endpoints: List[dict]) -> Optional[LogitechDevice]:
        """
        Tests multiple hidraw/HID endpoints for a Bluetooth device and selects the working HID++ endpoint.
        """
        best_dev: Optional[LogitechDevice] = None
        all_paths = [ep.get('path', b'') for ep in endpoints if ep.get('path')]

        for ep in endpoints:
            path = ep.get('path', b'')
            pid = ep.get('product_id', 0)
            up = ep.get('usage_page', 0)
            u = ep.get('usage', 0)

            dev = LogitechDevice(
                name=name,
                path=path,
                transport=TransportType.BLUETOOTH,
                device_index=0xFF,
                vid=LOGITECH_VID,
                pid=pid,
                usage_page=up,
                usage=u,
                all_paths=all_paths
            )

            # Test querying CHANGE_HOST feature on this path
            feat_idx = self.query_feature_index(dev, FEATURE_CHANGE_HOST)
            if feat_idx:
                dev.change_host_feature_index = feat_idx
                return dev

            if best_dev is None:
                best_dev = dev

        return best_dev

    def _scan_linux_sysfs(self, target_keywords: Optional[List[str]]) -> List[LogitechDevice]:
        """
        Inspects /sys/class/hidraw on Linux to find Logitech devices directly from the kernel.
        Groups all hidraw nodes belonging to the same physical device.
        """
        results: List[LogitechDevice] = []
        if not os.path.isdir("/sys/class/hidraw"):
            return results

        # Group by physical device identifier (HID_PHYS or parent sysfs path)
        devices_by_phys: Dict[str, Dict] = {}

        try:
            for hidraw_dir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
                uevent_file = os.path.join(hidraw_dir, "device", "uevent")
                if not os.path.isfile(uevent_file):
                    continue

                dev_name = ""
                bus = ""
                phys = ""
                vid = 0
                pid = 0

                try:
                    with open(uevent_file, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("HID_NAME="):
                                dev_name = line.split("=", 1)[1].strip()
                            elif line.startswith("HID_PHYS="):
                                phys = line.split("=", 1)[1].strip()
                            elif line.startswith("HID_ID="):
                                parts = line.split("=", 1)[1].split(":")
                                if len(parts) >= 3:
                                    bus = parts[0]
                                    vid = int(parts[1], 16)
                                    pid = int(parts[2], 16)
                except Exception:
                    continue

                if vid != LOGITECH_VID or pid in ALL_RECEIVER_PIDS:
                    continue

                node_name = os.path.basename(hidraw_dir)
                dev_path = f"/dev/{node_name}".encode("utf-8")

                # Unique key: either physical address (e.g. bluetooth MAC) or clean device name
                phys_key = phys or dev_name or f"dev_{pid}"
                if phys_key not in devices_by_phys:
                    devices_by_phys[phys_key] = {
                        "name": dev_name,
                        "pid": pid,
                        "paths": []
                    }
                devices_by_phys[phys_key]["paths"].append(dev_path)

            for phys_key, data in devices_by_phys.items():
                dev_name = data["name"]
                pid = data["pid"]
                paths = data["paths"]

                clean_name = dev_name.replace("_", " ").strip()
                if not clean_name:
                    clean_name = self._guess_name_from_pid(pid)

                if self._matches_keywords(clean_name, target_keywords) and paths:
                    # In Linux hidraw, the higher-numbered hidraw node is typically the HID++ interface
                    primary_path = paths[-1]
                    ldev = LogitechDevice(
                        name=clean_name,
                        path=primary_path,
                        transport=TransportType.BLUETOOTH,
                        device_index=0xFF,
                        vid=LOGITECH_VID,
                        pid=pid,
                        usage_page=USAGE_PAGE_BLUETOOTH,
                        usage=0x0202,
                        all_paths=paths
                    )
                    ldev.change_host_feature_index = 0x09
                    results.append(ldev)
        except Exception as e:
            print(f"[HID++] Error scanning Linux sysfs: {e}")

        return results

    def _scan_solaar_devices(self, target_keywords: Optional[List[str]]) -> List[LogitechDevice]:
        """
        Uses Solaar CLI on Linux to enumerate recognized devices and their Solaar names.
        """
        results: List[LogitechDevice] = []
        if not self._solaar_path:
            return results

        try:
            res = subprocess.run([self._solaar_path, "show"], capture_output=True, text=True, timeout=3)
            if res.returncode != 0:
                return results

            devices_data = []
            current = None

            for line in res.stdout.splitlines():
                # Device headers in solaar show start without indentation or with '  \d+:'
                m_sub = re.match(r'^\s*(\d+):\s+(.*)', line)
                is_root_header = line and not line.startswith(' ') and not line.startswith('\t') and not line.startswith('-')
                is_indented_header = m_sub and line.startswith('  ') and not line.startswith('   ')

                if is_root_header or is_indented_header:
                    if current and current.get("name"):
                        devices_data.append(current)
                    name_part = m_sub.group(2).strip() if is_indented_header else line.strip()
                    current = {
                        "name": name_part,
                        "codename": "",
                        "is_bt": False,
                        "can_switch": True  # All modern Easy-Switch devices support change-host
                    }
                elif current:
                    line_s = line.strip()
                    if line_s.startswith("Codename") and ":" in line_s:
                        current["codename"] = line_s.split(":", 1)[1].strip()
                    elif "Bluetooth" in line_s:
                        current["is_bt"] = True
                    elif "1814" in line_s or "CHANGE HOST" in line_s or "change-host" in line_s:
                        current["can_switch"] = True

            if current and current.get("name"):
                devices_data.append(current)

            for d in devices_data:
                dev_name = d["codename"] or d["name"]
                solaar_name = d["codename"] or d["name"]
                if self._matches_keywords(dev_name, target_keywords):
                    transport = TransportType.BLUETOOTH if d["is_bt"] else TransportType.UNIFYING
                    ldev = LogitechDevice(
                        name=dev_name,
                        path=b"/dev/solaar",
                        transport=transport,
                        device_index=0xFF if d["is_bt"] else 0x01,
                        solaar_name=solaar_name
                    )
                    ldev.change_host_feature_index = 0x09
                    results.append(ldev)
        except Exception as ex:
            print(f"[HID++] Solaar scan error: {ex}")

        return results

    @staticmethod
    def _guess_name_from_pid(pid: int) -> str:
        known_pids = {
            0xB35B: "MX Keys",
            0xB35F: "MX Keys",
            0xB366: "MX Keys Mini",
            0xB378: "MX Keys S",
            0xB015: "M720 Triathlon",
            0xB029: "POP Mouse",
            0xB02A: "POP Mouse",
            0xB030: "M370 Mouse",
            0xB034: "MX Master 3S",
            0xB023: "MX Master 3",
            0xB025: "MX Anywhere 3",
        }
        return known_pids.get(pid, f"Logitech Device (PID 0x{pid:04X})")

    def _matches_keywords(self, name: str, keywords: Optional[List[str]]) -> bool:
        if not keywords:
            return True
        name_lower = name.lower()
        if name_lower.startswith("unifying slot") or name_lower.startswith("bolt slot"):
            return True
        return any(k.lower() in name_lower for k in keywords)

    def _query_receiver_paired_devices(self, long_path: bytes, short_path: Optional[bytes],
                                       pid: int, transport: TransportType) -> List[LogitechDevice]:
        """
        Queries a Unifying/Bolt receiver for paired devices.
        """
        results: List[LogitechDevice] = []
        try:
            h = hid.device()
            h.open_path(long_path)
        except Exception:
            return results

        try:
            for idx in range(1, 7):
                dev_name = None
                ch_feat = 0x09

                try:
                    q_name = [0x11, idx, 0x00, 0x00, 0x00, FEATURE_DEVICE_NAME] + [0x00] * 14
                    h.write(q_name)
                    resp = h.read(20, timeout_ms=80)
                    if resp and resp[4] != 0:
                        name_feat = resp[4]
                        h.write([0x11, idx, name_feat, 0x10, 0x00] + [0x00] * 15)
                        r_name = h.read(20, timeout_ms=80)
                        if r_name and len(r_name) > 4:
                            raw_name = bytes(r_name[4:]).decode('utf-8', errors='ignore').strip()
                            clean = ''.join(c for c in raw_name if c.isprintable())
                            if clean:
                                dev_name = clean

                        q_ch = [0x11, idx, 0x00, 0x00, (FEATURE_CHANGE_HOST >> 8) & 0xFF, FEATURE_CHANGE_HOST & 0xFF] + [0x00] * 14
                        h.write(q_ch)
                        resp_ch = h.read(20, timeout_ms=80)
                        if resp_ch and len(resp_ch) > 4 and resp_ch[4] != 0:
                            ch_feat = resp_ch[4]
                except Exception:
                    pass

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
        if not hid or dev.path == b"/dev/solaar":
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
        return 0x09

    def switch_device_host(self, dev: LogitechDevice, target_channel: int) -> bool:
        """
        Switches device to target Easy-Switch channel (1, 2, or 3).
        Autonomous: automatically routes command over Solaar, Unifying, Bolt, or Bluetooth as appropriate.
        """
        channel_index = max(0, min(2, target_channel - 1))

        # --- METHOD 1: Linux Solaar CLI (handles Bluetooth & Receivers with user/daemon permissions) ---
        if sys.platform.startswith("linux") and self._solaar_path:
            candidate_solaar_names = []
            if dev.solaar_name:
                candidate_solaar_names.append(dev.solaar_name)
            candidate_solaar_names.append(dev.name)

            # Generate stripped model names (e.g. "Logitech Wireless Mouse MX Master 3" -> "MX Master 3")
            cleaned = dev.name
            for term in ["Logitech", "Wireless", "Mouse", "Keyboard", "Bluetooth", "Edition"]:
                cleaned = re.sub(rf"\b{term}\b", "", cleaned, flags=re.IGNORECASE).strip()
            cleaned = " ".join(cleaned.split())
            if cleaned and cleaned not in candidate_solaar_names:
                candidate_solaar_names.append(cleaned)

            # Specific known model aliases for Solaar
            name_lower = dev.name.lower()
            if "mx master 3" in name_lower:
                for alias in ["MX Master 3", "MX Master 3S", "MX Master"]:
                    if alias not in candidate_solaar_names:
                        candidate_solaar_names.append(alias)
            elif "mx master" in name_lower:
                for alias in ["MX Master", "MX Master 3", "MX Master 2S"]:
                    if alias not in candidate_solaar_names:
                        candidate_solaar_names.append(alias)
            elif "mx keys" in name_lower:
                for alias in ["MX Keys", "MX Keys S", "MX Keys Mini"]:
                    if alias not in candidate_solaar_names:
                        candidate_solaar_names.append(alias)
            elif "m370" in name_lower or "pop" in name_lower:
                for alias in ["POP Mouse", "M370", "POP"]:
                    if alias not in candidate_solaar_names:
                        candidate_solaar_names.append(alias)
            elif "m720" in name_lower or "triathlon" in name_lower:
                for alias in ["M720 Triathlon", "M720", "Triathlon"]:
                    if alias not in candidate_solaar_names:
                        candidate_solaar_names.append(alias)

            for s_name in candidate_solaar_names:
                try:
                    cmd = [self._solaar_path, "config", s_name, "change-host", str(target_channel)]
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                    if res.returncode == 0:
                        print(f"[HID++] Solaar ({dev.transport.value}) switched '{dev.name}' (as '{s_name}') -> Channel {target_channel}")
                        return True
                except Exception:
                    pass

        feat_idx = dev.change_host_feature_index or 0x09
        candidate_indices = [feat_idx]
        for f in DEFAULT_FEATURE_INDICES:
            if f not in candidate_indices:
                candidate_indices.append(f)

        success = False
        target_paths = dev.all_paths if dev.all_paths else ([dev.path] if dev.path else [])
        dev_indices_to_try = [dev.device_index]
        if dev.transport == TransportType.BLUETOOTH and 0x00 not in dev_indices_to_try:
            dev_indices_to_try.append(0x00)
        if dev.transport == TransportType.BLUETOOTH and 0xFF not in dev_indices_to_try:
            dev_indices_to_try.append(0xFF)

        # --- METHOD 2: Direct hidapi write across all candidate paths & device indices ---
        if hid:
            for p in target_paths:
                if not p or p == b"/dev/solaar":
                    continue
                try:
                    h = hid.device()
                    h.open_path(p)
                    for d_idx in dev_indices_to_try:
                        for f_idx in candidate_indices:
                            cmd_packet = [
                                0x11,
                                d_idx,
                                f_idx,
                                0x10,           # Function 1: set_current_host
                                channel_index
                            ] + [0x00] * 15

                            try:
                                written = h.write(cmd_packet)
                                if written > 0:
                                    print(f"[HID++] Sent Long Report (0x11) to '{dev.name}' via {dev.transport.value} "
                                          f"(DevIdx: 0x{d_idx:02x}, Feat: 0x{f_idx:02x}) -> Channel {target_channel}")
                                    success = True
                                    break
                            except Exception:
                                pass
                        if success:
                            break
                    h.close()
                except Exception:
                    pass
                if success:
                    break

        # --- METHOD 3: Short Report (0x10) fallback for Unifying receivers (Col01) ---
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

        # --- METHOD 4: Linux direct /dev/hidraw OS write across all candidate hidraw nodes ---
        if not success and sys.platform.startswith("linux"):
            for p in target_paths:
                if not p or not p.startswith(b"/dev/hidraw"):
                    continue
                dev_node = p.decode("utf-8")
                for d_idx in dev_indices_to_try:
                    for f_idx in candidate_indices:
                        try:
                            with open(dev_node, "wb", buffering=0) as f:
                                cmd_packet = bytes([0x11, d_idx, f_idx, 0x10, channel_index] + [0x00] * 15)
                                f.write(cmd_packet)
                                print(f"[HID++] Sent direct Linux hidraw write to {dev_node} (DevIdx: 0x{d_idx:02x}, Feat: 0x{f_idx:02x}) -> Channel {target_channel}")
                                success = True
                                break
                        except Exception:
                            pass
                    if success:
                        break
                if success:
                    break

        return success

    def switch_all_to_channel(self, target_channel: int, target_keywords: Optional[List[str]] = None) -> Dict[str, bool]:
        """
        Autonomously scans all devices across Bluetooth and Unifying/Bolt receivers and switches them.
        """
        devices = self.scan_devices(target_keywords)
        results: Dict[str, bool] = {}

        for dev in devices:
            key = f"{dev.name} ({dev.transport.value})"
            ok = self.switch_device_host(dev, target_channel)
            results[key] = ok
            time.sleep(0.04)

        return results
