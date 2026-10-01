"""Default masters (categories, test parameters, spec fields). Not register data."""
from __future__ import annotations

from typing import Any

CATEGORIES = [
    "Laptop",
    "Desktop",
    "Monitor",
    "Thin Client",
    "Tiny PC",
    "Server",
    "Switch",
    "All-in-One",
    "Tablet",
    "Printer",
]

BLANCCO_CATEGORIES = ["Laptop"]

TEST_PARAMS: dict[str, list[dict[str, Any]]] = {
    "Laptop": [
        {"key": "poweron", "label": "Powers on / boots to BIOS", "critical": True},
        {"key": "display", "label": "Display — no dead pixels / lines", "critical": True},
        {"key": "keyboard", "label": "Keyboard — all keys functional", "critical": False},
        {"key": "touchpad", "label": "Touchpad / trackpoint", "critical": False},
        {"key": "battery", "label": "Battery health ≥ 70%", "critical": False, "measure": "Battery health %"},
        {"key": "ports", "label": "USB / HDMI / Type-C ports", "critical": False},
        {"key": "webcam", "label": "Webcam & microphone", "critical": False},
        {"key": "audio", "label": "Speakers / audio jack", "critical": False},
        {"key": "wifi", "label": "WiFi & Bluetooth", "critical": False},
        {"key": "charger", "label": "Charger / adapter present", "critical": False},
        {"key": "biosclear", "label": "BIOS / firmware password cleared", "critical": True},
        {"key": "sanitize", "label": "Data sanitization verified (Blancco)", "critical": True, "blancco": True},
    ],
    "Desktop": [
        {"key": "poweron", "label": "Powers on / completes POST", "critical": True},
        {"key": "ram", "label": "RAM detected & stable", "critical": False, "measure": "RAM (GB)"},
        {"key": "storage", "label": "Storage detected / SMART OK", "critical": False, "measure": "Storage"},
        {"key": "ports", "label": "Front & rear ports", "critical": False},
        {"key": "psu", "label": "PSU stable under load", "critical": True},
        {"key": "gpu", "label": "Graphics output", "critical": False},
        {"key": "sanitize", "label": "Data sanitization completed", "critical": True},
    ],
    "Monitor": [
        {"key": "poweron", "label": "Powers on", "critical": True},
        {"key": "panel", "label": "Panel — no dead pixels / burn-in", "critical": True},
        {"key": "backlight", "label": "Backlight uniform", "critical": False},
        {"key": "ports", "label": "HDMI / VGA / DP inputs", "critical": False},
        {"key": "buttons", "label": "OSD buttons functional", "critical": False},
        {"key": "stand", "label": "Stand included", "critical": False},
        {"key": "cables", "label": "Power + video cable included", "critical": False},
    ],
    "Thin Client": [
        {"key": "poweron", "label": "Powers on / boots firmware", "critical": True},
        {"key": "network", "label": "Ethernet / WiFi connectivity", "critical": True},
        {"key": "ports", "label": "USB / display ports", "critical": False},
        {"key": "adapter", "label": "Power adapter present", "critical": False},
        {"key": "mount", "label": "Mount / stand included", "critical": False},
        {"key": "sanitize", "label": "Flash storage sanitized", "critical": True},
    ],
    "Tiny PC": [
        {"key": "poweron", "label": "Powers on / completes POST", "critical": True},
        {"key": "ram", "label": "RAM detected", "critical": False, "measure": "RAM (GB)"},
        {"key": "storage", "label": "Storage detected / SMART OK", "critical": False, "measure": "Storage"},
        {"key": "ports", "label": "USB / DP / HDMI ports", "critical": False},
        {"key": "wifi", "label": "WiFi & Bluetooth", "critical": False},
        {"key": "adapter", "label": "Power adapter present", "critical": False},
        {"key": "sanitize", "label": "Data sanitization completed", "critical": True},
    ],
    "Server": [
        {"key": "poweron", "label": "Powers on / POST clean", "critical": True},
        {"key": "mgmt", "label": "iDRAC / iLO / BMC accessible", "critical": False},
        {"key": "cpu", "label": "All CPUs detected", "critical": True, "measure": "CPU count"},
        {"key": "ram", "label": "All DIMMs detected", "critical": False, "measure": "RAM (GB)"},
        {"key": "drives", "label": "Drive bays & caddies present", "critical": False, "measure": "Drive count"},
        {"key": "raid", "label": "RAID controller detected", "critical": False},
        {"key": "psu", "label": "PSU redundancy OK", "critical": True},
        {"key": "rails", "label": "Rails / bezel included", "critical": False},
        {"key": "sanitize", "label": "All drives sanitized / removed", "critical": True},
    ],
    "Switch": [
        {"key": "poweron", "label": "Powers on / boots IOS-firmware", "critical": True},
        {"key": "console", "label": "Console access OK", "critical": False},
        {"key": "ports", "label": "All ports link up", "critical": True, "measure": "Port count"},
        {"key": "poe", "label": "PoE delivering power", "critical": False},
        {"key": "fans", "label": "Fans / thermals normal", "critical": False},
        {"key": "stack", "label": "Stacking module present", "critical": False},
        {"key": "configerase", "label": "Config erased to factory", "critical": True},
    ],
    "All-in-One": [
        {"key": "poweron", "label": "Powers on / completes POST", "critical": True},
        {"key": "panel", "label": "Panel — no dead pixels", "critical": True},
        {"key": "touch", "label": "Touchscreen (if applicable)", "critical": False},
        {"key": "ports", "label": "Ports functional", "critical": False},
        {"key": "webcam", "label": "Webcam & audio", "critical": False},
        {"key": "sanitize", "label": "Data sanitization completed", "critical": True},
    ],
    "Tablet": [
        {"key": "poweron", "label": "Powers on / boots OS", "critical": True},
        {"key": "panel", "label": "Screen & touch response", "critical": True},
        {"key": "battery", "label": "Battery health ≥ 70%", "critical": False, "measure": "Battery health %"},
        {"key": "cameras", "label": "Front & rear cameras", "critical": False},
        {"key": "charging", "label": "Charging port functional", "critical": False},
        {"key": "sanitize", "label": "Factory reset / MDM removed", "critical": True},
    ],
    "Printer": [
        {"key": "poweron", "label": "Powers on", "critical": True},
        {"key": "printtest", "label": "Test page prints clean", "critical": True},
        {"key": "network", "label": "Network / USB connectivity", "critical": False},
        {"key": "trays", "label": "Trays & feeders present", "critical": False},
        {"key": "consumable", "label": "Consumable level", "critical": False, "measure": "Toner %"},
        {"key": "sanitize", "label": "Internal storage sanitized", "critical": False},
    ],
}

SPEC_FIELDS: dict[str, list[str]] = {
    "Laptop": ["Processor", "Generation", "RAM", "Storage", "Screen Size", "GPU", "Year"],
    "Desktop": ["Processor", "Generation", "RAM", "Storage", "Form Factor", "GPU", "Year"],
    "Monitor": ["Screen Size", "Panel Type", "Resolution", "Year"],
    "Thin Client": ["Processor", "RAM", "Flash Storage", "OS", "Year"],
    "Tiny PC": ["Processor", "Generation", "RAM", "Storage", "Year"],
    "Server": ["Form Factor", "Processor", "CPU Count", "RAM", "Drive Config", "RAID", "PSU", "Year"],
    "Switch": ["Port Count", "Speed", "PoE", "Stackable", "Firmware", "Year"],
    "All-in-One": ["Processor", "RAM", "Storage", "Screen Size", "Year"],
    "Tablet": ["Processor", "RAM", "Storage", "Screen Size", "Cellular", "Year"],
    "Printer": ["Type", "Mono/Colour", "Duplex", "Network", "Year"],
}
