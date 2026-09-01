"""
Unit tests for Screen Edge Detector boundary calculations and hysteresis.
"""

from btsync.edge_detector import ScreenEdgeDetector


def test_edge_detector_bounds_check():
    detector = ScreenEdgeDetector(trigger_edge="right", hold_delay_ms=200)
    detector._screen_bounds = {"left": 0, "top": 0, "right": 1920, "bottom": 1080}

    # At edge
    assert detector._is_at_edge(1919, 500) is True
    assert detector._is_at_edge(1920, 500) is True
    
    # Inside screen
    assert detector._is_at_edge(1900, 500) is False
    assert detector._is_at_edge(960, 540) is False


def test_edge_detector_ratio_calculation():
    detector = ScreenEdgeDetector(trigger_edge="right")
    detector._screen_bounds = {"left": 0, "top": 0, "right": 1920, "bottom": 1000}

    # Vertical ratio
    assert detector._calculate_ratio(1920, 0) == 0.0
    assert detector._calculate_ratio(1920, 500) == 0.5
    assert detector._calculate_ratio(1920, 1000) == 1.0


def test_left_edge_detector():
    detector = ScreenEdgeDetector(trigger_edge="left")
    detector._screen_bounds = {"left": 0, "top": 0, "right": 1920, "bottom": 1080}

    assert detector._is_at_edge(0, 500) is True
    assert detector._is_at_edge(1, 500) is True
    assert detector._is_at_edge(10, 500) is False
