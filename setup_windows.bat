@echo off
echo === LogiFlowBT Windows Setup ===

echo [1/2] Installing required Python dependencies...
python -m pip install --upgrade hidapi bleak customtkinter

echo [2/2] Testing Logitech device detection...
python -m btsync.app --scan

echo.
echo === Setup Complete! ===
echo To run settings GUI:      python -m btsync.app --gui
echo To run daemon in console: python -m btsync.app --daemon
pause
