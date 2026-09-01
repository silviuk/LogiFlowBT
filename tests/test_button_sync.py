"""
Unit tests for ButtonSyncManager.
"""

from btsync.button_sync import ButtonSyncManager
from btsync.hidpp import HIDPPMaster, LogitechDevice, TransportType


def test_button_sync_device_categorization():
    hidpp = HIDPPMaster()
    dev1 = LogitechDevice("MX Keys Wireless", b"/dev/hidraw1", TransportType.BLUETOOTH)
    dev2 = LogitechDevice("MX Master 3", b"/dev/hidraw2", TransportType.BLUETOOTH)
    hidpp._cached_devices = [dev1, dev2]

    mgr = ButtonSyncManager(hidpp, enabled=True)
    kb, mice = mgr._get_keyboards_and_mice()

    assert len(kb) == 1
    assert kb[0].name == "MX Keys Wireless"
    assert len(mice) == 1
    assert mice[0].name == "MX Master 3"


def test_button_sync_disabled():
    hidpp = HIDPPMaster()
    mgr = ButtonSyncManager(hidpp, enabled=False)
    mgr.start()
    assert mgr._running is False
