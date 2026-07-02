#!/usr/bin/env python3
"""
=============================================================
  THEMES — Système de thèmes multiples (Feature 11)
  Palette sombre classique + variantes
=============================================================
"""

THEMES = {
    "Dark Orange": {
        "bg": "#0A0A0A",
        "card": "#1A1A1A",
        "card2": "#2A2A2A",
        "fg": "#F5F5F5",
        "muted": "#9CA3AF",
        "accent": "#F97316",
        "accent_h": "#EA580C",
        "green": "#22C55E",
        "green_h": "#16A34A",
        "red": "#EF4444",
        "red_h": "#DC2626",
        "yellow": "#FBBF24",
        "log_bg": "#111111",
        "name": "Dark Orange",
    },
    "Catppuccin Mocha": {
        "bg": "#1e1e2e",
        "card": "#313244",
        "card2": "#45475a",
        "fg": "#cdd6f4",
        "muted": "#a6adc8",
        "accent": "#89b4fa",
        "accent_h": "#74a0e8",
        "green": "#a6e3a1",
        "green_h": "#94d68f",
        "red": "#f38ba8",
        "red_h": "#e8798f",
        "yellow": "#f9e2af",
        "log_bg": "#181825",
        "name": "Catppuccin Mocha",
    },
    "Catppuccin Latte": {
        "bg": "#eff1f5",
        "card": "#e6e9ef",
        "card2": "#ccd0da",
        "fg": "#4c4f69",
        "muted": "#6c6f85",
        "accent": "#1e66f5",
        "accent_h": "#2a6ef5",
        "green": "#40a02b",
        "green_h": "#368a22",
        "red": "#d20f39",
        "red_h": "#b80e32",
        "yellow": "#df8e1d",
        "log_bg": "#dce0e8",
        "name": "Catppuccin Latte",
    },
    "Dracula": {
        "bg": "#282a36",
        "card": "#44475a",
        "card2": "#565a75",
        "fg": "#f8f8f2",
        "muted": "#6272a4",
        "accent": "#bd93f9",
        "accent_h": "#a97ef0",
        "green": "#50fa7b",
        "green_h": "#3ee66b",
        "red": "#ff5555",
        "red_h": "#ee3333",
        "yellow": "#f1fa8c",
        "log_bg": "#21222c",
        "name": "Dracula",
    },
    "Nord": {
        "bg": "#2e3440",
        "card": "#3b4252",
        "card2": "#434c5e",
        "fg": "#eceff4",
        "muted": "#81a1c1",
        "accent": "#88c0d0",
        "accent_h": "#6faebf",
        "green": "#a3be8c",
        "green_h": "#8fae78",
        "red": "#bf616a",
        "red_h": "#ab4f58",
        "yellow": "#ebcb8b",
        "log_bg": "#242932",
        "name": "Nord",
    },
    "Gruvbox Dark": {
        "bg": "#282828",
        "card": "#3c3836",
        "card2": "#504945",
        "fg": "#ebdbb2",
        "muted": "#a89984",
        "accent": "#83a598",
        "accent_h": "#6f9386",
        "green": "#b8bb26",
        "green_h": "#a2aa20",
        "red": "#fb4934",
        "red_h": "#e63a26",
        "yellow": "#fabd2f",
        "log_bg": "#1d2021",
        "name": "Gruvbox Dark",
    },
    "Gruvbox Light": {
        "bg": "#fbf1c7",
        "card": "#ebdbb2",
        "card2": "#d5c4a1",
        "fg": "#3c3836",
        "muted": "#7c6f64",
        "accent": "#458588",
        "accent_h": "#3a7476",
        "green": "#98971a",
        "green_h": "#7f7e14",
        "red": "#cc241d",
        "red_h": "#ae1e18",
        "yellow": "#d79921",
        "log_bg": "#f2e5bc",
        "name": "Gruvbox Light",
    },
}

THEME_NAMES = list(THEMES.keys())
DEFAULT_THEME = "Dark Orange"
_ACTIVE_THEME = None

def get(name=None):
    global _ACTIVE_THEME
    if name is None:
        name = _ACTIVE_THEME or DEFAULT_THEME
    theme = THEMES.get(name, THEMES[DEFAULT_THEME])
    _ACTIVE_THEME = name
    return dict(theme)

def apply(widget, theme_dict):
    pass

def list_names():
    return THEME_NAMES
