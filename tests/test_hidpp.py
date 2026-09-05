"""
Unit tests for Logitech HID++ protocol logic with autonomous multi-protocol support.
"""

import pytest
from btsync.hidpp import HIDPPMaster, LogitechDevice, LOGITECH_VID, FEATURE_CHANGE_HOST, TransportType


def test_device_creation():
    dev = LogitechDevice(
        name="MX Keys",
        path=b"hid_test_path",
        transport=TransportType.BLUETOOTH,
        device_index=0xFF,
        vid=LOGITECH_VID
    )
    assert dev.name == "MX Keys"
    assert dev.device_index == 0xFF
    assert dev.transport == TransportType.BLUETOOTH
    assert dev.is_receiver is False
    assert repr(dev).startswith("<LogitechDevice")


def test_receiver_device():
    dev = LogitechDevice(
        name="M370 Mouse",
        path=b"hid_rcv_long",
        transport=TransportType.UNIFYING,
        device_index=0x01,
        short_path=b"hid_rcv_short"
    )
    assert dev.is_receiver is True
    assert dev.transport == TransportType.UNIFYING
    assert dev.short_path == b"hid_rcv_short"


def test_keyword_matching():
    master = HIDPPMaster()
    keywords = ["MX Keys", "M370", "POP", "Triathlon"]
    
    assert master._matches_keywords("Logitech MX Keys Wireless", keywords) is True
    assert master._matches_keywords("Logitech M370 Mouse", keywords) is True
    assert master._matches_keywords("POP Mouse", keywords) is True
    assert master._matches_keywords("M720 Triathlon", keywords) is True
    assert master._matches_keywords("Generic USB Mouse", keywords) is False
    # Receiver slots should always match
    assert master._matches_keywords("Unifying Slot 1", keywords) is True
    assert master._matches_keywords("Bolt Slot 2", keywords) is True


def test_channel_index_conversion():
    # Target channels 1, 2, 3 map to 0, 1, 2
    for ch in [1, 2, 3]:
        idx = max(0, min(2, ch - 1))
        assert idx == ch - 1


def test_transport_identification():
    master = HIDPPMaster()
    # Unifying PID 0xC52B
    assert master.identify_transport(0xC52B, 0xFF00, b"path") == TransportType.UNIFYING
    # Bolt PID 0xC548
    assert master.identify_transport(0xC548, 0xFF00, b"path") == TransportType.BOLT
    # Bluetooth Usage Page 0xFF43
    assert master.identify_transport(0xB015, 0xFF43, b"path") == TransportType.BLUETOOTH


def test_device_name_normalization_and_matching():
    master = HIDPPMaster()
    # Identical variations of M720 mouse
    assert master._is_same_device_name("Wireless Mouse M720", "M720_Triathlon") is True
    assert master._is_same_device_name("Logitech M720 Triathlon", "M720 Triathlon") is True
    # Identical variations of MX Master 3
    assert master._is_same_device_name("Wireless Mouse MX Master 3", "MX Master 3") is True
    assert master._is_same_device_name("Logitech Wireless Mouse MX Master 3", "MX_Master_3") is True
    # Different devices should never match
    assert master._is_same_device_name("MX Keys", "MX Master 3") is False
    assert master._is_same_device_name("MX Keys", "M720 Triathlon") is False

