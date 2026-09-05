"""
Unit tests for configuration save and load.
"""

import os
import tempfile
from btsync.config import AppConfig


def test_config_defaults():
    cfg = AppConfig()
    assert cfg.my_channel == 1
    assert cfg.target_channel == 2
    assert cfg.trigger_edge == "right"
    assert "MX Keys" in cfg.devices


def test_config_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_path = os.path.join(tmpdir, "test_config.json")
        cfg = AppConfig(
            host_name="LaptopWin",
            my_channel=2,
            target_channel=1,
            trigger_edge="left",
            hold_delay_ms=300
        )
        cfg.save(cfg_path)
        assert os.path.exists(cfg_path)

        loaded = AppConfig.load(cfg_path)
        assert loaded.host_name == "LaptopWin"
        assert loaded.my_channel == 2
        assert loaded.target_channel == 1
        assert loaded.trigger_edge == "left"
        assert loaded.hold_delay_ms == 300


def test_multi_edge_channels():
    cfg = AppConfig(
        my_channel=2,
        edge_channels={
            "left": 1,
            "right": 3,
            "top": None,
            "bottom": None
        }
    )
    assert cfg.get_target_channel_for_edge("left") == 1
    assert cfg.get_target_channel_for_edge("right") == 3
    assert cfg.get_target_channel_for_edge("top") is None
    assert cfg.get_target_channel_for_edge("bottom") is None
    assert set(cfg.get_active_edges()) == {"left", "right"}

