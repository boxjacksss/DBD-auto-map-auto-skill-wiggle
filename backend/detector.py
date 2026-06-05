import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, Y, BooleanVar, Button, Canvas, Checkbutton, Entry, Frame, Label, Listbox, Scrollbar, Text, Tk, Toplevel, messagebox, ttk

try:
    import mss
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageTk
except ImportError as exc:
    print("Missing Python package:", exc)
    print("Install the needed packages with:")
    print("  python -m pip install mss pillow")
    raise


PROJECT_DIR = Path(__file__).resolve().parent.parent
ASSET_DIR = PROJECT_DIR / "assets"
MAPS_DIR = ASSET_DIR / "maps"
TEMPLATE_PATH = ASSET_DIR / "image-trigger-template.png"
DEBUG_TRIGGER_CURRENT_PATH = ASSET_DIR / "debug-image-trigger-current.png"
DEBUG_TEXT_AREA_PATH = ASSET_DIR / "debug-text-area.png"
DEBUG_TEXT_AREA_PROCESSED_PATH = ASSET_DIR / "debug-text-area-processed.png"
OCR_DEBUG_DIR = ASSET_DIR / "ocr-debug"
SKILL_DEBUG_DIR = ASSET_DIR / "skill-check-debug"
OCR_DEBUG_KEEP_SESSIONS = 8
OCR_DEBUG_MAX_FRAMES_PER_SESSION = 240
OCR_QUEUE_MAX = 3
OCR_TESSERACT_TIMEOUT_SECONDS = 4
_USER32 = None

APPDATA = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
CONFIG_DIR = APPDATA / "dbd-screen-ocr-detector"
CONFIG_PATH = CONFIG_DIR / "detector-config.json"
LOG_PATH = CONFIG_DIR / "python-detector.log"
OCR_USER_WORDS_PATH = CONFIG_DIR / "dbd-map-ocr-words.txt"
TESSERACT_WINGET_ID = "UB-Mannheim.TesseractOCR"
DBD_WINDOW_TITLE_HINTS = ("dead by daylight", "deadbydaylight")

DEFAULT_CONFIG = {
    "mapDetectorEnabled": False,
    "saveOcrDebugImages": False,
    "textBox": {"x": 11, "y": 817, "width": 761, "height": 198},
    "imageTriggerBox": None,
    "scanMs": 500,
    "triggerSeenScanMs": 200,
    "ocrIntervalMs": 1000,
    "ocrWindowMs": 60000,
    "imageTriggerMeanDiffThreshold": 5,
    "imageTriggerChangedPixelRatio": 0.025,
    "imageTriggerChangedPixelThreshold": 18,
    "imageTriggerForegroundThreshold": 28,
    "imageTriggerForegroundMeanDiffThreshold": 8,
    "imageTriggerForegroundChangedRatio": 0.08,
    "skillCheck": {
        "enabled": False,
        "box": {"x": 890, "y": 470, "width": 140, "height": 140},
        "scanMs": 1,
        "cooldownMs": 0,
        "pressKey": "c",
        "screenDebugOverlay": True,
        "saveDebugImages": True,
        "whiteMin": 185,
        "whiteSpreadMax": 90,
        "redMin": 150,
        "redOtherMax": 150,
        "greatOnly": True,
        "greatHitTolerancePx": 2,
        "greatLeadDegrees": 0,
        "minGreatRedPixels": 2,
        "hitTolerancePx": 2,
        "angleToleranceDeg": 8,
        "minWhitePixels": 18,
        "minWhiteZonePixels": 24,
        "maxWhiteZoneRadialSpan": 14,
        "whiteAngleGapDeg": 8,
        "minWhiteAngleSpan": 6,
        "maxWhiteAngleSpan": 95,
        "maxWhiteTotalAngleSpan": 120,
        "minRingOutlineBins": 55,
        "maxRingOutlinePercent": 18,
        "minCenterPromptPixels": 120,
        "maxCenterPromptPixels": 420,
        "minRedPixels": 2,
        "whiteStableMs": 0,
        "ringInnerPercent": 72,
        "ringOuterPercent": 110,
    },
    "overlay": {
        "enabled": False,
        "position": "top-left",
        "side": "left",
        "sizePercent": 30,
        "opacity": 0.7,
        "margin": 24,
        "dragMode": False,
        "customPosition": False,
        "customX": None,
        "customY": None,
    },
    "autoSprint": {
        "enabled": False,
        "dbdOnly": True,
    },
}

MAPS = [
    ("The MacMillan Estate", "Coal Tower", ["Coal Tower I", "Coal Tower II"]),
    ("The MacMillan Estate", "Groaning Storehouse", ["Groaning Storehouse I", "Groaning Storehouse II"]),
    ("The MacMillan Estate", "Ironworks of Misery", ["Ironworks of Misery I", "Ironworks of Misery II"]),
    ("The MacMillan Estate", "Shelter Woods", ["Shelter Woods I", "Shelter Woods II"]),
    ("The MacMillan Estate", "Suffocation Pit", ["Suffocation Pit I", "Suffocation Pit II"]),
    ("Autohaven Wreckers", "Azarov's Resting Place", ["Azarovs Resting Place", "Azarov Resting Place"]),
    ("Autohaven Wreckers", "Blood Lodge", []),
    ("Autohaven Wreckers", "Gas Heaven", []),
    ("Autohaven Wreckers", "Wreckers' Yard", ["Wreckers Yard"]),
    ("Autohaven Wreckers", "Wretched Shop", []),
    ("Coldwind Farm", "Fractured Cowshed", []),
    ("Coldwind Farm", "Rancid Abattoir", []),
    ("Coldwind Farm", "Rotten Fields", []),
    ("Coldwind Farm", "The Thompson House", ["Thompson House"]),
    ("Coldwind Farm", "Torment Creek", []),
    ("Crotus Prenn Asylum", "Disturbed Ward", []),
    ("Crotus Prenn Asylum", "Father Campbell's Chapel", ["Father Campbells Chapel"]),
    ("Haddonfield", "Lampkin Lane", ["Haddonfield"]),
    ("Backwater Swamp", "The Pale Rose", ["Pale Rose"]),
    ("Backwater Swamp", "Grim Pantry", []),
    ("Lery's Memorial Institute", "Treatment Theatre", ["Treatment Theater", "Lerys Memorial Institute"]),
    ("Red Forest", "Mother's Dwelling", ["Mothers Dwelling"]),
    ("Red Forest", "The Temple of Purgation", ["Temple of Purgation"]),
    ("Springwood", "Badham Preschool", ["Badham Preschool I", "Badham Preschool II", "Badham Preschool III", "Badham Preschool IV", "Badham Preschool V"]),
    ("Gideon Meat Plant", "The Game", ["Gideon Meat Plant"]),
    ("Yamaoka Estate", "Family Residence", []),
    ("Yamaoka Estate", "Sanctum of Wrath", []),
    ("Ormond", "Mount Ormond Resort", []),
    ("Ormond", "Ormond Lake Mine", []),
    ("Hawkins National Laboratory", "The Underground Complex", ["Underground Complex"]),
    ("Grave of Glenvale", "Dead Dawg Saloon", []),
    ("Silent Hill", "Midwich Elementary School", ["Midwich"]),
    ("Raccoon City", "Raccoon City Police Station East Wing", ["RPD East Wing", "Raccoon City East Wing"]),
    ("Raccoon City", "Raccoon City Police Station West Wing", ["RPD West Wing", "Raccoon City West Wing"]),
    ("Raccoon City", "Raccoon City Police Station", ["RPD", "R.C.P.D.", "Raccoon City Police Department"]),
    ("Forsaken Boneyard", "Eyrie of Crows", []),
    ("Withered Isle", "Garden of Joy", []),
    ("Withered Isle", "Greenville Square", []),
    ("Withered Isle", "Freddy Fazbear's Pizza", ["Freddy Fazbears Pizza", "Freddy Fazbear Pizza", "Fazbear Pizza"]),
    ("Withered Isle", "Fallen Refuge", []),
    ("The Decimated Borgo", "The Shattered Square", ["Shattered Square"]),
    ("The Decimated Borgo", "Forgotten Ruins", []),
    ("Dvarka Deepwood", "Toba Landing", []),
    ("Dvarka Deepwood", "Nostromo Wreckage", []),
]


def deep_merge(base, incoming):
    result = dict(base)
    for key, value in (incoming or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def clean_box(box):
    if not isinstance(box, dict):
        return None
    try:
        x = int(round(float(box["x"])))
        y = int(round(float(box["y"])))
        width = int(round(float(box["width"])))
        height = int(round(float(box["height"])))
    except Exception:
        return None
    if width <= 5 or height <= 5:
        return None
    cleaned = {"x": x, "y": y, "width": width, "height": height}
    if box.get("relativeTo") == "dbd-window":
        cleaned["relativeTo"] = "dbd-window"
        try:
            if box.get("baseWidth") and box.get("baseHeight"):
                cleaned["baseWidth"] = max(1, int(round(float(box.get("baseWidth")))))
                cleaned["baseHeight"] = max(1, int(round(float(box.get("baseHeight")))))
        except Exception:
            cleaned.pop("baseWidth", None)
            cleaned.pop("baseHeight", None)
    return cleaned


def find_dbd_window_bounds():
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        matches = []

        @enum_proc_type
        def enum_proc(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            normalized = title.lower().replace(" ", "")
            if not any(hint.replace(" ", "") in normalized for hint in DBD_WINDOW_TITLE_HINTS):
                return True
            rect = RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            width = int(rect.right - rect.left)
            height = int(rect.bottom - rect.top)
            if width <= 100 or height <= 100:
                return True
            matches.append({
                "x": int(rect.left),
                "y": int(rect.top),
                "width": width,
                "height": height,
                "title": title,
            })
            return True

        user32.EnumWindows(enum_proc, 0)
        if not matches:
            return None
        return max(matches, key=lambda item: item["width"] * item["height"])
    except Exception:
        return None


def is_dbd_foreground_window():
    if os.name != "nt":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return False
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        normalized = buffer.value.strip().lower().replace(" ", "")
        return any(hint.replace(" ", "") in normalized for hint in DBD_WINDOW_TITLE_HINTS)
    except Exception:
        return False


def point_in_box(x, y, box):
    return box["x"] <= x <= box["x"] + box["width"] and box["y"] <= y <= box["y"] + box["height"]


def make_dbd_relative_box(screen_box):
    box = clean_box(screen_box)
    dbd = find_dbd_window_bounds()
    if not box or not dbd:
        return box
    center_x = box["x"] + box["width"] // 2
    center_y = box["y"] + box["height"] // 2
    if not point_in_box(center_x, center_y, dbd):
        return box
    return {
        "x": box["x"] - dbd["x"],
        "y": box["y"] - dbd["y"],
        "width": box["width"],
        "height": box["height"],
        "relativeTo": "dbd-window",
        "baseWidth": dbd["width"],
        "baseHeight": dbd["height"],
    }


def resolve_screen_box(box):
    box = clean_box(box)
    if not box:
        return None
    if box.get("relativeTo") != "dbd-window":
        return box
    dbd = find_dbd_window_bounds()
    if not dbd:
        return {key: box[key] for key in ("x", "y", "width", "height")}
    base_w = max(1, int(box.get("baseWidth") or dbd["width"]))
    base_h = max(1, int(box.get("baseHeight") or dbd["height"]))
    scale_x = dbd["width"] / base_w
    scale_y = dbd["height"] / base_h
    return clean_box({
        "x": dbd["x"] + int(round(box["x"] * scale_x)),
        "y": dbd["y"] + int(round(box["y"] * scale_y)),
        "width": int(round(box["width"] * scale_x)),
        "height": int(round(box["height"] * scale_y)),
    })


def load_config():
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        raw = {}
    cfg = deep_merge(DEFAULT_CONFIG, raw)
    cfg["textBox"] = clean_box(cfg.get("textBox")) or DEFAULT_CONFIG["textBox"]
    cfg["imageTriggerBox"] = clean_box(cfg.get("imageTriggerBox"))
    cfg["mapDetectorEnabled"] = bool(cfg.get("mapDetectorEnabled", DEFAULT_CONFIG["mapDetectorEnabled"]))
    cfg["saveOcrDebugImages"] = bool(cfg.get("saveOcrDebugImages", DEFAULT_CONFIG["saveOcrDebugImages"]))
    cfg["scanMs"] = max(100, int(float(cfg.get("scanMs") or DEFAULT_CONFIG["scanMs"])))
    cfg["triggerSeenScanMs"] = max(50, int(float(cfg.get("triggerSeenScanMs") or DEFAULT_CONFIG["triggerSeenScanMs"])))
    cfg["ocrIntervalMs"] = max(50, int(float(cfg.get("ocrIntervalMs") or DEFAULT_CONFIG["ocrIntervalMs"])))
    cfg["ocrWindowMs"] = max(1000, int(float(cfg.get("ocrWindowMs") or DEFAULT_CONFIG["ocrWindowMs"])))
    overlay = cfg.get("overlay") or {}
    position = overlay.get("position")
    if position not in {"top-left", "top-right", "bottom-left", "bottom-right"}:
        overlay["position"] = "top-left" if overlay.get("side") == "left" else "top-right"
    overlay["side"] = "left" if "left" in overlay["position"] else "right"
    cfg["overlay"] = overlay
    auto_sprint = cfg.get("autoSprint") or {}
    auto_sprint_defaults = DEFAULT_CONFIG["autoSprint"]
    auto_sprint["enabled"] = bool(auto_sprint.get("enabled", auto_sprint_defaults["enabled"]))
    auto_sprint["dbdOnly"] = bool(auto_sprint.get("dbdOnly", auto_sprint_defaults["dbdOnly"]))
    cfg["autoSprint"] = auto_sprint
    skill = cfg.get("skillCheck") or {}
    defaults = DEFAULT_CONFIG["skillCheck"]

    def skill_value(key):
        value = skill.get(key)
        return defaults[key] if value is None or value == "" else value

    skill["box"] = clean_box(skill.get("box")) or defaults["box"]
    skill["scanMs"] = max(1, min(1000, int(float(skill_value("scanMs")))))
    skill["cooldownMs"] = max(0, min(5000, int(float(skill_value("cooldownMs")))))
    skill["pressKey"] = str(skill_value("pressKey")).strip() or defaults["pressKey"]
    skill.pop("areaHotkey", None)
    skill.pop("testHotkey", None)
    skill.pop("pressHoldMs", None)
    skill.pop("targetAngleToleranceDeg", None)
    skill["screenDebugOverlay"] = bool(skill.get("screenDebugOverlay", defaults["screenDebugOverlay"]))
    skill["saveDebugImages"] = bool(skill.get("saveDebugImages", defaults["saveDebugImages"]))
    skill["whiteMin"] = max(120, min(255, int(float(skill_value("whiteMin")))))
    skill["whiteSpreadMax"] = max(10, min(160, int(float(skill_value("whiteSpreadMax")))))
    skill["redMin"] = max(80, min(255, int(float(skill_value("redMin")))))
    skill["redOtherMax"] = max(0, min(220, int(float(skill_value("redOtherMax")))))
    skill["greatOnly"] = bool(skill.get("greatOnly", defaults["greatOnly"]))
    skill["greatHitTolerancePx"] = max(2, min(6, int(float(skill_value("greatHitTolerancePx")))))
    skill["greatLeadDegrees"] = max(0, min(30, int(float(skill_value("greatLeadDegrees")))))
    skill["minGreatRedPixels"] = max(1, min(50, int(float(skill_value("minGreatRedPixels")))))
    if int(skill["minGreatRedPixels"]) in (7, 10, 16):
        skill["minGreatRedPixels"] = defaults["minGreatRedPixels"]
    skill["hitTolerancePx"] = max(0, min(20, int(float(skill_value("hitTolerancePx")))))
    skill["angleToleranceDeg"] = max(1, min(45, int(float(skill_value("angleToleranceDeg")))))
    skill["minWhitePixels"] = max(1, min(200, int(float(skill_value("minWhitePixels")))))
    skill["minWhiteZonePixels"] = max(1, min(300, int(float(skill_value("minWhiteZonePixels")))))
    skill["maxWhiteZoneRadialSpan"] = max(1, min(80, int(float(skill_value("maxWhiteZoneRadialSpan")))))
    skill["whiteAngleGapDeg"] = max(0, min(30, int(float(skill_value("whiteAngleGapDeg")))))
    skill["minWhiteAngleSpan"] = max(1, min(90, int(float(skill_value("minWhiteAngleSpan")))))
    skill["maxWhiteAngleSpan"] = max(skill["minWhiteAngleSpan"], min(180, int(float(skill_value("maxWhiteAngleSpan")))))
    skill["maxWhiteTotalAngleSpan"] = max(skill["minWhiteAngleSpan"], min(240, int(float(skill_value("maxWhiteTotalAngleSpan")))))
    skill["minRingOutlineBins"] = max(0, min(360, int(float(skill_value("minRingOutlineBins")))))
    skill["maxRingOutlinePercent"] = max(1, min(100, int(float(skill_value("maxRingOutlinePercent")))))
    skill["minCenterPromptPixels"] = max(0, min(2000, int(float(skill_value("minCenterPromptPixels")))))
    skill["maxCenterPromptPixels"] = max(0, min(5000, int(float(skill_value("maxCenterPromptPixels")))))
    skill["minRedPixels"] = max(1, min(200, int(float(skill_value("minRedPixels")))))
    skill["whiteStableMs"] = max(0, min(1000, int(float(skill_value("whiteStableMs")))))
    skill["ringInnerPercent"] = max(0, min(100, int(float(skill_value("ringInnerPercent")))))
    skill["ringOuterPercent"] = max(skill["ringInnerPercent"] + 1, min(120, int(float(skill_value("ringOuterPercent")))))
    cfg["skillCheck"] = skill
    cfg.pop("terrorRadius", None)
    return cfg


def save_config(cfg, force_overlay=False):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        existing = {}
    merged = deep_merge(existing, cfg)
    for key in ("textBox", "imageTriggerBox"):
        if not cfg.get(key) and existing.get(key):
            merged[key] = existing[key]
    if (
        not force_overlay
        and existing.get("overlay")
        and cfg.get("overlay") == DEFAULT_CONFIG["overlay"]
        and existing.get("overlay") != DEFAULT_CONFIG["overlay"]
    ):
        merged["overlay"] = existing["overlay"]
    skill = merged.get("skillCheck")
    if isinstance(skill, dict):
        skill.pop("areaHotkey", None)
        skill.pop("testHotkey", None)
        skill.pop("pressHoldMs", None)
        skill.pop("targetAngleToleranceDeg", None)
    merged.pop("terrorRadius", None)
    CONFIG_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")


def log_to_file(message):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")


def normalize_name(value):
    value = str(value or "").lower()
    value = re.sub(r"\.[^.]+$", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def compact_name(value):
    return normalize_name(value).replace(" ", "")


def slugify(value):
    return re.sub(r"(^-+|-+$)", "", re.sub(r"[^a-z0-9]+", "-", normalize_name(value)))


def levenshtein(a, b):
    previous = list(range(len(b) + 1))
    current = [0] * (len(b) + 1)
    for i, ca in enumerate(a, 1):
        current[0] = i
        for j, cb in enumerate(b, 1):
            current[j] = previous[j - 1] if ca == cb else 1 + min(previous[j], current[j - 1], previous[j - 1])
        previous, current = current, previous
    return previous[len(b)]


def build_name_candidates():
    seen = set()
    candidates = []
    for realm, name, aliases in MAPS:
        for display in [name] + list(aliases):
            normalized = normalize_name(display)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            candidates.append({
                "realm": realm,
                "name": name,
                "display": display,
                "normalized": normalized,
                "compact": compact_name(display),
            })
    return candidates


NAME_CANDIDATES = build_name_candidates()
COMMON_MATCH_WORDS = {
    "a",
    "an",
    "and",
    "i",
    "ii",
    "iii",
    "iv",
    "of",
    "the",
}


def ensure_ocr_user_words():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    words = []
    seen = set()
    for realm, name, aliases in MAPS:
        for value in [realm, name, *aliases]:
            normalized = str(value or "").strip()
            if not normalized or normalized.lower() in seen:
                continue
            seen.add(normalized.lower())
            words.append(normalized)
    OCR_USER_WORDS_PATH.write_text("\n".join(words) + "\n", encoding="utf-8")
    return OCR_USER_WORDS_PATH


def candidate_useful_words(candidate):
    return [
        word
        for word in candidate["normalized"].split()
        if len(word) >= 4 and word not in COMMON_MATCH_WORDS
    ]


def fuzzy_word_visible(words, target):
    for word in words:
        if len(word) < 2:
            continue
        max_word_dist = 1 if len(target) <= 6 else max(2, int(len(target) * 0.25))
        if word == target or levenshtein(word, target) <= max_word_dist:
            return True
    return False


def ocr_noise_reason(text):
    raw = str(text or "").strip()
    normalized = normalize_name(raw)
    if not normalized:
        return "no readable text"

    words = normalized.split()
    if not words:
        return "no readable text"

    long_words = sum(1 for word in words if len(word) >= 4)
    tiny_words = sum(1 for word in words if len(word) <= 1)
    avg_len = sum(len(word) for word in words) / len(words)
    alpha_count = sum(1 for char in raw if char.isalpha())
    printable_count = sum(1 for char in raw if not char.isspace())
    alpha_ratio = alpha_count / printable_count if printable_count else 0

    if len(words) >= 24 and (long_words / len(words) < 0.22 or avg_len < 2.7):
        return "selected text area looks like image noise, not a map title"
    if len(raw) >= 260 and alpha_ratio < 0.48:
        return "selected text area looks like image noise, not a map title"
    if len(words) >= 18 and tiny_words / len(words) > 0.45:
        return "selected text area has too many one-letter OCR fragments"
    return ""


def ocr_fallback_is_promising(text):
    if ocr_noise_reason(text):
        return False
    words = normalize_name(text).split()
    return any(len(word) >= 5 for word in words)


def match_map_name(text):
    normalized = normalize_name(text)
    if not normalized:
        return None
    noise_reason = ocr_noise_reason(text)
    compact = normalized.replace(" ", "")
    words = normalized.split()
    padded = f" {normalized} "
    best = None

    for candidate in NAME_CANDIDATES:
        candidate_words = candidate["normalized"].split()
        useful_words = candidate_useful_words(candidate)

        if f" {candidate['normalized']} " in padded:
            return {**candidate, "score": 1.0, "raw": text}

        if not noise_reason and len(candidate["compact"]) >= 10 and candidate["compact"] in compact:
            return {**candidate, "score": 0.96, "raw": text}

        if noise_reason:
            continue

        max_dist = 1 if len(candidate["normalized"]) <= 8 else max(2, int(len(candidate["normalized"]) * 0.15))
        for i in range(len(words)):
            for length in range(max(1, len(candidate_words) - 1), min(5, len(words) - i, len(candidate_words) + 1) + 1):
                chunk = " ".join(words[i:i + length])
                if abs(len(chunk) - len(candidate["normalized"])) > max_dist:
                    continue
                dist = levenshtein(chunk, candidate["normalized"])
                score = 1 - dist / max(len(chunk), len(candidate["normalized"]))
                threshold = 0.92 if len(candidate_words) == 1 else 0.88
                if useful_words and not any(word in chunk.split() for word in useful_words):
                    continue
                if dist <= max_dist and score >= threshold and (best is None or score > best["score"]):
                    best = {**candidate, "score": score, "raw": text}

        if len(useful_words) >= 2:
            matched_words = sum(1 for word in useful_words if fuzzy_word_visible(words, word))
            score = matched_words / len(useful_words)
            needed = max(2, len(useful_words) - 1)
            if matched_words >= needed and (best is None or score > best["score"]):
                best = {**candidate, "score": score, "raw": text}
        elif len(useful_words) == 1 and len(useful_words[0]) >= 7 and fuzzy_word_visible(words, useful_words[0]):
            score = 0.9
            if best is None or score > best["score"]:
                best = {**candidate, "score": score, "raw": text}

    return best


def find_tesseract():
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]:
        if Path(candidate).exists():
            return candidate
    return None


def install_tesseract_with_winget():
    winget = shutil.which("winget")
    if not winget:
        return False, "winget was not found on this PC."
    command = [
        winget,
        "install",
        "--id",
        TESSERACT_WINGET_ID,
        "-e",
        "--source",
        "winget",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--silent",
    ]
    result = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=900)
    output = "\n".join(part.strip() for part in [result.stdout, result.stderr] if part.strip())
    if result.returncode == 0:
        return True, output or "Tesseract OCR installed."
    return False, output or f"winget exited with code {result.returncode}."


def find_map_image(map_name):
    images = find_map_images(map_name)
    return images[0] if images else None


def find_map_images(map_name):
    accepted = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    target = slugify(map_name)
    aliases = set()
    for _realm, name, map_aliases in MAPS:
        if name == map_name:
            aliases = {slugify(name), *(slugify(alias) for alias in map_aliases)}
            break
    if not aliases:
        aliases = {target}

    folders = [MAPS_DIR, Path.home() / "Documents" / "dbd-map-overlay" / "maps"]
    matches = []
    for folder in folders:
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if path.suffix.lower() not in accepted:
                continue
            file_slug = slugify(path.stem)
            if any(file_slug == alias or file_slug.startswith(alias + "-") or file_slug.endswith("-" + alias) for alias in aliases):
                matches.append(path)
    def source_priority(path):
        parts = {part.lower() for part in path.parts}
        if "steam-isometric" in parts:
            return 1
        if "wiki-outlines" in parts:
            return 2
        return 0

    return sorted(matches, key=lambda path: (source_priority(path), path.name.lower()))


def map_entry_for_name(map_name):
    for realm, name, aliases in MAPS:
        if name == map_name or map_name in aliases:
            return {"realm": realm, "name": name, "aliases": aliases}
    return {"realm": "", "name": map_name, "aliases": []}


def local_map_image_folders():
    return [MAPS_DIR, Path.home() / "Documents" / "dbd-map-overlay" / "maps"]


def build_map_library_entries():
    entries = []
    known_names = {name for _realm, name, _aliases in MAPS}
    for realm, name, aliases in MAPS:
        images = find_map_images(name)
        entries.append({
            "realm": realm,
            "name": name,
            "aliases": aliases,
            "images": images,
            "known": True,
        })

    accepted = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    matched_paths = {str(path).lower() for entry in entries for path in entry["images"]}
    for folder in local_map_image_folders():
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*"), key=lambda item: item.name.lower()):
            if path.suffix.lower() not in accepted or str(path).lower() in matched_paths:
                continue
            guessed = normalize_name(path.stem).title()
            if guessed in known_names:
                continue
            entries.append({
                "realm": "Local image",
                "name": guessed,
                "aliases": [],
                "images": [path],
                "known": False,
            })

    return entries


@dataclass
class Template:
    width: int
    height: int
    rgb: bytes
    foreground_mask: bytearray
    foreground_count: int
    foreground_ratio: float
    sample_offsets: tuple
    foreground_sample_offsets: tuple


def build_sample_offsets(width, height, max_samples=4096):
    pixels = width * height
    if pixels <= max_samples:
        return tuple(range(0, pixels * 3, 3))
    stride = max(1, int((pixels / max_samples) ** 0.5))
    offsets = []
    for y in range(0, height, stride):
        row = y * width
        for x in range(0, width, stride):
            offsets.append((row + x) * 3)
    return tuple(offsets)


def clean_debug_label(value):
    return re.sub(r"[^a-z0-9-]+", "-", normalize_name(value)) or "capture"


def cleanup_ocr_debug_sessions():
    if not OCR_DEBUG_DIR.exists():
        return
    sessions = [path for path in OCR_DEBUG_DIR.iterdir() if path.is_dir()]
    sessions.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for old_session in sessions[OCR_DEBUG_KEEP_SESSIONS:]:
        try:
            shutil.rmtree(old_session)
        except OSError:
            pass


def summarize_ocr_candidates(candidates):
    best_text = ""
    best_label = ""
    match = None
    rejection_reason = ""
    combined_parts = []

    for candidate in candidates:
        text = candidate.get("text", "")
        if text:
            combined_parts.append(text)
        if text and (not best_text or len(text) > len(best_text)):
            best_text = text
            best_label = candidate.get("label", "")
        candidate_match = match_map_name(text)
        if candidate_match:
            return text, candidate.get("label", ""), candidate_match, ""
        rejection_reason = ocr_noise_reason(text) or rejection_reason

    combined_text = "\n".join(combined_parts)
    if combined_text:
        match = match_map_name(combined_text)
        if match:
            return combined_text, "combined variants", match, ""

    return best_text, best_label, match, rejection_reason


def windows_virtual_key(input_name):
    if os.name != "nt":
        raise RuntimeError("Keyboard input is only supported on Windows.")
    user32 = windows_user32()

    value = str(input_name or "").strip().lower()
    named_keys = {
        "space": 0x20,
        "spacebar": 0x20,
        "enter": 0x0D,
        "return": 0x0D,
        "shift": 0x10,
        "ctrl": 0x11,
        "control": 0x11,
        "alt": 0x12,
        "tab": 0x09,
        "esc": 0x1B,
        "escape": 0x1B,
        "0": 0x30,
        "1": 0x31,
        "2": 0x32,
        "3": 0x33,
        "4": 0x34,
        "5": 0x35,
        "6": 0x36,
        "7": 0x37,
        "8": 0x38,
        "9": 0x39,
        "c": 0x43,
    }
    vk = named_keys.get(value)
    if vk is None and len(value) == 1:
        vk_scan = user32.VkKeyScanW(ord(value))
        if vk_scan == -1:
            raise RuntimeError(f"Unsupported key: {input_name}")
        vk = vk_scan & 0xFF
    if vk is None:
        raise RuntimeError(f"Unsupported key: {input_name}")
    return vk


def windows_user32():
    if os.name != "nt":
        raise RuntimeError("Windows input is only supported on Windows.")
    global _USER32
    if _USER32 is None:
        import ctypes
        _USER32 = ctypes.windll.user32
    return _USER32


def activate_windows_input(input_name):
    if os.name != "nt":
        raise RuntimeError("Auto input is only supported on Windows.")
    user32 = windows_user32()

    value = str(input_name or "").strip().lower()
    mouse_inputs = {
        "mouse1": (0x0002, 0x0004, 0),
        "m1": (0x0002, 0x0004, 0),
        "mb1": (0x0002, 0x0004, 0),
        "button1": (0x0002, 0x0004, 0),
        "left": (0x0002, 0x0004, 0),
        "lmb": (0x0002, 0x0004, 0),
        "leftclick": (0x0002, 0x0004, 0),
        "left click": (0x0002, 0x0004, 0),
        "mouse2": (0x0008, 0x0010, 0),
        "m2": (0x0008, 0x0010, 0),
        "mb2": (0x0008, 0x0010, 0),
        "button2": (0x0008, 0x0010, 0),
        "right": (0x0008, 0x0010, 0),
        "rmb": (0x0008, 0x0010, 0),
        "rightclick": (0x0008, 0x0010, 0),
        "right click": (0x0008, 0x0010, 0),
        "mouse3": (0x0020, 0x0040, 0),
        "m3": (0x0020, 0x0040, 0),
        "mb3": (0x0020, 0x0040, 0),
        "button3": (0x0020, 0x0040, 0),
        "middle": (0x0020, 0x0040, 0),
        "mmb": (0x0020, 0x0040, 0),
        "middleclick": (0x0020, 0x0040, 0),
        "middle click": (0x0020, 0x0040, 0),
        "mouse4": (0x0080, 0x0100, 0x0001),
        "m4": (0x0080, 0x0100, 0x0001),
        "mb4": (0x0080, 0x0100, 0x0001),
        "button4": (0x0080, 0x0100, 0x0001),
        "x1": (0x0080, 0x0100, 0x0001),
        "xbutton1": (0x0080, 0x0100, 0x0001),
        "side1": (0x0080, 0x0100, 0x0001),
        "side mouse 1": (0x0080, 0x0100, 0x0001),
        "back": (0x0080, 0x0100, 0x0001),
        "mouse5": (0x0080, 0x0100, 0x0002),
        "m5": (0x0080, 0x0100, 0x0002),
        "mb5": (0x0080, 0x0100, 0x0002),
        "button5": (0x0080, 0x0100, 0x0002),
        "x2": (0x0080, 0x0100, 0x0002),
        "xbutton2": (0x0080, 0x0100, 0x0002),
        "side2": (0x0080, 0x0100, 0x0002),
        "side mouse 2": (0x0080, 0x0100, 0x0002),
        "forward": (0x0080, 0x0100, 0x0002),
    }
    if value in mouse_inputs:
        down, up, data = mouse_inputs[value]
        user32.mouse_event(down, 0, 0, data, 0)
        user32.mouse_event(up, 0, 0, data, 0)
        return

    vk = windows_virtual_key(value)
    scan = user32.MapVirtualKeyW(vk, 0)
    user32.keybd_event(vk, scan, 0, 0)
    user32.keybd_event(vk, scan, 0x0002, 0)


def set_windows_key_state(input_name, pressed):
    if os.name != "nt":
        raise RuntimeError("Windows input is only supported on Windows.")
    user32 = windows_user32()
    vk = windows_virtual_key(input_name)
    scan = user32.MapVirtualKeyW(vk, 0)
    flags = 0 if pressed else 0x0002
    user32.keybd_event(vk, scan, flags, 0)


class AutoSprintController:
    SHIFT_VKS = {0x10, 0xA0, 0xA1}
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_SYSKEYDOWN = 0x0104
    WM_SYSKEYUP = 0x0105
    WH_KEYBOARD_LL = 13
    LLKHF_INJECTED = 0x10

    def __init__(self, cfg, emit):
        self.cfg = cfg
        self.emit = emit
        self.enabled = False
        self.synthetic_shift_down = False
        self.physical_shift_down = False
        self.stop_event = threading.Event()
        self.thread = None
        self.hook = None
        self.callback_ref = None
        self.user32 = None
        self.kernel32 = None
        self.lock = threading.Lock()
        self.last_focus_state = None

    def log(self, message):
        self.emit(("log", message))

    def should_hold_shift(self):
        auto = self.cfg.get("autoSprint") or {}
        if not bool(auto.get("enabled")):
            return False
        if bool(auto.get("dbdOnly", True)) and not is_dbd_foreground_window():
            return False
        return not self.physical_shift_down

    def set_shift(self, pressed):
        if self.synthetic_shift_down == pressed:
            return
        try:
            set_windows_key_state("shift", pressed)
            self.synthetic_shift_down = pressed
        except Exception as exc:
            self.log(f"Auto Sprint input error: {exc}")

    def update_shift_state(self):
        should_hold = self.should_hold_shift()
        self.set_shift(should_hold)
        active = bool((self.cfg.get("autoSprint") or {}).get("enabled"))
        mode_text = "running" if should_hold else "walking" if self.physical_shift_down else "waiting for DBD focus"
        if active and self.last_focus_state != mode_text:
            self.last_focus_state = mode_text
            self.emit(("auto-sprint-state", mode_text))

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        if os.name != "nt":
            self.emit(("auto-sprint-state", "Auto Sprint is Windows-only."))
            return
        self.stop_event.clear()
        self.enabled = True
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        self.log("Auto Sprint started. Shift is held while DBD is focused; hold Shift to walk.")

    def stop(self):
        self.enabled = False
        self.stop_event.set()
        self.physical_shift_down = False
        self.set_shift(False)
        self.emit(("auto-sprint-state", "off"))
        self.log("Auto Sprint stopped.")

    def install_hook(self):
        import ctypes
        from ctypes import wintypes

        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p),
            ]

        hook_proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        self.kernel32.GetLastError.restype = wintypes.DWORD
        self.user32.SetWindowsHookExW.argtypes = [ctypes.c_int, hook_proc_type, ctypes.c_void_p, wintypes.DWORD]
        self.user32.SetWindowsHookExW.restype = ctypes.c_void_p
        self.user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        self.user32.CallNextHookEx.restype = ctypes.c_ssize_t
        self.user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        self.user32.UnhookWindowsHookEx.restype = wintypes.BOOL

        @hook_proc_type
        def hook_proc(n_code, w_param, l_param):
            if n_code >= 0 and bool((self.cfg.get("autoSprint") or {}).get("enabled")):
                event = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                is_shift = int(event.vkCode) in self.SHIFT_VKS
                is_injected = bool(event.flags & self.LLKHF_INJECTED)
                if is_shift and not is_injected and (not bool((self.cfg.get("autoSprint") or {}).get("dbdOnly", True)) or is_dbd_foreground_window()):
                    if int(w_param) in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
                        self.physical_shift_down = True
                        self.update_shift_state()
                        return 1
                    if int(w_param) in (self.WM_KEYUP, self.WM_SYSKEYUP):
                        self.physical_shift_down = False
                        self.update_shift_state()
                        return 1
            return self.user32.CallNextHookEx(self.hook, n_code, w_param, l_param)

        self.callback_ref = hook_proc
        module_handle = self.kernel32.GetModuleHandleW(None)
        self.hook = self.user32.SetWindowsHookExW(self.WH_KEYBOARD_LL, self.callback_ref, module_handle, 0)
        if not self.hook:
            self.hook = self.user32.SetWindowsHookExW(self.WH_KEYBOARD_LL, self.callback_ref, None, 0)
        if not self.hook:
            error = int(self.kernel32.GetLastError())
            raise RuntimeError(f"Could not install Auto Sprint keyboard hook. Windows error {error}.")

    def run(self):
        try:
            import ctypes
            from ctypes import wintypes

            self.install_hook()
            msg = wintypes.MSG()
            while not self.stop_event.is_set():
                self.update_shift_state()
                while self.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    self.user32.TranslateMessage(ctypes.byref(msg))
                    self.user32.DispatchMessageW(ctypes.byref(msg))
                self.stop_event.wait(0.03)
        except Exception as exc:
            self.emit(("auto-sprint-state", f"error: {exc}"))
            self.log(f"Auto Sprint error: {exc}")
        finally:
            self.set_shift(False)
            if self.hook and self.user32:
                try:
                    self.user32.UnhookWindowsHookEx(self.hook)
                except Exception:
                    pass
            self.hook = None
            self.callback_ref = None


class SkillCheckDetector:
    def __init__(self, cfg, emit):
        self.cfg = cfg
        self.emit = emit
        self.stop_event = threading.Event()
        self.thread = None
        self.last_press_at = 0
        self.white_history = set()
        self.white_angle_history = set()
        self.white_hit_angles = set()
        self.white_hit_mask = set()
        self.white_hit_tolerance = None
        self.white_zones = []
        self.hit_zone_ids = set()
        self.hit_zone_last_active_at = {}
        self.hit_zone_last_press_at = {}
        self.white_candidate = set()
        self.white_angle_candidate = set()
        self.white_candidate_since = 0
        self.current_red_angle = None
        self.last_debug_at = 0
        self.last_event_debug_at = {}
        self.last_visual_emit_at = 0
        self.debug_capture_id = 0
        self.debug_location_logged = False
        self.geometry_cache_key = None
        self.geometry_cache = None
        self.last_red_angle = None
        self.current_red_angle = None
        self.last_red_seen_at = 0

    def reset_skill_state(self):
        self.white_history = set()
        self.white_angle_history = set()
        self.white_hit_angles = set()
        self.white_hit_mask = set()
        self.white_hit_tolerance = None
        self.white_zones = []
        self.hit_zone_ids = set()
        self.hit_zone_last_active_at = {}
        self.hit_zone_last_press_at = {}
        self.white_candidate = set()
        self.white_angle_candidate = set()
        self.white_candidate_since = 0

    def unwrap_angle_run(self, run):
        if not run:
            return []
        values = [int(run[0])]
        previous = values[0]
        for angle in run[1:]:
            value = int(angle)
            while value < previous - 180:
                value += 360
            while value > previous + 180:
                value -= 360
            values.append(value)
            previous = value
        return values

    def update_red_direction(self, red_ring_points):
        now = time.perf_counter()
        if not red_ring_points:
            self.current_red_angle = None
            if self.last_red_seen_at and now - self.last_red_seen_at > 0.25:
                self.last_red_angle = None
            return
        sin_total = sum(math.sin(math.radians(angle)) for _x, _y, angle in red_ring_points)
        cos_total = sum(math.cos(math.radians(angle)) for _x, _y, angle in red_ring_points)
        if not sin_total and not cos_total:
            return
        current = (math.degrees(math.atan2(sin_total, cos_total)) + 360) % 360
        self.current_red_angle = current
        if self.last_red_seen_at and now - self.last_red_seen_at > 0.25:
            self.last_red_angle = None
        self.last_red_angle = current
        self.last_red_seen_at = now

    def log(self, message):
        self.emit(("log", message))

    def zone_angle_distance(self, a, b):
        return abs(((int(a) - int(b) + 180) % 360) - 180)

    def matching_hit_zone_id(self, zone_id, tolerance=8):
        for hit_id in self.hit_zone_ids:
            if self.zone_angle_distance(zone_id, hit_id) <= tolerance:
                return hit_id
        return None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.last_press_at = 0
        self.reset_skill_state()
        self.last_debug_at = 0
        self.last_event_debug_at = {}
        self.last_visual_emit_at = 0
        self.debug_capture_id = 0
        self.debug_location_logged = False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        self.log("Skill check watcher started. It captures only the selected skill-check area.")

    def stop(self):
        self.stop_event.set()
        self.reset_skill_state()
        self.log("Skill check watcher stopped.")

    def capture_box(self, sct, box):
        box = resolve_screen_box(box)
        if not box:
            raise RuntimeError("Selected skill-check area is not valid.")
        region = {
            "left": int(box["x"]),
            "top": int(box["y"]),
            "width": int(box["width"]),
            "height": int(box["height"]),
        }
        shot = sct.grab(region)
        return shot.rgb, shot.width, shot.height

    def set_learned_white_zone(self, points, angles, width, height, tolerance, reset_hits=True):
        self.white_history = set(points)
        self.white_angle_history = set(angles)
        angle_tolerance = int(self.cfg["skillCheck"]["angleToleranceDeg"])
        self.white_hit_angles = set()
        for angle in self.white_angle_history:
            for delta in range(-angle_tolerance, angle_tolerance + 1):
                self.white_hit_angles.add((angle + delta) % 360)
        self.white_hit_tolerance = tolerance
        self.white_hit_mask = set()
        self.white_zones = []
        angle_by_point = (self.geometry_cache or {}).get("angleByPoint", {})
        radius_by_point = (self.geometry_cache or {}).get("radiusByPoint", {})
        min_zone_pixels = int(self.cfg["skillCheck"].get("minWhiteZonePixels", DEFAULT_CONFIG["skillCheck"]["minWhiteZonePixels"]))
        max_radial_span_setting = int(self.cfg["skillCheck"].get("maxWhiteZoneRadialSpan", DEFAULT_CONFIG["skillCheck"]["maxWhiteZoneRadialSpan"]))
        great_tolerance = int(self.cfg["skillCheck"].get("greatHitTolerancePx", DEFAULT_CONFIG["skillCheck"]["greatHitTolerancePx"]))
        great_tolerance = max(2, min(6, great_tolerance))
        great_lead_degrees = int(self.cfg["skillCheck"].get("greatLeadDegrees", DEFAULT_CONFIG["skillCheck"]["greatLeadDegrees"]))
        max_radial_span = max(max_radial_span_setting, min(width, height) * 0.09)
        for run in self.contiguous_angle_runs(self.white_angle_history):
            zone_angles = set(run)
            unwrapped_run = self.unwrap_angle_run(run)
            unwrapped_min = min(unwrapped_run) if unwrapped_run else 0
            unwrapped_max = max(unwrapped_run) if unwrapped_run else unwrapped_min
            zone_center = ((unwrapped_min + unwrapped_max) / 2) % 360
            zone_id = int(round(zone_center)) % 360
            zone_hit_angles = set()
            zone_lead_angles = set()
            for angle in zone_angles:
                for delta in range(-angle_tolerance, angle_tolerance + 1):
                    zone_hit_angles.add((angle + delta) % 360)
                for delta in range(-great_lead_degrees, great_lead_degrees + 1):
                    zone_lead_angles.add((angle + delta) % 360)
            zone_points = {point for point in self.white_history if angle_by_point.get(point) in zone_angles}
            interior_angles = set()
            span = max(1, unwrapped_max - unwrapped_min)
            edge_inset = 0 if span <= 8 else max(1, min(7, int(round(span * 0.20))))
            for angle in zone_angles:
                candidates = [angle - 360, angle, angle + 360]
                value = min(candidates, key=lambda item: abs(item - ((unwrapped_min + unwrapped_max) / 2)))
                progress = (value - unwrapped_min) / span
                if edge_inset == 0 or edge_inset <= (value - unwrapped_min) <= span - edge_inset:
                    interior_angles.add(angle % 360)
            if not interior_angles:
                interior_angles = set(zone_angles)
            zone_mask = set()
            for x, y in zone_points:
                for dy in range(-tolerance, tolerance + 1):
                    yy = y + dy
                    if yy < 0 or yy >= height:
                        continue
                    for dx in range(-tolerance, tolerance + 1):
                        xx = x + dx
                        if 0 <= xx < width:
                            zone_mask.add((xx, yy))
            zone_radii = [radius_by_point.get(point) for point in zone_points if radius_by_point.get(point) is not None]
            radial_min = min(zone_radii) if zone_radii else 0
            radial_max = max(zone_radii) if zone_radii else 0
            radial_span = radial_max - radial_min
            radial_mid = (radial_min + radial_max) / 2
            middle_half_span = max(1.5, radial_span * 0.35)
            middle_mask = set()
            for xx, yy in zone_mask:
                radius = radius_by_point.get((xx, yy))
                if radius is not None and abs(radius - radial_mid) <= middle_half_span + tolerance:
                    middle_mask.add((xx, yy))
            great_mask = set()
            great_core_mask = set()
            interior_mask = set()
            radial_edge_inset = 1 if radial_span >= 4 else 0
            interior_radial_min = radial_min + radial_edge_inset
            interior_radial_max = radial_max - radial_edge_inset
            if interior_radial_min > interior_radial_max:
                interior_radial_min = radial_min
                interior_radial_max = radial_max
            for x, y in zone_points:
                point_angle = angle_by_point.get((x, y))
                if point_angle in interior_angles:
                    great_core_mask.add((x, y))
                for dy in range(-great_tolerance, great_tolerance + 1):
                    yy = y + dy
                    if yy < 0 or yy >= height:
                        continue
                    for dx in range(-great_tolerance, great_tolerance + 1):
                        xx = x + dx
                        if 0 <= xx < width:
                            radius = radius_by_point.get((xx, yy))
                            if radius is not None and radial_min - great_tolerance <= radius <= radial_max + great_tolerance:
                                great_mask.add((xx, yy))
                            if point_angle in interior_angles and abs(dx) <= 1 and abs(dy) <= 1:
                                radius = radius_by_point.get((xx, yy))
                                if radius is not None and interior_radial_min <= radius <= interior_radial_max:
                                    great_core_mask.add((xx, yy))
            for (xx, yy), point_angle in angle_by_point.items():
                if point_angle not in interior_angles:
                    continue
                radius = radius_by_point.get((xx, yy))
                if radius is not None and interior_radial_min <= radius <= interior_radial_max:
                    interior_mask.add((xx, yy))
            if len(zone_points) >= min_zone_pixels and radial_span <= max_radial_span:
                self.white_zones.append({
                    "id": zone_id,
                    "centerAngle": zone_center,
                    "angles": zone_angles,
                    "hitAngles": zone_hit_angles,
                    "leadAngles": zone_lead_angles,
                    "interiorAngles": interior_angles,
                    "points": zone_points,
                    "mask": zone_mask,
                    "middleMask": middle_mask,
                    "greatMask": great_mask,
                    "greatCoreMask": great_core_mask,
                    "interiorMask": interior_mask,
                    "radialMin": radial_min,
                    "radialMax": radial_max,
                    "interiorRadialMin": interior_radial_min,
                    "interiorRadialMax": interior_radial_max,
                    "radialMid": radial_mid,
                    "radialSpan": radial_span,
                    "middleHalfSpan": middle_half_span,
                    "unwrappedMin": unwrapped_min,
                    "unwrappedMax": unwrapped_max,
                })
                self.white_hit_mask.update(zone_mask)
        for x, y in self.white_history:
            for dy in range(-tolerance, tolerance + 1):
                yy = y + dy
                if yy < 0 or yy >= height:
                    continue
                for dx in range(-tolerance, tolerance + 1):
                    xx = x + dx
                    if 0 <= xx < width:
                        self.white_hit_mask.add((xx, yy))
        if reset_hits:
            self.hit_zone_ids = set()
            self.hit_zone_last_active_at = {}
            self.hit_zone_last_press_at = {}

    def contiguous_angle_runs(self, angles, max_gap=None):
        if not angles:
            return []
        if max_gap is None:
            max_gap = int(self.cfg["skillCheck"].get("whiteAngleGapDeg", DEFAULT_CONFIG["skillCheck"]["whiteAngleGapDeg"]))
        ordered = sorted(set(int(angle) % 360 for angle in angles))
        runs = []
        current = [ordered[0]]
        for angle in ordered[1:]:
            if angle - current[-1] <= max_gap + 1:
                current.append(angle)
            else:
                runs.append(current)
                current = [angle]
        runs.append(current)
        if len(runs) > 1 and (runs[0][0] + 360) - runs[-1][-1] <= max_gap + 1:
            runs[0] = runs[-1] + runs[0]
            runs.pop()
        return runs

    def skill_geometry(self, width, height, cfg):
        key = (
            width,
            height,
            int(cfg["ringInnerPercent"]),
            int(cfg["ringOuterPercent"]),
        )
        if self.geometry_cache_key == key and self.geometry_cache:
            return self.geometry_cache

        center_x = (width - 1) / 2
        center_y = (height - 1) / 2
        max_radius = min(width, height) / 2
        inner_radius = max_radius * int(cfg["ringInnerPercent"]) / 100
        outer_radius = max_radius * int(cfg["ringOuterPercent"]) / 100
        inner_radius_sq = inner_radius * inner_radius
        outer_radius_sq = outer_radius * outer_radius
        center_prompt_radius_sq = (max_radius * 0.23) * (max_radius * 0.23)
        ring_pixels = []
        center_prompt_pixels = []
        angle_by_point = {}
        radius_by_point = {}
        for pixel in range(width * height):
            x = pixel % width
            y = pixel // width
            dist_sq = (x - center_x) * (x - center_x) + (y - center_y) * (y - center_y)
            if dist_sq <= center_prompt_radius_sq:
                center_prompt_pixels.append(pixel * 3)
            if inner_radius_sq <= dist_sq <= outer_radius_sq:
                radius = math.sqrt(dist_sq)
                angle = int(round((math.degrees(math.atan2(y - center_y, x - center_x)) + 360) % 360))
                item = (pixel * 3, x, y, angle)
                ring_pixels.append(item)
                angle_by_point[(x, y)] = angle
                radius_by_point[(x, y)] = radius
        self.geometry_cache_key = key
        self.geometry_cache = {
            "ring": ring_pixels,
            "centerPrompt": center_prompt_pixels,
            "angleByPoint": angle_by_point,
            "radiusByPoint": radius_by_point,
        }
        return self.geometry_cache

    def detect_hit(self, rgb, width, height):
        cfg = self.cfg["skillCheck"]
        white_min = int(cfg["whiteMin"])
        white_spread_max = int(cfg["whiteSpreadMax"])
        red_min = int(cfg["redMin"])
        red_other_max = int(cfg["redOtherMax"])
        hit_tolerance = int(cfg["hitTolerancePx"])
        min_white = int(cfg["minWhitePixels"])
        min_white_zone_pixels = int(cfg["minWhiteZonePixels"])
        min_white_angle_span = int(cfg["minWhiteAngleSpan"])
        max_white_angle_span = int(cfg["maxWhiteAngleSpan"])
        max_white_total_angle_span = int(cfg["maxWhiteTotalAngleSpan"])
        min_ring_outline_bins = int(cfg["minRingOutlineBins"])
        max_ring_outline_percent = int(cfg.get("maxRingOutlinePercent", DEFAULT_CONFIG["skillCheck"]["maxRingOutlinePercent"]))
        min_center_prompt_pixels = int(cfg["minCenterPromptPixels"])
        max_center_prompt_pixels = int(cfg["maxCenterPromptPixels"])
        min_red = int(cfg["minRedPixels"])
        great_only = bool(cfg.get("greatOnly", DEFAULT_CONFIG["skillCheck"]["greatOnly"]))
        min_great_red = int(cfg.get("minGreatRedPixels", DEFAULT_CONFIG["skillCheck"]["minGreatRedPixels"]))
        white_stable_seconds = int(cfg["whiteStableMs"]) / 1000
        now = time.perf_counter()
        geometry = self.skill_geometry(width, height, cfg)
        white_points = set()
        red_ring_points = []
        ring_outline_angles = set()
        ring_outline_pixel_count = 0
        center_prompt_count = 0

        for i in geometry["centerPrompt"]:
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            luma = (r + g + b) / 3
            if luma >= 160 and (max(r, g, b) - min(r, g, b)) <= 80:
                center_prompt_count += 1

        for i, x, y, angle in geometry["ring"]:
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            luma = (r + g + b) / 3
            is_white = luma >= white_min and (max(r, g, b) - min(r, g, b)) <= white_spread_max
            is_red = (
                r >= red_min
                and g <= red_other_max
                and b <= red_other_max
                and r >= max(g, b) + 35
            )
            if is_white:
                white_points.add((x, y))
            ring_luma = luma
            ring_spread = max(r, g, b) - min(r, g, b)
            looks_like_ring_outline = (
                ring_luma >= 115
                and ring_spread <= 95
                and not (r >= max(g, b) + 45 and r >= 130)
            )
            if looks_like_ring_outline:
                ring_outline_pixel_count += 1
                ring_outline_angles.add(angle)
            if is_red:
                red_ring_points.append((x, y, angle))
        red_all_points = [(x, y) for x, y, _angle in red_ring_points]
        self.update_red_direction(red_ring_points)

        center_prompt_too_large = max_center_prompt_pixels > 0 and center_prompt_count > max_center_prompt_pixels
        ring_outline_pixel_percent = 100 * ring_outline_pixel_count / max(1, len(geometry["ring"]))
        ring_outline_too_full = ring_outline_pixel_percent > max_ring_outline_percent
        if center_prompt_count < min_center_prompt_pixels or center_prompt_too_large or len(ring_outline_angles) < min_ring_outline_bins or ring_outline_too_full:
            self.reset_skill_state()
            return False, 0, 0, set(), [], [], None, 0, 0

        white_angle_counts = {}
        ring_angles_by_point = geometry["angleByPoint"]
        for x, y in white_points:
            angle = ring_angles_by_point[(x, y)]
            white_angle_counts[angle] = white_angle_counts.get(angle, 0) + 1
        white_angle_bins = set()
        if white_angle_counts:
            strongest = max(white_angle_counts.values())
            threshold = 1 if strongest <= 3 else max(2, int(strongest * 0.35))
            raw_white_angles = {angle for angle, count in white_angle_counts.items() if count >= threshold}
            for run in self.contiguous_angle_runs(raw_white_angles, max_gap=2):
                if min_white_angle_span <= len(run) <= max_white_angle_span:
                    expanded_run = set()
                    for angle in run:
                        for delta in range(-2, 3):
                            expanded_run.add((angle + delta) % 360)
                    run_points = {point for point in white_points if ring_angles_by_point[point] in expanded_run}
                    if len(run_points) >= min_white_zone_pixels:
                        white_angle_bins.update(expanded_run)
            if len(white_angle_bins) > max_white_total_angle_span:
                white_angle_bins = set()
        white_zone_points = {point for point in white_points if ring_angles_by_point[point] in white_angle_bins}

        can_learn_white = not red_ring_points or len(self.white_history) < min_white or not self.white_zones
        if red_ring_points and self.white_angle_history and white_angle_bins:
            overlap = len(white_angle_bins & self.white_angle_history)
            smaller = max(1, min(len(white_angle_bins), len(self.white_angle_history)))
            if overlap / smaller < 0.25:
                can_learn_white = True
        if len(white_zone_points) >= min_white and white_angle_bins and can_learn_white:
            candidate_changed = False
            if not self.white_candidate:
                self.white_candidate = white_zone_points
                self.white_angle_candidate = white_angle_bins
                self.white_candidate_since = now
                candidate_changed = True
            else:
                overlap = len(white_angle_bins & self.white_angle_candidate)
                smaller = max(1, min(len(white_angle_bins), len(self.white_angle_candidate)))
                if overlap / smaller < 0.25:
                    self.white_candidate = white_zone_points
                    self.white_angle_candidate = white_angle_bins
                    self.white_candidate_since = now
                    candidate_changed = True
                else:
                    self.white_candidate = white_zone_points
                    self.white_angle_candidate = white_angle_bins
            if now - self.white_candidate_since >= white_stable_seconds:
                reset_hits = candidate_changed or len(self.white_history) < min_white
                self.set_learned_white_zone(self.white_candidate, self.white_angle_candidate, width, height, hit_tolerance, reset_hits=reset_hits)
        elif not red_all_points:
            self.reset_skill_state()

        learned_white = self.white_history if len(self.white_history) >= min_white else set()
        learned_angles = self.white_angle_history
        if learned_white and self.white_hit_tolerance != hit_tolerance:
            self.set_learned_white_zone(learned_white, learned_angles, width, height, hit_tolerance, reset_hits=False)
        if len(learned_white) < min_white or not learned_angles or not self.white_zones:
            return False, len(white_zone_points), 0, white_zone_points, [], red_all_points, None, len(self.white_zones), len(self.hit_zone_ids)

        red_zone_points = []
        hit_zone_id = None
        best_zone_count = 0
        active_zone_counts = {}
        active_zone_angle_counts = {}
        active_zone_points = {}
        for x, y, red_angle in red_ring_points:
            for zone in self.white_zones:
                if great_only:
                    red_radius = geometry["radiusByPoint"].get((x, y))
                    red_is_in_white_angle = red_angle in zone.get("interiorAngles", zone["hitAngles"])
                    red_is_in_marker_interior = (
                        red_radius is not None
                        and zone.get("interiorRadialMin", zone["radialMin"]) <= red_radius <= zone.get("interiorRadialMax", zone["radialMax"])
                    )
                    red_is_on_white = red_is_in_white_angle and red_is_in_marker_interior
                else:
                    red_is_on_white = (x, y) in zone["middleMask"]
                    red_is_in_white_angle = red_angle in zone["hitAngles"]
                    red_is_in_marker_interior = True
                if red_is_on_white and red_is_in_white_angle and red_is_in_marker_interior:
                    zone_id = zone["id"]
                    active_zone_counts[zone_id] = active_zone_counts.get(zone_id, 0) + 1
                    active_zone_angle_counts.setdefault(zone_id, {})
                    active_zone_angle_counts[zone_id][red_angle] = active_zone_angle_counts[zone_id].get(red_angle, 0) + 1
                    active_zone_points.setdefault(zone_id, []).append((x, y))
                    break

        required_red = min_great_red if great_only else min_red
        required_angle_red = max(2, min(5, required_red // 3)) if great_only else 1

        def strongest_angle_cluster(angle_counts):
            if not angle_counts:
                return 0
            strongest = 0
            for angle in angle_counts:
                total = 0
                for delta in (-1, 0, 1):
                    total += angle_counts.get((angle + delta) % 360, 0)
                strongest = max(strongest, total)
            return strongest

        active_zone_ids = {
            zone_id
            for zone_id, count in active_zone_counts.items()
            if count >= required_red
            and (not great_only or strongest_angle_cluster(active_zone_angle_counts.get(zone_id, {})) >= required_angle_red)
        }
        red_zone_points = []
        for zone_id in active_zone_ids:
            red_zone_points.extend(active_zone_points.get(zone_id, []))
        for zone_id in active_zone_ids:
            self.hit_zone_last_active_at[zone_id] = now
        rearm_seconds = 0.015
        rearm_angle = 8
        min_zone_repress_seconds = 0.045
        current_red_angle = self.current_red_angle
        for zone_id in list(self.hit_zone_ids):
            still_active = any(self.zone_angle_distance(zone_id, active_id) <= 8 for active_id in active_zone_ids)
            if still_active:
                self.hit_zone_last_active_at[zone_id] = now
                continue
            red_moved_away = (
                current_red_angle is not None
                and self.zone_angle_distance(zone_id, current_red_angle) >= rearm_angle
            )
            red_disappeared = current_red_angle is None and now - float(self.hit_zone_last_active_at.get(zone_id, 0)) >= 0.04
            if red_moved_away or (red_disappeared and now - float(self.hit_zone_last_active_at.get(zone_id, 0)) >= rearm_seconds):
                self.hit_zone_ids.discard(zone_id)
                self.hit_zone_last_active_at.pop(zone_id, None)

        for zone_id in active_zone_ids:
            if self.matching_hit_zone_id(zone_id) is not None:
                continue
            last_zone_press_at = float(self.hit_zone_last_press_at.get(zone_id, 0))
            if now - last_zone_press_at < min_zone_repress_seconds:
                continue
            count = active_zone_counts.get(zone_id, 0)
            if count > best_zone_count:
                best_zone_count = count
                hit_zone_id = zone_id
        hit = hit_zone_id is not None and best_zone_count >= required_red
        return hit, len(white_zone_points), len(red_zone_points), white_zone_points, red_zone_points, red_all_points, hit_zone_id, len(self.white_zones), len(self.hit_zone_ids)

    def build_highlight_preview(self, rgb, width, height, white_points, red_zone_points, red_all_points):
        image = Image.frombytes("RGB", (width, height), rgb).convert("RGBA")
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        def outline(points, color, radius=0):
            points = set(points)
            for x, y in points:
                if (
                    (x - 1, y) not in points
                    or (x + 1, y) not in points
                    or (x, y - 1) not in points
                    or (x, y + 1) not in points
                ):
                    draw.rectangle((x - radius, y - radius, x + radius, y + radius), fill=color)

        def mark(points, color, radius):
            for x, y in points:
                draw.rectangle((x - radius, y - radius, x + radius, y + radius), fill=color)

        good_points = set()
        great_points = set()
        for zone in self.white_zones:
            good_points.update(zone.get("mask", set()))
            great_points.update(zone.get("interiorMask", set()))
        outline(good_points, (30, 220, 255, 230), 0)
        outline(great_points, (255, 245, 70, 245), 0)
        mark(red_all_points, (255, 160, 0, 155), 1)
        mark(red_zone_points, (255, 0, 0, 235), 2)
        return Image.alpha_composite(image, overlay).convert("RGB").tobytes()

    def build_screen_debug_overlay(self, width, height, white_points, red_zone_points, red_all_points):
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        def outline(points, color, radius=0):
            points = set(points)
            for x, y in points:
                if (
                    (x - 1, y) not in points
                    or (x + 1, y) not in points
                    or (x, y - 1) not in points
                    or (x, y + 1) not in points
                ):
                    draw.rectangle((x - radius, y - radius, x + radius, y + radius), fill=color)

        def mark(points, color, radius):
            for x, y in points:
                draw.rectangle((x - radius, y - radius, x + radius, y + radius), fill=color)

        good_points = set()
        great_points = set()
        for zone in self.white_zones:
            good_points.update(zone.get("mask", set()))
            great_points.update(zone.get("interiorMask", set()))

        # Sparse, high-saturation non-white/non-red colors avoid feeding back into
        # detection if Windows includes the overlay in screen capture.
        outline(good_points, (30, 220, 255, 210), 0)
        outline(great_points, (255, 245, 70, 230), 0)
        mark(red_zone_points, (255, 0, 255, 230), 1)
        return overlay.tobytes()

    def save_image_atomic(self, image, path):
        temp_path = path.with_suffix(path.suffix + ".tmp")
        image.save(temp_path, format="PNG")
        temp_path.replace(path)

    def save_debug_images(self, rgb, width, height, white_points, red_zone_points, red_all_points, hit):
        if not self.cfg["skillCheck"].get("saveDebugImages"):
            return
        now = time.time()
        min_white = int(self.cfg["skillCheck"]["minWhitePixels"])
        white_seen = len(white_points) >= min_white
        red_seen = bool(red_all_points)
        red_in_zone = bool(red_zone_points)
        if not (hit or white_seen or red_seen or red_in_zone):
            return
        if hit:
            event_name = "hit"
        elif red_in_zone:
            event_name = "red-in-zone"
        elif red_seen:
            event_name = "red-visible"
        else:
            event_name = "white-visible"
        should_archive = hit or red_in_zone
        min_gap = 0.0 if hit else 0.035 if red_in_zone else 0.20 if red_seen else 0.35
        last_event_at = float(self.last_event_debug_at.get(event_name, 0))
        if not hit and now - last_event_at < min_gap:
            return
        self.last_event_debug_at[event_name] = now
        self.last_debug_at = now
        self.debug_capture_id += 1
        SKILL_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        raw_image = Image.frombytes("RGB", (width, height), rgb)
        mask = Image.new("RGB", (width, height), "#05070a")
        draw = ImageDraw.Draw(mask)

        def outline(points, color):
            points = set(points)
            for x, y in points:
                if (
                    (x - 1, y) not in points
                    or (x + 1, y) not in points
                    or (x, y - 1) not in points
                    or (x, y + 1) not in points
                ):
                    draw.point((x, y), fill=color)

        def mark(points, color, radius=0):
            for x, y in points:
                if radius:
                    draw.rectangle((x - radius, y - radius, x + radius, y + radius), fill=color)
                else:
                    draw.point((x, y), fill=color)

        for zone in self.white_zones:
            outline(zone.get("mask", set()), (30, 220, 255))
            outline(zone.get("interiorMask", set()), (255, 245, 70))
        mark(red_all_points, (255, 160, 0), 1)
        mark(red_zone_points, (255, 0, 255), 2)

        latest_raw = SKILL_DEBUG_DIR / "latest-raw.png"
        latest_mask = SKILL_DEBUG_DIR / "latest-mask.png"
        self.save_image_atomic(raw_image, latest_raw)
        self.save_image_atomic(mask, latest_mask)
        if not should_archive:
            if not self.debug_location_logged:
                self.debug_location_logged = True
                self.log(f"Skill check debug images: {SKILL_DEBUG_DIR}")
            return
        millis = int((now % 1) * 1000)
        stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{millis:03d}-{self.debug_capture_id:05d}-{event_name}"
        self.save_image_atomic(raw_image, SKILL_DEBUG_DIR / f"{stamp}-raw.png")
        self.save_image_atomic(mask, SKILL_DEBUG_DIR / f"{stamp}-mask.png")
        if not self.debug_location_logged:
            self.debug_location_logged = True
            self.log(f"Skill check debug images: {SKILL_DEBUG_DIR}")

    def run(self):
        with mss.MSS() as sct:
            while not self.stop_event.is_set():
                try:
                    cfg = self.cfg["skillCheck"]
                    box = cfg.get("box")
                    if not box:
                        self.emit(("skill-state", "No skill-check area set."))
                        self.stop_event.wait(0.5)
                        continue

                    rgb, width, height = self.capture_box(sct, box)
                    hit, white_count, red_count, white_points, red_zone_points, red_all_points, hit_zone_id, zone_count, hit_zone_count = self.detect_hit(rgb, width, height)
                    can_press = hit and hit_zone_id is not None
                    if can_press:
                        activate_windows_input(cfg.get("pressKey") or "c")
                        self.last_press_at = time.time()
                        self.hit_zone_ids.add(hit_zone_id)
                        self.hit_zone_last_press_at[hit_zone_id] = time.perf_counter()
                        hit_zone_count = len(self.hit_zone_ids)
                        self.emit(("skill-hit", f"Pressed {cfg.get('pressKey') or 'c'} at marker {hit_zone_id}; markers visible {zone_count}"))
                    self.save_debug_images(rgb, width, height, white_points, red_zone_points, red_all_points, can_press)
                    emit_visual = can_press or time.perf_counter() - self.last_visual_emit_at >= 0.075
                    if emit_visual:
                        self.last_visual_emit_at = time.perf_counter()
                        armed = len(self.white_history) >= int(cfg["minWhitePixels"])
                        preview_rgb = self.build_highlight_preview(rgb, width, height, white_points, red_zone_points, red_all_points)
                        screen_overlay = None
                        if cfg.get("screenDebugOverlay"):
                            screen_overlay = self.build_screen_debug_overlay(width, height, white_points, red_zone_points, red_all_points)
                        overlay_box = resolve_screen_box(box) or box
                        self.emit(("skill-visual", {
                            "armed": armed,
                            "hit": can_press,
                            "cooldown": hit and not can_press,
                            "white": white_count,
                            "redInZone": red_count,
                            "redTotal": len(red_all_points) if armed else 0,
                            "memory": len(self.white_history),
                            "zones": zone_count,
                            "hitZones": hit_zone_count,
                            "rgb": preview_rgb,
                            "overlayRgba": screen_overlay,
                            "box": dict(overlay_box),
                            "width": width,
                            "height": height,
                        }))
                        self.emit(("skill-score", f"markers {zone_count}, red inside target {red_count}, red total {len(red_all_points) if armed else 0}"))
                        if hit and not can_press:
                            self.emit(("skill-state", "NOW: red in a learned white zone that was already pressed."))
                        else:
                            if armed:
                                self.emit(("skill-state", f"NOW: found {zone_count} marker{'s' if zone_count != 1 else ''}; waiting for red inside target."))
                            else:
                                self.emit(("skill-state", "NOW: looking for white success zone."))
                    scan_ms = int(cfg["scanMs"])
                    if scan_ms > 1:
                        self.stop_event.wait(scan_ms / 1000)
                except Exception as exc:
                    self.emit(("skill-state", str(exc)))
                    self.log(f"Skill check error: {exc}")
                    self.stop_event.wait(1)


class Detector:
    def __init__(self, cfg, emit):
        self.cfg = cfg
        self.emit = emit
        self.stop_event = threading.Event()
        self.thread = None
        self.trigger_seen = False
        self.ocr_until = 0
        self.last_ocr_at = 0
        self.template = None
        self.tesseract = find_tesseract()
        self.last_score_emit_at = 0
        self.last_trigger_debug_at = 0
        self.ocr_queue = queue.Queue(maxsize=OCR_QUEUE_MAX)
        self.ocr_worker_thread = None
        self.ocr_session_dir = None
        self.ocr_capture_id = 0
        self.ocr_queue_drop_count = 0

    def log(self, message):
        self.emit(("log", message))

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.trigger_seen = False
        self.ocr_until = 0
        self.last_ocr_at = 0
        self.template = None
        self.ocr_queue = queue.Queue(maxsize=OCR_QUEUE_MAX)
        self.ocr_session_dir = None
        self.ocr_capture_id = 0
        self.ocr_queue_drop_count = 0
        self.ocr_worker_thread = threading.Thread(target=self.ocr_worker, args=(self.ocr_queue,), daemon=True)
        self.ocr_worker_thread.start()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        self.log("Python detector started. Trigger checks capture only the saved trigger rectangle.")

    def stop(self):
        self.stop_event.set()
        try:
            self.ocr_queue.put_nowait(None)
        except queue.Full:
            pass
        self.log("Python detector stopped.")

    def capture_box(self, sct, box):
        box = resolve_screen_box(box)
        if not box:
            raise RuntimeError("Selected map detector area is not valid.")
        region = {
            "left": int(box["x"]),
            "top": int(box["y"]),
            "width": int(box["width"]),
            "height": int(box["height"]),
        }
        shot = sct.grab(region)
        return shot.rgb, shot.width, shot.height

    def load_template(self):
        if self.template is not None:
            return self.template
        if not TEMPLATE_PATH.exists():
            raise RuntimeError("No trigger image saved yet. Use Set Trigger Area first.")
        image = Image.open(TEMPLATE_PATH).convert("RGB")
        rgb = image.tobytes()
        threshold = int(self.cfg["imageTriggerForegroundThreshold"])
        mask = bytearray(image.width * image.height)
        foreground = 0
        for pixel, i in enumerate(range(0, len(rgb), 3)):
            luma = (rgb[i] + rgb[i + 1] + rgb[i + 2]) / 3
            if luma >= threshold:
                mask[pixel] = 1
                foreground += 1
        pixels = image.width * image.height
        sample_offsets = build_sample_offsets(image.width, image.height)
        foreground_sample_offsets = tuple(offset for offset in sample_offsets if mask[offset // 3])
        self.template = Template(
            image.width,
            image.height,
            rgb,
            mask,
            foreground,
            foreground / pixels if pixels else 0,
            sample_offsets,
            foreground_sample_offsets,
        )
        return self.template

    def emit_score(self, message, force=False):
        now = time.time()
        if force or now - self.last_score_emit_at >= 0.5:
            self.last_score_emit_at = now
            self.emit(("score", message))

    def sample_rejects_trigger(self, current, template):
        offsets = template.sample_offsets
        if not offsets:
            return False, ""

        cfg = self.cfg
        mean_limit = float(cfg["imageTriggerMeanDiffThreshold"])
        changed_ratio_limit = float(cfg["imageTriggerChangedPixelRatio"])
        changed_threshold = float(cfg["imageTriggerChangedPixelThreshold"])
        foreground_threshold = float(cfg["imageTriggerForegroundThreshold"])
        foreground_mean_limit = float(cfg["imageTriggerForegroundMeanDiffThreshold"])
        foreground_changed_limit = float(cfg["imageTriggerForegroundChangedRatio"])

        sum_diff = 0.0
        changed = 0
        current_foreground = 0
        foreground_sum = 0.0
        foreground_changed = 0
        foreground_seen = 0

        for seen, i in enumerate(offsets, 1):
            cr, cg, cb = current[i], current[i + 1], current[i + 2]
            tr, tg, tb = template.rgb[i], template.rgb[i + 1], template.rgb[i + 2]
            diff = (abs(cr - tr) + abs(cg - tg) + abs(cb - tb)) / 3
            sum_diff += diff
            if diff >= changed_threshold:
                changed += 1
            if (cr + cg + cb) / 3 >= foreground_threshold:
                current_foreground += 1
            if template.foreground_mask[i // 3]:
                foreground_seen += 1
                foreground_sum += diff
                if diff >= changed_threshold:
                    foreground_changed += 1

            if seen >= 128:
                if changed / seen > changed_ratio_limit * 8:
                    return True, f"sample reject: changed {(changed / seen) * 100:.2f}%"
                if sum_diff / seen > mean_limit * 8:
                    return True, f"sample reject: mean {sum_diff / seen:.2f}"

        sample_count = len(offsets)
        mean = sum_diff / sample_count
        changed_ratio = changed / sample_count
        current_foreground_ratio = current_foreground / sample_count
        template_sample_foreground_ratio = foreground_seen / sample_count if sample_count else 0
        foreground_mean = foreground_sum / foreground_seen if foreground_seen else 255
        foreground_changed_ratio = foreground_changed / foreground_seen if foreground_seen else 1
        foreground_close = (
            template_sample_foreground_ratio > 0.01
            and current_foreground_ratio >= template_sample_foreground_ratio * 0.65
            and current_foreground_ratio <= template_sample_foreground_ratio * 1.45
        )

        self.emit_score(f"sample mean {mean:.2f}, changed {changed_ratio * 100:.2f}%")
        rejects = (
            mean > mean_limit * 4
            or changed_ratio > changed_ratio_limit * 6
            or foreground_mean > foreground_mean_limit * 4
            or foreground_changed_ratio > foreground_changed_limit * 4
            or not foreground_close
        )
        if rejects:
            return True, f"sample reject: mean {mean:.2f}, changed {changed_ratio * 100:.2f}%"
        return False, ""

    def detect_trigger(self, sct):
        box = self.cfg.get("imageTriggerBox")
        if not box:
            return False, "No trigger area set."

        template = self.load_template()
        current, width, height = self.capture_box(sct, box)
        if width != template.width or height != template.height:
            return False, f"Trigger template is {template.width}x{template.height}, but selected box is {width}x{height}."

        cfg = self.cfg
        pixels = width * height
        rejected, sample_message = self.sample_rejects_trigger(current, template)
        if rejected:
            self.emit_score(sample_message)
            return False, ""

        sum_diff = 0.0
        max_diff = 0.0
        changed = 0
        current_foreground = 0
        foreground_sum_diff = 0.0
        foreground_changed = 0
        changed_threshold = float(cfg["imageTriggerChangedPixelThreshold"])
        foreground_threshold = float(cfg["imageTriggerForegroundThreshold"])
        mean_limit = float(cfg["imageTriggerMeanDiffThreshold"])
        changed_ratio_limit = float(cfg["imageTriggerChangedPixelRatio"])
        foreground_mean_limit = float(cfg["imageTriggerForegroundMeanDiffThreshold"])
        foreground_changed_ratio_limit = float(cfg["imageTriggerForegroundChangedRatio"])
        max_sum_diff = mean_limit * pixels
        max_changed = int(changed_ratio_limit * pixels)
        max_foreground_sum = foreground_mean_limit * template.foreground_count
        max_foreground_changed = int(foreground_changed_ratio_limit * template.foreground_count)

        for pixel, i in enumerate(range(0, len(current), 3)):
            cr, cg, cb = current[i], current[i + 1], current[i + 2]
            tr, tg, tb = template.rgb[i], template.rgb[i + 1], template.rgb[i + 2]
            current_luma = (cr + cg + cb) / 3
            diff = (abs(cr - tr) + abs(cg - tg) + abs(cb - tb)) / 3
            sum_diff += diff
            if diff > max_diff:
                max_diff = diff
            if diff >= changed_threshold:
                changed += 1
            if current_luma >= foreground_threshold:
                current_foreground += 1
            if template.foreground_mask[pixel]:
                foreground_sum_diff += diff
                if diff >= changed_threshold:
                    foreground_changed += 1

            if sum_diff > max_sum_diff or changed > max_changed:
                self.emit_score(f"reject: mean>{mean_limit:.2f} or changed>{changed_ratio_limit * 100:.2f}%")
                return False, ""
            if template.foreground_mask[pixel] and (
                foreground_sum_diff > max_foreground_sum or foreground_changed > max_foreground_changed
            ):
                self.emit_score("reject: foreground mismatch")
                return False, ""

        mean_diff = sum_diff / pixels
        changed_ratio = changed / pixels
        current_foreground_ratio = current_foreground / pixels
        foreground_mean = foreground_sum_diff / template.foreground_count if template.foreground_count else 255
        foreground_changed_ratio = foreground_changed / template.foreground_count if template.foreground_count else 1
        foreground_close = (
            template.foreground_ratio > 0.01
            and current_foreground_ratio >= template.foreground_ratio * 0.72
            and current_foreground_ratio <= template.foreground_ratio * 1.35
        )
        visible = (
            mean_diff <= mean_limit
            and changed_ratio <= changed_ratio_limit
            and foreground_mean <= foreground_mean_limit
            and foreground_changed_ratio <= foreground_changed_ratio_limit
            and foreground_close
        )

        self.emit_score(f"mean {mean_diff:.2f}, changed {changed_ratio * 100:.2f}%, fg {foreground_mean:.2f}", force=visible)
        if visible and time.time() - self.last_trigger_debug_at >= 1:
            self.last_trigger_debug_at = time.time()
            ASSET_DIR.mkdir(parents=True, exist_ok=True)
            Image.frombytes("RGB", (width, height), current).save(DEBUG_TRIGGER_CURRENT_PATH)
        return visible, ""

    def ensure_ocr_engine(self):
        if self.tesseract:
            return self.tesseract
        self.tesseract = find_tesseract()
        if self.tesseract:
            return self.tesseract
        raise RuntimeError("OCR is not installed yet. The app will try to install Tesseract automatically.")

    def build_ocr_variants(self, image):
        variants = []

        def add_variant(label, source, scale=3, invert=False, threshold=None, contrast=2.0, crop=None):
            if crop:
                left, top, right, bottom = crop
                source = source.crop((
                    int(source.width * left),
                    int(source.height * top),
                    int(source.width * right),
                    int(source.height * bottom),
                ))
            work = source.resize((source.width * scale, source.height * scale), Image.Resampling.LANCZOS)
            work = ImageOps.grayscale(work)
            work = ImageOps.autocontrast(work)
            if invert:
                work = ImageOps.invert(work)
            work = ImageEnhance.Contrast(work).enhance(contrast)
            work = work.filter(ImageFilter.SHARPEN)
            if threshold is not None:
                work = work.point(lambda px: 255 if px >= threshold else 0)
            variants.append((label, work))

        title_crop = (0.02, 0.06, 0.78, 0.50)
        title_wide_crop = (0.00, 0.00, 0.84, 0.58)
        add_variant("title-threshold-4x", image, scale=4, invert=False, threshold=165, contrast=2.0, crop=title_crop)
        add_variant("title-contrast-4x", image, scale=4, invert=False, threshold=None, contrast=2.3, crop=title_crop)
        add_variant("title-inverted-contrast-4x", image, scale=4, invert=True, threshold=None, contrast=2.4, crop=title_crop)
        add_variant("title-wide-threshold-4x", image, scale=4, invert=False, threshold=165, contrast=2.0, crop=title_wide_crop)
        add_variant("inverted-contrast-3x", image, scale=3, invert=True, threshold=None, contrast=2.4)
        add_variant("inverted-threshold-3x", image, scale=3, invert=True, threshold=150, contrast=2.2)
        add_variant("contrast-3x", image, scale=3, invert=False, threshold=None, contrast=2.0)
        add_variant("threshold-4x", image, scale=4, invert=False, threshold=165, contrast=2.0)
        return variants

    def run_tesseract(self, image, label, psm):
        tesseract = self.ensure_ocr_engine()
        user_words = ensure_ocr_user_words()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            temp_path = Path(tmp.name)
        try:
            image.save(temp_path)
            command = [
                tesseract,
                str(temp_path),
                "stdout",
                "--oem",
                "1",
                "--psm",
                str(psm),
                "-l",
                "eng",
                "--user-words",
                str(user_words),
                "-c",
                "preserve_interword_spaces=1",
                "-c",
                "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .'-",
            ]
            result = subprocess.run(
                command,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=OCR_TESSERACT_TIMEOUT_SECONDS,
                cwd=PROJECT_DIR,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "Tesseract OCR failed.")
            return {
                "label": f"{label}/psm{psm}",
                "text": result.stdout.strip(),
            }
        except subprocess.TimeoutExpired:
            return {
                "label": f"{label}/psm{psm}/timeout",
                "text": "",
            }
        finally:
            try:
                temp_path.unlink()
            except OSError:
                pass

    def begin_ocr_debug_session(self):
        if self.ocr_session_dir:
            return self.ocr_session_dir
        OCR_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        cleanup_ocr_debug_sessions()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.ocr_session_dir = OCR_DEBUG_DIR / stamp
        suffix = 1
        while self.ocr_session_dir.exists():
            suffix += 1
            self.ocr_session_dir = OCR_DEBUG_DIR / f"{stamp}-{suffix}"
        self.ocr_session_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"OCR debug screenshots will be saved in: {self.ocr_session_dir}")
        return self.ocr_session_dir

    def save_ocr_result_debug(self, raw_path, candidates, elapsed_ms, match, rejection_reason):
        if not raw_path:
            return
        try:
            lines = [f"elapsed_ms={elapsed_ms}"]
            if match:
                lines.append(f"match={match['name']} score={match['score']:.2f}")
            elif rejection_reason:
                lines.append(f"rejected={rejection_reason}")
            else:
                lines.append("match=")
            for candidate in candidates:
                lines.append("")
                lines.append(f"[{candidate.get('label', 'unknown')}]")
                lines.append(candidate.get("text", "") or "(empty)")
            raw_path.with_suffix(".txt").write_text("\n".join(lines), encoding="utf-8")
        except OSError:
            pass

    def read_text_candidates_from_image(self, image, raw_path=None, live_budget_seconds=None, work_queue=None):
        started = time.perf_counter()

        def should_yield_to_newer_frame():
            if live_budget_seconds is None or work_queue is None:
                return False
            return time.perf_counter() - started >= live_budget_seconds and work_queue.qsize() > 0

        variants = self.build_ocr_variants(image)
        if self.cfg.get("saveOcrDebugImages"):
            ASSET_DIR.mkdir(parents=True, exist_ok=True)
            image.save(DEBUG_TEXT_AREA_PATH)
            variants[0][1].save(DEBUG_TEXT_AREA_PROCESSED_PATH)
        if raw_path:
            try:
                processed_path = raw_path.with_name(raw_path.stem.replace("-raw", "-processed") + raw_path.suffix)
                variants[0][1].save(processed_path)
            except OSError:
                pass

        candidates = []
        fallback_variants = []
        title_variants = variants[:4]
        full_variants = variants[4:]
        for label, variant in title_variants:
            for psm in (7, 6, 11):
                candidate = self.run_tesseract(variant, label, psm)
                candidates.append(candidate)
                if match_map_name(candidate["text"]):
                    return candidates
                if should_yield_to_newer_frame():
                    candidates.append({"label": "live-budget/newer-frame", "text": ""})
                    return candidates

        primary_variants = full_variants[:2]
        secondary_variants = full_variants[2:]
        for label, variant in primary_variants:
            candidate = self.run_tesseract(variant, label, 7)
            candidates.append(candidate)
            if match_map_name(candidate["text"]):
                return candidates
            if should_yield_to_newer_frame():
                candidates.append({"label": "live-budget/newer-frame", "text": ""})
                return candidates
            if ocr_fallback_is_promising(candidate["text"]):
                fallback_variants.append((label, variant))

        if not fallback_variants:
            return candidates

        for label, variant in fallback_variants[:2]:
            candidate = self.run_tesseract(variant, label, 6)
            candidates.append(candidate)
            if match_map_name(candidate["text"]):
                return candidates
            if should_yield_to_newer_frame():
                candidates.append({"label": "live-budget/newer-frame", "text": ""})
                return candidates
            recent_reasons = [ocr_noise_reason(item["text"]) for item in candidates[-2:]]
            if len(candidates) >= 2 and all(reason and reason != "no readable text" for reason in recent_reasons):
                return candidates

        for label, variant in secondary_variants:
            candidate = self.run_tesseract(variant, label, 7)
            candidates.append(candidate)
            if match_map_name(candidate["text"]):
                return candidates
            if should_yield_to_newer_frame():
                candidates.append({"label": "live-budget/newer-frame", "text": ""})
                return candidates
        return candidates

    def read_text_candidates(self, sct):
        box = self.cfg["textBox"]
        rgb, width, height = self.capture_box(sct, box)
        image = Image.frombytes("RGB", (width, height), rgb)
        return self.read_text_candidates_from_image(image)

    def read_text_area(self, sct):
        candidates = self.read_text_candidates(sct)
        return candidates[0]["text"] if candidates else ""

    def run_ocr_pass(self, sct):
        started = time.perf_counter()
        box = self.cfg["textBox"]
        rgb, width, height = self.capture_box(sct, box)
        image = Image.frombytes("RGB", (width, height), rgb)
        candidates = self.read_text_candidates_from_image(image)
        self.last_ocr_at = time.time()
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        best_text, best_label, match, rejection_reason = summarize_ocr_candidates(candidates)
        self.emit(("ocr", best_text or "(no text detected)"))
        self.log(f"OCR timing: {elapsed_ms} ms; variant: {best_label or 'none'}; text: {best_text or '(empty)'}")
        if match:
            self.ocr_until = 0
            self.emit(("match", match))
            self.log(f"Matched map: {match['name']} ({match['score']:.2f})")
        elif rejection_reason:
            self.emit(("state", "OCR rejected noisy text. Recheck the selected text area."))
            self.log(f"OCR rejected: {rejection_reason}. Set Text Area should cover the map name text, not gameplay.")
        return match

    def enqueue_ocr_capture(self, sct, reason):
        box = self.cfg["textBox"]
        rgb, width, height = self.capture_box(sct, box)
        image = Image.frombytes("RGB", (width, height), rgb)
        self.last_ocr_at = time.time()
        self.ocr_capture_id += 1
        capture_id = self.ocr_capture_id

        raw_path = None
        if self.cfg.get("saveOcrDebugImages") and capture_id <= OCR_DEBUG_MAX_FRAMES_PER_SESSION:
            session_dir = self.begin_ocr_debug_session()
            millis = int((time.time() % 1) * 1000)
            stamp = f"{time.strftime('%H%M%S')}-{millis:03d}"
            label = clean_debug_label(reason)
            raw_path = session_dir / f"{capture_id:03d}-{stamp}-{label}-raw.png"
            try:
                image.save(raw_path)
                image.save(DEBUG_TEXT_AREA_PATH)
            except OSError:
                raw_path = None
        elif self.cfg.get("saveOcrDebugImages") and capture_id == OCR_DEBUG_MAX_FRAMES_PER_SESSION + 1:
            self.log(f"OCR debug screenshot cap reached for this window ({OCR_DEBUG_MAX_FRAMES_PER_SESSION} frames). New frames will still be processed.")

        job = {
            "id": capture_id,
            "image": image,
            "raw_path": raw_path,
            "reason": reason,
            "created_at": time.time(),
        }
        dropped_before_put = self.clear_ocr_queue()
        if dropped_before_put:
            self.ocr_queue_drop_count += dropped_before_put
        try:
            self.ocr_queue.put_nowait(job)
        except queue.Full:
            try:
                self.ocr_queue.get_nowait()
                self.ocr_queue.task_done()
            except queue.Empty:
                pass
            self.ocr_queue_drop_count += 1
            try:
                self.ocr_queue.put_nowait(job)
            except queue.Full:
                return
            if self.ocr_queue_drop_count == 1 or self.ocr_queue_drop_count % 10 == 0:
                self.log(f"OCR queue is full; dropped {self.ocr_queue_drop_count} older frame(s) so fresh screenshots keep flowing.")

        if capture_id == 1 or capture_id % 20 == 0:
            location = f" saved to {raw_path}" if raw_path else ""
            self.log(f"OCR captured frame {capture_id:03d}; queue={self.ocr_queue.qsize()}.{location}")

    def clear_ocr_queue(self, work_queue=None):
        work_queue = work_queue or self.ocr_queue
        cleared = 0
        while True:
            try:
                work_queue.get_nowait()
                work_queue.task_done()
                cleared += 1
            except queue.Empty:
                return cleared

    def get_latest_ocr_job(self, first_job, work_queue):
        latest = first_job
        skipped = 0
        while True:
            try:
                next_job = work_queue.get_nowait()
            except queue.Empty:
                break
            if next_job is None:
                if latest is not None:
                    work_queue.task_done()
                return None, skipped
            if latest is not None:
                skipped += 1
                work_queue.task_done()
            latest = next_job
        if skipped:
            self.ocr_queue_drop_count += skipped
            self.log(f"OCR skipped {skipped} stale queued frame(s); processing newest frame {latest['id']:03d}.")
        return latest, skipped

    def process_ocr_job(self, job, work_queue=None):
        if self.ocr_until <= 0:
            return
        started = time.perf_counter()
        candidates = self.read_text_candidates_from_image(
            job["image"],
            job.get("raw_path"),
            live_budget_seconds=2.5,
            work_queue=work_queue,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        best_text, best_label, match, rejection_reason = summarize_ocr_candidates(candidates)
        self.save_ocr_result_debug(job.get("raw_path"), candidates, elapsed_ms, match, rejection_reason)
        self.emit(("ocr", best_text or "(no text detected)"))
        self.log(
            f"OCR frame {job['id']:03d} timing: {elapsed_ms} ms; "
            f"variant: {best_label or 'none'}; text: {best_text or '(empty)'}"
        )
        if match:
            self.ocr_until = 0
            self.clear_ocr_queue(work_queue)
            self.emit(("match", match))
            self.log(f"Matched map from OCR frame {job['id']:03d}: {match['name']} ({match['score']:.2f})")
        elif rejection_reason:
            self.emit(("state", "OCR rejected noisy text. Recheck the selected text area."))
            self.log(f"OCR frame {job['id']:03d} rejected: {rejection_reason}.")

    def ocr_worker(self, work_queue):
        while not self.stop_event.is_set():
            try:
                job = work_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if job is None:
                    return
                job, _skipped = self.get_latest_ocr_job(job, work_queue)
                if job is None:
                    return
                self.process_ocr_job(job, work_queue)
            except Exception as exc:
                self.emit(("state", str(exc)))
                self.log(f"OCR worker error: {exc}")
            finally:
                work_queue.task_done()

    def run(self):
        with mss.MSS() as sct:
            while not self.stop_event.is_set():
                try:
                    now = time.time()
                    if self.ocr_until and now < self.ocr_until:
                        if now - self.last_ocr_at >= self.cfg["ocrIntervalMs"] / 1000:
                            self.emit(("state", f"OCR capturing, {int(self.ocr_until - now)}s left; queue={self.ocr_queue.qsize()}"))
                            self.enqueue_ocr_capture(sct, "timer")
                        self.stop_event.wait(self.cfg["ocrIntervalMs"] / 1000)
                        continue
                    if self.ocr_until and now >= self.ocr_until:
                        self.ocr_until = 0
                        self.emit(("state", "OCR window expired. Waiting for trigger image."))

                    visible, reason = self.detect_trigger(sct)
                    if reason:
                        self.emit(("state", reason))
                        self.stop_event.wait(0.5)
                        continue

                    if visible:
                        self.trigger_seen = True
                        self.emit(("state", "Trigger visible. Waiting for it to disappear."))
                        self.stop_event.wait(self.cfg["triggerSeenScanMs"] / 1000)
                        continue

                    if self.trigger_seen:
                        self.trigger_seen = False
                        self.ocr_until = time.time() + self.cfg["ocrWindowMs"] / 1000
                        self.last_ocr_at = 0
                        self.ocr_session_dir = None
                        self.ocr_capture_id = 0
                        self.ocr_queue_drop_count = 0
                        self.clear_ocr_queue()
                        self.emit(("state", "Trigger disappeared. OCR capture queue starting."))
                        try:
                            self.enqueue_ocr_capture(sct, "trigger-disappeared")
                        except Exception as exc:
                            self.ocr_until = 0
                            self.emit(("state", str(exc)))
                            self.log(str(exc))
                        continue

                    self.emit(("state", "Waiting for trigger image."))
                    self.stop_event.wait(self.cfg["scanMs"] / 1000)
                except Exception as exc:
                    self.emit(("state", str(exc)))
                    self.log(f"Error: {exc}")
                    self.stop_event.wait(1)


class MapOverlay:
    NORMAL_BG = "#000000"
    DRAG_BG = "#111111"

    def __init__(self, root, cfg):
        self.root = root
        self.cfg = cfg
        self.window = None
        self.label = None
        self.photo = None
        self.last_image_path = None
        self.last_error = ""
        self.last_drag_mode = None
        self.last_layout_key = None
        self.drag_start = None
        self.clickthrough_hwnd = None
        self.clickthrough_procs = {}
        self.original_wndproc = None
        self.native_bitmap = None

    def apply_window_transparency(self, drag_mode, bg):
        if not self.window:
            return
        try:
            if os.name == "nt" and not drag_mode:
                self.window.attributes("-transparentcolor", bg)
            elif os.name == "nt":
                self.window.attributes("-transparentcolor", "")
        except Exception:
            pass

    def screen_bounds(self):
        dbd = find_dbd_window_bounds()
        if dbd:
            return dbd["x"], dbd["y"], dbd["width"], dbd["height"]
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32

                class RECT(ctypes.Structure):
                    _fields_ = [
                        ("left", ctypes.c_long),
                        ("top", ctypes.c_long),
                        ("right", ctypes.c_long),
                        ("bottom", ctypes.c_long),
                    ]

                class MONITORINFO(ctypes.Structure):
                    _fields_ = [
                        ("cbSize", wintypes.DWORD),
                        ("rcMonitor", RECT),
                        ("rcWork", RECT),
                        ("dwFlags", wintypes.DWORD),
                    ]

                monitor = user32.MonitorFromWindow(self.root.winfo_id(), 2)  # MONITOR_DEFAULTTONEAREST
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(MONITORINFO)
                if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    rect = info.rcMonitor
                    width = int(rect.right - rect.left)
                    height = int(rect.bottom - rect.top)
                    if width > 0 and height > 0:
                        return int(rect.left), int(rect.top), width, height

                x = int(user32.GetSystemMetrics(76))  # SM_XVIRTUALSCREEN fallback
                y = int(user32.GetSystemMetrics(77))  # SM_YVIRTUALSCREEN fallback
                width = int(user32.GetSystemMetrics(78))  # SM_CXVIRTUALSCREEN fallback
                height = int(user32.GetSystemMetrics(79))  # SM_CYVIRTUALSCREEN fallback
                if width > 0 and height > 0:
                    return x, y, width, height
            except Exception:
                pass
        return 0, 0, int(self.root.winfo_screenwidth()), int(self.root.winfo_screenheight())

    def corner_position(self, overlay_cfg, window_w, window_h):
        screen_x, screen_y, screen_w, screen_h = self.screen_bounds()
        margin = int(overlay_cfg.get("margin") or 24)
        if overlay_cfg.get("customPosition") and overlay_cfg.get("customX") is not None and overlay_cfg.get("customY") is not None:
            x = int(overlay_cfg["customX"])
            y = int(overlay_cfg["customY"])
        else:
            position = overlay_cfg.get("position")
            if not position:
                position = "top-left" if overlay_cfg.get("side") == "left" else "top-right"
            x = screen_x + margin if "left" in position else screen_x + screen_w - window_w - margin
            y = screen_y + margin if "top" in position else screen_y + screen_h - window_h - margin

        min_x = screen_x
        min_y = screen_y
        max_x = screen_x + max(0, screen_w - window_w)
        max_y = screen_y + max(0, screen_h - window_h)
        return max(min_x, min(max_x, x)), max(min_y, min(max_y, y))

    def update(self, match=None, image_path=None, map_name=None, force_recreate=False):
        overlay_cfg = self.cfg.get("overlay") or {}
        if not overlay_cfg.get("enabled"):
            self.close()
            return
        display_name = map_name
        self.last_error = ""
        if match:
            display_name = match["name"]
            image_path = find_map_image(match["name"]) or image_path
        desired_image_path = str(image_path) if image_path else None
        drag_mode = bool(overlay_cfg.get("dragMode"))
        layout_key = (
            overlay_cfg.get("position"),
            bool(overlay_cfg.get("customPosition")),
            overlay_cfg.get("customX"),
            overlay_cfg.get("customY"),
            int(overlay_cfg.get("margin") or 24),
            float(overlay_cfg.get("sizePercent") or 30),
            float(overlay_cfg.get("opacity") or 0.7),
        )

        if (
            self.window is not None
            and self.window.winfo_exists()
            and (
                force_recreate
                or desired_image_path != self.last_image_path
                or drag_mode != self.last_drag_mode
                or layout_key != self.last_layout_key
            )
        ):
            self.close()

        _screen_x, _screen_y, screen_w, screen_h = self.screen_bounds()
        max_size = max(160, int(min(screen_w, screen_h) * float(overlay_cfg.get("sizePercent") or 30) / 100))
        pad = 6 if drag_mode else 0
        bg = self.DRAG_BG if drag_mode else self.NORMAL_BG
        display_image = None
        if image_path:
            try:
                display_image = Image.open(image_path).convert("RGB")
                display_image.thumbnail((max_size - pad * 2, max_size - pad * 2), Image.Resampling.LANCZOS)
            except Exception:
                display_image = None
                self.last_error = f"Could not load overlay image: {image_path}"

        if not display_image and not drag_mode:
            self.photo = None
            self.last_image_path = None
            self.close()
            return

        if self.window is None or not self.window.winfo_exists():
            self.window = Toplevel()
            self.window.overrideredirect(True)
            self.window.withdraw()
            self.window.attributes("-topmost", True)
            self.window.attributes("-alpha", float(overlay_cfg.get("opacity") or 0.7))
            self.window.configure(bg=bg)
            self.label = Canvas(self.window, bg=bg, bd=0, highlightthickness=0, relief="flat")
            self.label.pack(fill=BOTH, expand=True)
        else:
            self.window.configure(bg=bg)
            if self.label is None or not self.label.winfo_exists():
                self.label = Canvas(self.window, bg=bg, bd=0, highlightthickness=0, relief="flat")
                self.label.pack(fill=BOTH, expand=True)
            else:
                self.label.configure(bg=bg, bd=0, highlightthickness=0)

        try:
            self.window.attributes("-disabled", False)
        except Exception:
            pass
        self.apply_window_transparency(drag_mode, bg)
        self.last_drag_mode = drag_mode
        self.last_layout_key = layout_key
        if display_image:
            window_w = display_image.width + pad * 2
            window_h = display_image.height + pad * 2
        else:
            window_w = max_size
            window_h = max_size
        x, y = self.corner_position(overlay_cfg, window_w, window_h)
        self.window.geometry(f"{window_w}x{window_h}+{x}+{y}")
        self.window.attributes("-alpha", float(overlay_cfg.get("opacity") or 0.7))

        if display_image:
            self.photo = ImageTk.PhotoImage(display_image)
            self.last_image_path = str(image_path)
            self.label.delete("all")
            self.label.create_image(pad, pad, image=self.photo, anchor="nw")
        else:
            self.photo = None
            self.last_image_path = None
            self.label.delete("all")
            self.label.create_text(
                window_w // 2,
                window_h // 2,
                text=display_name or "No map selected",
                fill="#ffffff",
                font=("Segoe UI", 10, "bold"),
            )

        self.window.deiconify()
        self.root.update_idletasks()
        self.window.lift()
        self.window.attributes("-topmost", True)
        self.label.update_idletasks()
        self.window.update_idletasks()
        if display_image and os.name == "nt" and not drag_mode:
            self.render_native_layered(display_image.convert("RGBA"), x, y, float(overlay_cfg.get("opacity") or 0.7))
        if drag_mode:
            self.enable_drag_mode()
        else:
            self.disable_drag_bindings()
            self.make_clickthrough()
            self.root.after(150, self.make_clickthrough)
            self.root.after(500, self.make_clickthrough)
            self.root.after(1200, self.make_clickthrough)

    def render_native_layered(self, image, x, y, opacity):
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            hwnd = self.window.winfo_id()
            width, height = image.size
            alpha = max(0, min(255, int(float(opacity) * 255)))
            gwl_exstyle = -20
            ws_ex_layered = 0x00080000
            ws_ex_toolwindow = 0x00000080
            ws_ex_noactivate = 0x08000000
            style = user32.GetWindowLongW(hwnd, gwl_exstyle)
            user32.SetWindowLongW(hwnd, gwl_exstyle, style | ws_ex_layered | ws_ex_toolwindow | ws_ex_noactivate)

            rgba = image.convert("RGBA")
            raw = bytearray(rgba.tobytes("raw", "BGRA"))
            for index in range(0, len(raw), 4):
                raw[index] = raw[index] * raw[index + 3] // 255
                raw[index + 1] = raw[index + 1] * raw[index + 3] // 255
                raw[index + 2] = raw[index + 2] * raw[index + 3] // 255

            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            class SIZE(ctypes.Structure):
                _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

            class BLENDFUNCTION(ctypes.Structure):
                _fields_ = [
                    ("BlendOp", ctypes.c_byte),
                    ("BlendFlags", ctypes.c_byte),
                    ("SourceConstantAlpha", ctypes.c_byte),
                    ("AlphaFormat", ctypes.c_byte),
                ]

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", wintypes.DWORD),
                    ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD),
                ]

            class BITMAPINFO(ctypes.Structure):
                _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

            BI_RGB = 0
            DIB_RGB_COLORS = 0
            ULW_ALPHA = 0x00000002
            AC_SRC_OVER = 0x00
            AC_SRC_ALPHA = 0x01

            hdc_screen = user32.GetDC(None)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            bits = ctypes.c_void_p()
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = BI_RGB
            bitmap = gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
            if not bitmap:
                return
            ctypes.memmove(bits, bytes(raw), len(raw))
            old_bitmap = gdi32.SelectObject(hdc_mem, bitmap)
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, alpha, AC_SRC_ALPHA)
            user32.UpdateLayeredWindow(
                hwnd,
                hdc_screen,
                ctypes.byref(POINT(x, y)),
                ctypes.byref(SIZE(width, height)),
                hdc_mem,
                ctypes.byref(POINT(0, 0)),
                0,
                ctypes.byref(blend),
                ULW_ALPHA,
            )
            hwnd_topmost = -1
            swp_noactivate = 0x0010
            swp_showwindow = 0x0040
            user32.SetWindowPos(hwnd, hwnd_topmost, x, y, width, height, swp_noactivate | swp_showwindow)
            gdi32.SelectObject(hdc_mem, old_bitmap)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(None, hdc_screen)
        except Exception as exc:
            self.last_error = f"Could not paint native overlay: {exc}"

    def disable_drag_bindings(self):
        if not self.window or not self.window.winfo_exists():
            return
        for widget in (self.window, self.label):
            if widget:
                widget.unbind("<ButtonPress-1>")
                widget.unbind("<B1-Motion>")
                widget.unbind("<ButtonRelease-1>")
                try:
                    widget.configure(cursor="")
                except Exception:
                    pass
        self.drag_start = None

    def enable_drag_mode(self):
        if not self.window or not self.window.winfo_exists():
            return
        self.remove_clickthrough_styles()
        for widget in (self.window, self.label):
            if widget:
                widget.bind("<ButtonPress-1>", self.begin_drag)
                widget.bind("<B1-Motion>", self.drag_overlay)
                widget.bind("<ButtonRelease-1>", self.finish_drag)
                try:
                    widget.configure(cursor="fleur")
                except Exception:
                    pass

    def begin_drag(self, event):
        overlay_cfg = self.cfg.get("overlay") or {}
        if not overlay_cfg.get("dragMode"):
            return "break"
        self.drag_start = {
            "mouse_x": event.x_root,
            "mouse_y": event.y_root,
            "x": self.window.winfo_x(),
            "y": self.window.winfo_y(),
        }
        return "break"

    def drag_overlay(self, event):
        overlay_cfg = self.cfg.get("overlay") or {}
        if not overlay_cfg.get("dragMode") or not self.drag_start:
            return "break"
        x = self.drag_start["x"] + event.x_root - self.drag_start["mouse_x"]
        y = self.drag_start["y"] + event.y_root - self.drag_start["mouse_y"]
        self.window.geometry(f"+{x}+{y}")
        overlay_cfg["customPosition"] = True
        overlay_cfg["customX"] = x
        overlay_cfg["customY"] = y
        return "break"

    def finish_drag(self, _event):
        if self.drag_start:
            save_config(self.cfg, force_overlay=True)
        self.drag_start = None
        return "break"

    def overlay_hwnds(self):
        hwnds = []
        for widget in (self.window, self.label):
            if widget and widget.winfo_exists():
                hwnd = widget.winfo_id()
                if hwnd and hwnd not in hwnds:
                    hwnds.append(hwnd)
        return hwnds

    def make_clickthrough(self):
        if not self.window or not self.window.winfo_exists() or os.name != "nt":
            return
        if (self.cfg.get("overlay") or {}).get("dragMode"):
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            for hwnd in self.overlay_hwnds():
                self.install_clickthrough_hit_test(user32, hwnd)
                self.apply_clickthrough_style_to_overlay(user32, hwnd)
        except Exception:
            pass

    def set_overlay_hwnd_enabled(self, user32, hwnd, enabled):
        try:
            user32.EnableWindow(hwnd, bool(enabled))
        except Exception:
            pass

    def apply_clickthrough_style_to_overlay(self, user32, hwnd):
        try:
            gwl_exstyle = -20
            ws_ex_layered = 0x00080000
            ws_ex_transparent = 0x00000020
            ws_ex_toolwindow = 0x00000080
            ws_ex_noactivate = 0x08000000
            swp_framechanged = 0x0020
            style = user32.GetWindowLongW(hwnd, gwl_exstyle)
            user32.SetWindowLongW(
                hwnd,
                gwl_exstyle,
                style | ws_ex_layered | ws_ex_transparent | ws_ex_toolwindow | ws_ex_noactivate,
            )
            hwnd_topmost = -1
            swp_nosize = 0x0001
            swp_nomove = 0x0002
            swp_noactivate = 0x0010
            swp_showwindow = 0x0040
            user32.SetWindowPos(
                hwnd,
                hwnd_topmost,
                0,
                0,
                0,
                0,
                swp_nomove | swp_nosize | swp_noactivate | swp_showwindow | swp_framechanged,
            )
        except Exception:
            pass

    def remove_clickthrough_styles(self):
        if not self.window or not self.window.winfo_exists() or os.name != "nt":
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            gwl_exstyle = -20
            ws_ex_transparent = 0x00000020
            ws_ex_noactivate = 0x08000000
            swp_framechanged = 0x0020
            for hwnd in self.overlay_hwnds():
                self.set_overlay_hwnd_enabled(user32, hwnd, True)
                style = user32.GetWindowLongW(hwnd, gwl_exstyle)
                user32.SetWindowLongW(hwnd, gwl_exstyle, style & ~ws_ex_transparent & ~ws_ex_noactivate)
                user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040 | swp_framechanged)
        except Exception:
            pass

    def install_clickthrough_hit_test(self, user32, hwnd):
        if hwnd in self.clickthrough_procs:
            return
        try:
            import ctypes
            from ctypes import wintypes
            wm_nchittest = 0x0084
            wm_mouseactivate = 0x0021
            httransparent = -1
            ma_noactivate = 3
            gwlp_wndproc = -4
            wndproc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
            set_window_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            call_window_proc = user32.CallWindowProcW
            set_window_long.restype = ctypes.c_ssize_t
            call_window_proc.restype = ctypes.c_ssize_t
            original = {"value": None}

            @wndproc_type
            def wndproc(window, message, wparam, lparam):
                if message == wm_nchittest:
                    return httransparent
                if message == wm_mouseactivate:
                    return ma_noactivate
                if not original["value"]:
                    return 0
                return call_window_proc(original["value"], window, message, wparam, lparam)

            previous = set_window_long(hwnd, gwlp_wndproc, ctypes.cast(wndproc, ctypes.c_void_p).value)
            original["value"] = previous
            self.clickthrough_hwnd = hwnd
            self.clickthrough_procs[hwnd] = wndproc
            self.original_wndproc = previous
        except Exception:
            pass

    def close(self):
        if self.window and self.window.winfo_exists():
            self.remove_clickthrough_styles()
            self.window.destroy()
        self.window = None
        self.clickthrough_hwnd = None
        self.clickthrough_procs = {}
        self.original_wndproc = None
        self.last_layout_key = None


class SkillDebugOverlay:
    def __init__(self, root, cfg):
        self.root = root
        self.cfg = cfg
        self.window = None
        self.last_error = ""

    def update(self, box, rgba_bytes, width, height):
        skill_cfg = self.cfg.get("skillCheck") or {}
        if not skill_cfg.get("screenDebugOverlay"):
            self.close()
            return
        if not box or not rgba_bytes or width <= 0 or height <= 0:
            self.close()
            return
        try:
            x = int(box["x"])
            y = int(box["y"])
            width = int(width)
            height = int(height)
            image = Image.frombytes("RGBA", (width, height), rgba_bytes)
            if self.window is None or not self.window.winfo_exists():
                self.window = Toplevel()
                self.window.overrideredirect(True)
                self.window.withdraw()
                self.window.attributes("-topmost", True)
                self.window.configure(bg="#000000")
            self.window.geometry(f"{width}x{height}+{x}+{y}")
            self.window.deiconify()
            self.window.lift()
            self.window.attributes("-topmost", True)
            self.root.update_idletasks()
            self.window.update_idletasks()
            self.render_native_layered(image, x, y)
            self.make_clickthrough()
        except Exception as exc:
            self.last_error = f"Could not update skill debug overlay: {exc}"

    def render_native_layered(self, image, x, y):
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        hwnd = self.window.winfo_id()
        width, height = image.size
        gwl_exstyle = -20
        ws_ex_layered = 0x00080000
        ws_ex_toolwindow = 0x00000080
        ws_ex_noactivate = 0x08000000
        style = user32.GetWindowLongW(hwnd, gwl_exstyle)
        user32.SetWindowLongW(hwnd, gwl_exstyle, style | ws_ex_layered | ws_ex_toolwindow | ws_ex_noactivate)

        raw = bytearray(image.convert("RGBA").tobytes("raw", "BGRA"))
        for index in range(0, len(raw), 4):
            raw[index] = raw[index] * raw[index + 3] // 255
            raw[index + 1] = raw[index + 1] * raw[index + 3] // 255
            raw[index + 2] = raw[index + 2] * raw[index + 3] // 255

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class SIZE(ctypes.Structure):
            _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [
                ("BlendOp", ctypes.c_byte),
                ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte),
                ("AlphaFormat", ctypes.c_byte),
            ]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

        hdc_screen = user32.GetDC(None)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        bits = ctypes.c_void_p()
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        bitmap = gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        if not bitmap:
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(None, hdc_screen)
            return
        ctypes.memmove(bits, bytes(raw), len(raw))
        old_bitmap = gdi32.SelectObject(hdc_mem, bitmap)
        blend = BLENDFUNCTION(0, 0, 255, 1)
        user32.UpdateLayeredWindow(
            hwnd,
            hdc_screen,
            ctypes.byref(POINT(x, y)),
            ctypes.byref(SIZE(width, height)),
            hdc_mem,
            ctypes.byref(POINT(0, 0)),
            0,
            ctypes.byref(blend),
            0x00000002,
        )
        gdi32.SelectObject(hdc_mem, old_bitmap)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_screen)

    def make_clickthrough(self):
        if not self.window or not self.window.winfo_exists() or os.name != "nt":
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = self.window.winfo_id()
            self.exclude_from_capture(user32, hwnd)
            gwl_exstyle = -20
            ws_ex_transparent = 0x00000020
            ws_ex_toolwindow = 0x00000080
            ws_ex_noactivate = 0x08000000
            style = user32.GetWindowLongW(hwnd, gwl_exstyle)
            user32.SetWindowLongW(hwnd, gwl_exstyle, style | ws_ex_transparent | ws_ex_toolwindow | ws_ex_noactivate)
            try:
                user32.EnableWindow(hwnd, False)
            except Exception:
                pass
        except Exception:
            pass

    def exclude_from_capture(self, user32, hwnd):
        try:
            # Windows 10 2004+: hide this diagnostic overlay from screen capture.
            if not user32.SetWindowDisplayAffinity(hwnd, 0x00000011):
                user32.SetWindowDisplayAffinity(hwnd, 0x00000001)
        except Exception:
            pass

    def close(self):
        if self.window and self.window.winfo_exists():
            try:
                self.window.destroy()
            except Exception:
                pass
        self.window = None


class App:
    COLORS = {
        "bg": "#10100f",
        "nav": "#15120f",
        "panel": "#1d1b18",
        "panel2": "#131313",
        "panel3": "#2a2621",
        "line": "#3a342c",
        "text": "#f7f1e8",
        "muted": "#b0a79b",
        "accent": "#d83a34",
        "accent2": "#2fc18c",
        "warn": "#e2b75a",
        "danger": "#ef5d64",
        "button": "#2a2621",
        "button_hover": "#3a332b",
    }

    def __init__(self):
        self.cfg = load_config()
        save_config(self.cfg)
        self.events = queue.Queue()
        self.detector = Detector(self.cfg, self.events.put)
        self.skill_detector = SkillCheckDetector(self.cfg, self.events.put)
        self.auto_sprint = AutoSprintController(self.cfg, self.events.put)
        self.current_match = None
        self.map_library_entries = build_map_library_entries()
        self.selected_map_name = self.map_library_entries[0]["name"] if self.map_library_entries else None
        self.selected_image_paths = []
        self.selected_image_index = 0
        self.map_photo = None
        self.installing_ocr = False
        self.last_overlay_log = ""
        self.suppress_overlay_updates = False
        self.area_selector_open = False
        self.selector_photo = None
        self.auto_sprint_mode = "off"

        self.root = Tk()
        self.root.title("DBD Overlay Assistant")
        self.root.geometry("1180x780")
        self.root.minsize(1040, 700)
        self.root.configure(bg=self.COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.map_enabled_var = BooleanVar(value=bool(self.cfg.get("mapDetectorEnabled")))
        self.skill_enabled_var = BooleanVar(value=bool((self.cfg.get("skillCheck") or {}).get("enabled")))
        auto_sprint_cfg = self.cfg.get("autoSprint") or {}
        self.auto_sprint_enabled_var = BooleanVar(value=bool(auto_sprint_cfg.get("enabled")))
        self.auto_sprint_dbd_only_var = BooleanVar(value=bool(auto_sprint_cfg.get("dbdOnly", True)))
        overlay_cfg = self.cfg.get("overlay") or {}
        self.overlay_enabled_var = BooleanVar(value=bool(overlay_cfg.get("enabled")))
        self.overlay_drag_var = BooleanVar(value=bool(overlay_cfg.get("dragMode")))
        self.configure_style()
        self.build_ui()

        self.overlay = MapOverlay(self.root, self.cfg)
        self.skill_debug_overlay = SkillDebugOverlay(self.root, self.cfg)
        self.render_map_view()
        self.update_overlay()
        self.render_overlay_state()
        self.render_home_state()
        if bool((self.cfg.get("autoSprint") or {}).get("enabled")):
            self.auto_sprint.start()
        self.log("Using fast Python region capture. Full-screen screenshots are not used while watching.")
        self.log(f"Trigger polling: {self.cfg['scanMs']} ms search, {self.cfg['triggerSeenScanMs']} ms disappearance check.")
        if self.detector.tesseract:
            self.log(f"OCR engine: native Tesseract at {self.detector.tesseract}")
        else:
            if os.environ.get("DBD_SKIP_OCR_AUTO_INSTALL") == "1":
                self.log("OCR engine not found. Automatic install skipped for this run.")
            else:
                self.log("OCR engine not found. Starting automatic Tesseract install in the background.")
                self.ensure_ocr_installed_async()

        self.root.after(50, self.process_events)

    def configure_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TNotebook", background=self.COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background="#192231", foreground=self.COLORS["muted"], padding=(18, 9), borderwidth=0, font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", self.COLORS["panel"])], foreground=[("selected", self.COLORS["text"])])
        style.configure("Horizontal.TScale", background=self.COLORS["panel"], troughcolor=self.COLORS["panel2"])

    def build_ui(self):
        shell = Frame(self.root, bg=self.COLORS["bg"])
        shell.pack(fill=BOTH, expand=True)

        sidebar = Frame(shell, bg=self.COLORS["nav"], width=230)
        sidebar.pack(side=LEFT, fill=Y)
        sidebar.pack_propagate(False)

        main = Frame(shell, bg=self.COLORS["bg"])
        main.pack(side=LEFT, fill=BOTH, expand=True)

        brand = Frame(sidebar, bg=self.COLORS["nav"], padx=18, pady=20)
        brand.pack(fill="x")
        Label(
            brand,
            text="DBD",
            bg=self.COLORS["nav"],
            fg=self.COLORS["accent"],
            font=("Segoe UI", 25, "bold"),
        ).pack(anchor="w")
        Label(
            brand,
            text="Player Tools",
            bg=self.COLORS["nav"],
            fg=self.COLORS["text"],
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        Label(
            brand,
            text="Quick toggles, clean setup, and advanced tuning when you need it.",
            bg=self.COLORS["nav"],
            fg=self.COLORS["muted"],
            wraplength=180,
            justify="left",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(6, 0))

        self.content = Frame(main, bg=self.COLORS["bg"], padx=22, pady=20)
        self.content.pack(fill=BOTH, expand=True)

        self.home_tab = Frame(self.content, bg=self.COLORS["bg"])
        self.detector_tab = Frame(self.content, bg=self.COLORS["bg"])
        self.skill_tab = Frame(self.content, bg=self.COLORS["bg"])
        self.auto_sprint_tab = Frame(self.content, bg=self.COLORS["bg"])
        self.map_tab = Frame(self.content, bg=self.COLORS["bg"])
        self.overlay_tab = Frame(self.content, bg=self.COLORS["bg"])
        self.timing_tab = Frame(self.content, bg=self.COLORS["bg"])
        self.screens = [
            self.home_tab,
            self.detector_tab,
            self.skill_tab,
            self.auto_sprint_tab,
            self.map_tab,
            self.overlay_tab,
            self.timing_tab,
        ]

        nav = Frame(sidebar, bg=self.COLORS["nav"], padx=12)
        nav.pack(fill="x", pady=(12, 0))
        self.nav_buttons = {}
        self.nav_button(nav, "Home", self.home_tab).pack(fill="x", pady=(0, 8))
        self.nav_button(nav, "Setup", self.detector_tab).pack(fill="x", pady=(0, 8))
        self.nav_button(nav, "Skill Monitor", self.skill_tab).pack(fill="x", pady=(0, 8))
        self.nav_button(nav, "Auto Sprint", self.auto_sprint_tab).pack(fill="x", pady=(0, 8))
        self.nav_button(nav, "Maps", self.map_tab).pack(fill="x", pady=(0, 8))
        self.nav_button(nav, "Overlay", self.overlay_tab).pack(fill="x", pady=(0, 8))
        self.nav_button(nav, "Settings", self.timing_tab).pack(fill="x", pady=(0, 8))

        sidebar_status = Frame(sidebar, bg=self.COLORS["nav"], padx=18, pady=12)
        sidebar_status.pack(side="bottom", fill="x")
        Label(sidebar_status, text="LIVE STATUS", bg=self.COLORS["nav"], fg=self.COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 8))
        self.run_pill = self.pill(sidebar_status, "Map: off", "stop")
        self.run_pill.pack(fill="x", pady=(0, 8))
        self.skill_global_pill = self.pill(sidebar_status, "Skill: off", "stop")
        self.skill_global_pill.pack(fill="x", pady=(0, 8))
        self.auto_sprint_global_pill = self.pill(sidebar_status, "Sprint: off", "stop")
        self.auto_sprint_global_pill.pack(fill="x")

        self.build_home_tab()
        self.build_detector_tab()
        self.build_skill_tab()
        self.build_auto_sprint_tab()
        self.build_map_tab()
        self.build_overlay_tab()
        self.build_timing_tab()
        self.show_screen(self.home_tab)

    def build_home_tab(self):
        body = self.scroll_body(self.home_tab)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(2, weight=1)
        body.grid_rowconfigure(2, weight=1)

        hero = Frame(body, bg="#211915", highlightthickness=1, highlightbackground="#593128", padx=24, pady=20)
        hero.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 18))
        Label(hero, text="Home", bg="#211915", fg=self.COLORS["text"], font=("Segoe UI", 28, "bold")).pack(anchor="w")
        Label(
            hero,
            text="Start what you need, confirm what is active, and keep the deeper tuning out of the way.",
            bg="#211915",
            fg=self.COLORS["muted"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        map_card = self.feature_card(body, "Map Detector", "Automatically reads the map when your trigger appears.")
        map_card.grid(row=1, column=0, sticky="nsew", padx=(0, 9), pady=(0, 18))
        self.home_map_status = self.feature_state(map_card, "Off")
        self.home_map_detail = self.feature_detail(map_card)
        self.check_toggle(map_card, "Map detector enabled", self.map_enabled_var, self.set_map_from_toggle).pack(fill="x", pady=(0, 10))
        self.link_button(map_card, "Set trigger and text areas", lambda: self.show_screen(self.detector_tab)).pack(anchor="w")

        skill_card = self.feature_card(body, "Skill Monitor", "Watches the skill-check ring and sends your input.")
        skill_card.grid(row=1, column=1, sticky="nsew", padx=9, pady=(0, 18))
        self.home_skill_status = self.feature_state(skill_card, "Off")
        self.home_skill_detail = self.feature_detail(skill_card)
        self.check_toggle(skill_card, "Skill assist enabled", self.skill_enabled_var, self.set_skill_from_toggle).pack(fill="x", pady=(0, 10))
        self.link_button(skill_card, "Open live monitor", lambda: self.show_screen(self.skill_tab)).pack(anchor="w")

        overlay_card = self.feature_card(body, "Map Overlay", "Shows the selected or detected map as a click-through overlay.")
        overlay_card.grid(row=1, column=2, sticky="nsew", padx=(9, 0), pady=(0, 18))
        self.home_overlay_status = self.feature_detail(overlay_card, lines=4)
        self.check_toggle(overlay_card, "Map overlay enabled", self.overlay_enabled_var, self.set_overlay_from_toggle).pack(fill="x", pady=(0, 8))
        self.check_toggle(overlay_card, "Drag mode", self.overlay_drag_var, self.set_overlay_drag_from_toggle).pack(fill="x", pady=(0, 10))
        self.link_button(overlay_card, "Position overlay", lambda: self.show_screen(self.overlay_tab)).pack(anchor="w")

        sprint_card = self.feature_card(body, "Auto Sprint", "Keeps Shift held while DBD is focused; hold Shift to walk.")
        sprint_card.grid(row=2, column=0, sticky="nsew", padx=(0, 9))
        self.home_auto_sprint_status = self.feature_state(sprint_card, "Off")
        self.home_auto_sprint_detail = self.feature_detail(sprint_card, lines=3)
        self.check_toggle(sprint_card, "Auto sprint enabled", self.auto_sprint_enabled_var, self.set_auto_sprint_from_toggle).pack(fill="x", pady=(0, 8))
        self.link_button(sprint_card, "Open auto sprint settings", lambda: self.show_screen(self.auto_sprint_tab)).pack(anchor="w")

        current_card = self.card(body)
        current_card.grid(row=2, column=1, sticky="nsew", padx=9)
        self.card_title(current_card, "Current Map")
        self.home_current_map = Label(current_card, text="None", bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Segoe UI", 18, "bold"), anchor="w", justify="left")
        self.home_current_map.pack(fill="x", pady=(10, 6))
        self.home_current_map_detail = Label(current_card, text="", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 10), anchor="w", justify="left")
        self.home_current_map_detail.pack(fill="x")
        self.link_button(current_card, "Open map library", lambda: self.show_screen(self.map_tab)).pack(anchor="w", pady=(14, 0))

        activity_card = self.card(body)
        activity_card.grid(row=2, column=2, sticky="nsew", padx=(9, 0))
        self.card_title(activity_card, "Session Feed")
        self.home_activity = Text(
            activity_card,
            height=8,
            wrap="word",
            bg=self.COLORS["panel2"],
            fg=self.COLORS["muted"],
            insertbackground=self.COLORS["text"],
            relief="flat",
            padx=10,
            pady=10,
            font=("Consolas", 9),
        )
        self.home_activity.pack(fill=BOTH, expand=True, pady=(8, 0))
        self.home_activity.configure(state="disabled")
        self.render_home_state()

    def nav_button(self, parent, text, screen):
        button = Button(
            parent,
            text=text,
            command=lambda: self.show_screen(screen),
            anchor="w",
            bg=self.COLORS["nav"],
            fg=self.COLORS["muted"],
            activebackground=self.COLORS["panel3"],
            activeforeground=self.COLORS["text"],
            relief="flat",
            bd=0,
            padx=14,
            pady=12,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
        )
        self.nav_buttons[screen] = button
        return button

    def show_screen(self, screen):
        for frame in getattr(self, "screens", []):
            frame.pack_forget()
        screen.pack(fill=BOTH, expand=True)
        for frame, button in getattr(self, "nav_buttons", {}).items():
            active = frame == screen
            button.configure(
                bg=self.COLORS["panel3"] if active else self.COLORS["nav"],
                fg=self.COLORS["text"] if active else self.COLORS["muted"],
            )

    def scroll_body(self, parent):
        canvas = Canvas(parent, bg=self.COLORS["bg"], highlightthickness=0, bd=0)
        scrollbar = Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        body = Frame(canvas, bg=self.COLORS["bg"])
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")

        def on_body_configure(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(event):
            canvas.itemconfigure(window_id, width=event.width)

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def bind_mousewheel(_event=None):
            canvas.bind_all("<MouseWheel>", on_mousewheel)

        def unbind_mousewheel(_event=None):
            canvas.unbind_all("<MouseWheel>")

        body.bind("<Configure>", on_body_configure)
        canvas.bind("<Configure>", on_canvas_configure)
        parent.bind("<Enter>", bind_mousewheel)
        parent.bind("<Leave>", unbind_mousewheel)
        return body

    def feature_card(self, parent, title, text):
        frame = self.card(parent)
        Label(frame, text=title, bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Segoe UI", 15, "bold"), anchor="w").pack(fill="x")
        Label(frame, text=text, bg=self.COLORS["panel"], fg=self.COLORS["muted"], wraplength=180, justify="left", anchor="w", font=("Segoe UI", 9)).pack(fill="x", pady=(5, 14))
        return frame

    def feature_state(self, parent, text):
        label = Label(parent, text=text, bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Segoe UI", 20, "bold"), anchor="w")
        label.pack(fill="x", pady=(0, 8))
        return label

    def feature_detail(self, parent, lines=2):
        label = Label(parent, text="", bg=self.COLORS["panel"], fg=self.COLORS["muted"], height=lines, font=("Segoe UI", 9), anchor="nw", justify="left")
        label.pack(fill="x", pady=(0, 12))
        return label

    def check_toggle(self, parent, text, variable, command):
        return Checkbutton(
            parent,
            text=text,
            variable=variable,
            command=command,
            bg=self.COLORS["panel"],
            fg=self.COLORS["text"],
            activebackground=self.COLORS["panel"],
            activeforeground=self.COLORS["text"],
            selectcolor=self.COLORS["panel2"],
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
            anchor="w",
            padx=0,
            pady=3,
        )

    def link_button(self, parent, text, command):
        return Button(
            parent,
            text=text,
            command=command,
            anchor="w",
            bg=self.COLORS["panel"],
            fg=self.COLORS["accent"],
            activebackground=self.COLORS["panel"],
            activeforeground=self.COLORS["text"],
            relief="flat",
            bd=0,
            padx=0,
            pady=4,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
        )

    def set_map_from_toggle(self):
        if self.map_enabled_var.get():
            self.start_detection()
        else:
            self.stop_detection()

    def set_skill_from_toggle(self):
        if self.skill_enabled_var.get():
            self.start_skill_checks()
        else:
            self.stop_skill_checks()

    def set_auto_sprint_from_toggle(self):
        if self.auto_sprint_enabled_var.get():
            self.start_auto_sprint()
        else:
            self.stop_auto_sprint()

    def set_auto_sprint_scope_from_toggle(self):
        self.cfg["autoSprint"]["dbdOnly"] = bool(self.auto_sprint_dbd_only_var.get())
        save_config(self.cfg)
        self.auto_sprint.update_shift_state()
        self.render_home_state()

    def set_overlay_from_toggle(self):
        desired = bool(self.overlay_enabled_var.get())
        if bool(self.cfg["overlay"].get("enabled")) != desired:
            self.cfg["overlay"]["enabled"] = desired
            save_config(self.cfg, force_overlay=True)
            self.update_overlay()
            self.render_overlay_state()
            self.render_home_state()

    def set_overlay_drag_from_toggle(self):
        desired = bool(self.overlay_drag_var.get())
        if bool(self.cfg["overlay"].get("dragMode")) != desired:
            self.cfg["overlay"]["dragMode"] = desired
            save_config(self.cfg, force_overlay=True)
            self.update_overlay()
            self.render_overlay_state()
            self.render_home_state()

    def build_detector_tab(self):
        grid = self.scroll_body(self.detector_tab)
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)
        grid.grid_rowconfigure(1, weight=1)

        setup_card = self.card(grid)
        setup_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 12))
        self.card_title(setup_card, "Capture Setup")
        self.boxes = Label(setup_card, text=self.box_summary(), anchor="w", justify="left", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Consolas", 9))
        self.boxes.pack(fill="x", pady=(10, 14))
        actions = Frame(setup_card, bg=self.COLORS["panel"])
        actions.pack(fill="x")
        self.button(actions, "Trigger Area", lambda: self.select_area("trigger"), "primary").pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.button(actions, "Text Area", lambda: self.select_area("text")).pack(side="left", fill="x", expand=True, padx=6)
        self.button(actions, "Recapture", lambda: self.select_area("trigger")).pack(side="left", fill="x", expand=True, padx=(6, 0))

        status_card = self.card(grid)
        status_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=(0, 12))
        self.card_title(status_card, "Detector Status")
        self.check_toggle(status_card, "Map detector enabled", self.map_enabled_var, self.set_map_from_toggle).pack(fill="x", pady=(10, 12))
        self.status = Label(status_card, text="Ready.", anchor="w", bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Segoe UI", 16, "bold"))
        self.status.pack(fill="x", pady=(0, 8))
        self.score = Label(status_card, text="No trigger score yet.", anchor="w", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Consolas", 10))
        self.score.pack(fill="x")

        ocr_card = self.card(grid)
        ocr_card.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        self.card_title(ocr_card, "Detected Text")
        self.ocr = Text(
            ocr_card,
            height=8,
            wrap="word",
            bg=self.COLORS["panel2"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["text"],
            relief="flat",
            padx=12,
            pady=10,
            font=("Consolas", 10),
        )
        self.ocr.pack(fill=BOTH, expand=True, pady=(8, 0))
        self.set_text(self.ocr, "No OCR yet.")

        log_card = self.card(grid)
        log_card.grid(row=1, column=1, sticky="nsew", padx=(10, 0))
        self.card_title(log_card, "Session Feed")
        self.log_box = Text(
            log_card,
            height=12,
            wrap="word",
            bg=self.COLORS["panel2"],
            fg=self.COLORS["muted"],
            insertbackground=self.COLORS["text"],
            relief="flat",
            padx=10,
            pady=10,
            font=("Consolas", 9),
        )
        self.log_box.pack(fill=BOTH, expand=True, pady=(8, 0))
        self.log_box.configure(state="disabled")

    def build_skill_tab(self):
        body = self.scroll_body(self.skill_tab)
        body.grid_columnconfigure(0, weight=2)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        state = self.card(body)
        state.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.card_title(state, "Live Skill Monitor")
        self.check_toggle(state, "Skill assist enabled", self.skill_enabled_var, self.set_skill_from_toggle).pack(fill="x", pady=(10, 10))
        self.skill_preview_photo = None
        self.skill_preview = Label(state, text="Live preview will appear while watching.", bg=self.COLORS["panel2"], fg=self.COLORS["muted"], font=("Segoe UI", 10), compound="center")
        self.skill_preview.pack(fill=BOTH, expand=True, pady=(0, 8))
        self.skill_preview_legend = Label(
            state,
            text="Preview: cyan outline = detected marker, yellow outline = press target, orange = red marker, magenta = red inside target.",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.skill_preview_legend.pack(fill="x", pady=(6, 0))

        side = Frame(body, bg=self.COLORS["bg"])
        side.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        side.grid_rowconfigure(1, weight=1)

        status = self.card(side)
        status.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.card_title(status, "Now")
        self.skill_pill = self.pill(status, "Stopped", "stop")
        self.skill_pill.pack(fill="x", pady=(10, 8))
        self.skill_status = Label(status, text="Ready.", anchor="w", bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Segoe UI", 14, "bold"), justify="left", wraplength=280)
        self.skill_status.pack(fill="x", pady=(0, 8))
        self.skill_score = Label(status, text="No scan yet.", anchor="w", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Consolas", 10), justify="left", wraplength=280)
        self.skill_score.pack(fill="x")
        now_row = Frame(status, bg=self.COLORS["panel"])
        now_row.pack(fill="x", pady=(12, 0))
        self.skill_white_pill = self.pill(now_row, "White: no", "stop")
        self.skill_white_pill.pack(fill="x", pady=(0, 6))
        self.skill_zone_pill = self.pill(now_row, "Markers: 0", "stop")
        self.skill_zone_pill.pack(fill="x", pady=(0, 6))
        self.skill_red_pill = self.pill(now_row, "Red in zone: no", "stop")
        self.skill_red_pill.pack(fill="x", pady=(0, 6))
        self.skill_hit_pill = self.pill(now_row, "Hit: no", "stop")
        self.skill_hit_pill.pack(fill="x")

        setup = self.card(side)
        setup.grid(row=1, column=0, sticky="nsew")
        self.card_title(setup, "Skill Area")
        self.skill_box_label = Label(setup, text=self.skill_box_summary(), anchor="w", justify="left", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Consolas", 9))
        self.skill_box_label.pack(fill="x", pady=(10, 14))
        self.button(setup, "Select Skill Area", lambda: self.select_area("skill", frozen=True), "primary").pack(fill="x", pady=(0, 10))
        self.link_button(setup, "Tune skill detection in Settings", lambda: self.show_screen(self.timing_tab)).pack(anchor="w")

    def build_auto_sprint_tab(self):
        body = self.scroll_body(self.auto_sprint_tab)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        main = self.card(body)
        main.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 12))
        self.card_title(main, "Auto Sprint")
        self.auto_sprint_status = Label(main, text="Off", bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Segoe UI", 22, "bold"), anchor="w")
        self.auto_sprint_status.pack(fill="x", pady=(10, 6))
        self.auto_sprint_detail = Label(
            main,
            text="Shift is held for sprint. Hold Shift yourself to walk.",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            justify="left",
            wraplength=420,
            font=("Segoe UI", 11),
        )
        self.auto_sprint_detail.pack(fill="x", pady=(0, 18))
        self.check_toggle(main, "Auto sprint enabled", self.auto_sprint_enabled_var, self.set_auto_sprint_from_toggle).pack(fill="x", pady=(0, 10))
        self.check_toggle(main, "Only while Dead by Daylight is focused", self.auto_sprint_dbd_only_var, self.set_auto_sprint_scope_from_toggle).pack(fill="x", pady=(0, 14))

        controls = Frame(main, bg=self.COLORS["panel"])
        controls.pack(fill="x")
        self.button(controls, "Enable", self.start_auto_sprint, "primary").pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.button(controls, "Disable", self.stop_auto_sprint, "danger").pack(side="left", fill="x", expand=True, padx=(6, 0))

        behavior = self.card(body)
        behavior.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=(0, 12))
        self.card_title(behavior, "Behavior")
        Label(
            behavior,
            text=(
                "When enabled, the app holds Shift down for you.\n\n"
                "Press and hold Shift to temporarily release sprint and walk.\n\n"
                "Release Shift to resume sprinting."
            ),
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            justify="left",
            wraplength=420,
            font=("Segoe UI", 11),
        ).pack(fill="x", pady=(10, 0))

    def build_timing_tab(self):
        body = self.scroll_body(self.timing_tab)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(2, weight=1)
        body.grid_rowconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        timing = self.card(body)
        timing.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 12))
        self.card_title(timing, "Map Detection Timing")
        Label(
            timing,
            text="Only affects map detection and OCR. Skill checks use their own fast loop.",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            wraplength=380,
            justify="left",
            font=("Segoe UI", 10),
        ).pack(fill="x", pady=(8, 8))
        self.timing_entries = {}
        self.timing_input_row(timing, "Search delay", "scanMs", 100, 5000, "ms")
        self.timing_input_row(timing, "Disappear check", "triggerSeenScanMs", 50, 2000, "ms")
        self.timing_input_row(timing, "OCR interval", "ocrIntervalMs", 50, 10000, "ms")
        self.timing_input_row(timing, "OCR window", "ocrWindowMs", 1000, 120000, "ms")
        self.button(timing, "Apply Timing", self.apply_timing_settings, "primary").pack(fill="x", pady=(14, 0))

        settings = self.card(body)
        settings.grid(row=0, column=1, rowspan=2, columnspan=2, sticky="nsew", padx=(10, 0))
        self.card_title(settings, "Skill Detection Tuning")
        self.skill_entries = {}
        skill_grid = Frame(settings, bg=self.COLORS["panel"])
        skill_grid.pack(fill=BOTH, expand=True, pady=(8, 0))
        skill_grid.grid_columnconfigure(0, weight=1)
        skill_grid.grid_columnconfigure(1, weight=1)
        skill_left = Frame(skill_grid, bg=self.COLORS["panel"])
        skill_left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        skill_right = Frame(skill_grid, bg=self.COLORS["panel"])
        skill_right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.skill_input_row(skill_left, "Press input", "pressKey", "", "", "")
        self.skill_press_binding_buttons(skill_left)
        self.skill_input_row(skill_left, "White minimum", "whiteMin", 120, 255, "rgb")
        self.skill_input_row(skill_left, "White spread", "whiteSpreadMax", 10, 160, "rgb")
        self.skill_input_row(skill_left, "White zone size", "minWhitePixels", 1, 200, "px")
        self.skill_input_row(skill_left, "Single zone size", "minWhiteZonePixels", 1, 300, "px")
        self.skill_input_row(skill_left, "Zone thickness max", "maxWhiteZoneRadialSpan", 1, 80, "px")
        self.skill_input_row(skill_left, "Zone gap merge", "whiteAngleGapDeg", 0, 30, "deg")
        self.skill_input_row(skill_left, "White angle span", "minWhiteAngleSpan", 1, 90, "deg")
        self.skill_input_row(skill_left, "Ring evidence", "minRingOutlineBins", 0, 360, "deg")
        self.skill_input_row(skill_left, "Ring max fill", "maxRingOutlinePercent", 1, 100, "%")
        self.skill_input_row(skill_left, "Center prompt", "minCenterPromptPixels", 0, 2000, "px")
        self.skill_input_row(skill_right, "Center max", "maxCenterPromptPixels", 0, 5000, "px")
        self.skill_input_row(skill_right, "Red minimum", "redMin", 80, 255, "rgb")
        self.skill_input_row(skill_right, "Red other max", "redOtherMax", 0, 220, "rgb")
        self.skill_input_row(skill_right, "Great tolerance", "greatHitTolerancePx", 0, 6, "px")
        self.skill_input_row(skill_right, "Great lead", "greatLeadDegrees", 0, 30, "deg")
        self.skill_input_row(skill_right, "Great red pixels", "minGreatRedPixels", 1, 50, "px")
        self.skill_input_row(skill_right, "Hit tolerance", "hitTolerancePx", 0, 20, "px")
        self.skill_input_row(skill_right, "Angle tolerance", "angleToleranceDeg", 1, 45, "deg")
        self.skill_input_row(skill_right, "Red hit pixels", "minRedPixels", 1, 200, "px")
        self.skill_input_row(skill_right, "Ring inner", "ringInnerPercent", 0, 100, "%")
        self.skill_input_row(skill_right, "Ring outer", "ringOuterPercent", 1, 120, "%")
        self.button(settings, "Apply Skill Tuning", self.apply_skill_settings, "primary").pack(fill="x", pady=(14, 0))

        debug = self.card(body)
        debug.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        self.card_title(debug, "Maintenance")
        Label(
            debug,
            text="Debug tools are here so normal screens stay clean.",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            wraplength=420,
            justify="left",
            font=("Segoe UI", 10),
        ).pack(fill="x", pady=(8, 10))
        self.button(debug, "Toggle Skill Screen Overlay", self.toggle_skill_debug_overlay).pack(fill="x", pady=(0, 8))
        self.button(debug, "Toggle Skill Debug Images", self.toggle_skill_debug_images).pack(fill="x", pady=(0, 8))
        self.button(debug, "Toggle OCR Debug Images", self.toggle_ocr_debug_images).pack(fill="x", pady=(0, 8))
        self.button(debug, "Open Skill Debug Folder", self.open_skill_debug_folder).pack(fill="x", pady=(0, 8))
        self.button(debug, "Clear Generated Debug Files", self.clear_debug_images, "danger").pack(fill="x")

    def build_map_tab(self):
        body = self.scroll_body(self.map_tab)
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(2, weight=1)
        body.grid_rowconfigure(0, weight=1)

        library = self.card(body)
        library.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.card_title(library, "All Maps")
        self.button(library, "Refresh Images", self.refresh_map_library).pack(fill="x", pady=(8, 0))
        list_frame = Frame(library, bg=self.COLORS["panel"])
        list_frame.pack(fill=BOTH, expand=True, pady=(8, 0))
        self.map_list = Listbox(
            list_frame,
            width=30,
            bg=self.COLORS["panel2"],
            fg=self.COLORS["text"],
            selectbackground=self.COLORS["accent"],
            selectforeground="#07111c",
            highlightthickness=0,
            relief="flat",
            activestyle="none",
            font=("Segoe UI", 10),
        )
        map_scroll = Scrollbar(list_frame, command=self.map_list.yview)
        self.map_list.configure(yscrollcommand=map_scroll.set)
        self.map_list.pack(side=LEFT, fill=BOTH, expand=True)
        map_scroll.pack(side=RIGHT, fill=Y)
        self.populate_map_list()
        self.map_list.bind("<<ListboxSelect>>", self.on_map_selected)

        details = self.card(body)
        details.grid(row=0, column=1, sticky="nsew", padx=10)
        self.card_title(details, "Selected Map")
        self.map_name = Label(details, text="", bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Segoe UI", 20, "bold"), anchor="w")
        self.map_name.pack(fill="x", pady=(8, 4))
        self.map_realm = Label(details, text="", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 11), anchor="w")
        self.map_realm.pack(fill="x")
        self.current_map_label = Label(details, text="Current detected: none", bg=self.COLORS["panel"], fg=self.COLORS["accent"], font=("Segoe UI", 10, "bold"), anchor="w")
        self.current_map_label.pack(fill="x", pady=(14, 6))
        self.image_count_label = Label(details, text="", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 10), anchor="w")
        self.image_count_label.pack(fill="x")

        self.card_title(details, "Available Images")
        image_list_frame = Frame(details, bg=self.COLORS["panel"])
        image_list_frame.pack(fill=BOTH, expand=True, pady=(8, 0))
        self.image_list = Listbox(
            image_list_frame,
            height=8,
            bg=self.COLORS["panel2"],
            fg=self.COLORS["text"],
            selectbackground=self.COLORS["accent"],
            selectforeground="#07111c",
            highlightthickness=0,
            relief="flat",
            activestyle="none",
            font=("Segoe UI", 9),
        )
        image_scroll = Scrollbar(image_list_frame, command=self.image_list.yview)
        self.image_list.configure(yscrollcommand=image_scroll.set)
        self.image_list.pack(side=LEFT, fill=BOTH, expand=True)
        image_scroll.pack(side=RIGHT, fill=Y)
        self.image_list.bind("<<ListboxSelect>>", self.on_image_selected)

        preview = self.card(body)
        preview.grid(row=0, column=2, sticky="nsew", padx=(10, 0))
        self.card_title(preview, "Image Preview")
        self.map_image = Label(preview, text="No local map image loaded yet.", bg=self.COLORS["panel2"], fg=self.COLORS["muted"], font=("Segoe UI", 11), compound="center")
        self.map_image.pack(fill=BOTH, expand=True, pady=(8, 0))

    def populate_map_list(self):
        self.map_list.delete(0, END)
        for entry in self.map_library_entries:
            count = len(entry["images"])
            marker = f" ({count} image{'s' if count != 1 else ''})" if count else " (no image)"
            self.map_list.insert(END, f"{entry['name']}{marker}")

    def refresh_map_library(self):
        selected = self.selected_map_name
        self.map_library_entries = build_map_library_entries()
        self.populate_map_list()
        if selected:
            self.select_map_by_name(selected)
        elif self.map_library_entries:
            self.selected_map_name = self.map_library_entries[0]["name"]
            self.render_map_view()
        self.log("Map image library refreshed.")
        self.render_home_state()

    def build_overlay_tab(self):
        body = self.scroll_body(self.overlay_tab)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(2, weight=1)

        state = self.card(body)
        state.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.card_title(state, "Overlay Mode")
        self.overlay_pill = self.pill(state, "Off", "stop")
        self.overlay_pill.pack(fill="x", pady=(10, 10))
        self.overlay_detail = Label(state, text="", bg=self.COLORS["panel"], fg=self.COLORS["muted"], justify="left", wraplength=400, font=("Segoe UI", 11))
        self.overlay_detail.pack(fill="x", pady=(0, 18))
        self.check_toggle(state, "Show map overlay", self.overlay_enabled_var, self.set_overlay_from_toggle).pack(fill="x", pady=(0, 10))
        self.check_toggle(state, "Drag mode", self.overlay_drag_var, self.set_overlay_drag_from_toggle).pack(fill="x", pady=(0, 14))

        settings = self.card(body)
        settings.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.card_title(settings, "Screen Corner")
        self.position_label = self.setting_row(settings, "Corner")
        top_buttons = Frame(settings, bg=self.COLORS["panel"])
        top_buttons.pack(fill="x", pady=(6, 8))
        self.button(top_buttons, "Top Left", lambda: self.set_overlay_position("top-left")).pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.button(top_buttons, "Top Right", lambda: self.set_overlay_position("top-right")).pack(side="left", fill="x", expand=True, padx=(5, 0))
        bottom_buttons = Frame(settings, bg=self.COLORS["panel"])
        bottom_buttons.pack(fill="x", pady=(0, 12))
        self.button(bottom_buttons, "Bottom Left", lambda: self.set_overlay_position("bottom-left")).pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.button(bottom_buttons, "Bottom Right", lambda: self.set_overlay_position("bottom-right")).pack(side="left", fill="x", expand=True, padx=(5, 0))

        appearance = self.card(body)
        appearance.grid(row=0, column=2, sticky="nsew", padx=(10, 0))
        self.card_title(appearance, "Size and Visibility")
        self.size_label = self.scale_row(appearance, "Size", "sizePercent", 10, 85, "%")
        self.opacity_label = self.scale_row(appearance, "Transparency", "opacity", 10, 100, "%", scale_value=lambda v: float(v) / 100, display_value=lambda v: int(float(v) * 100))
        self.margin_label = self.scale_row(appearance, "Screen margin", "margin", 0, 200, "px")

    def card(self, parent):
        frame = Frame(parent, bg=self.COLORS["panel"], highlightthickness=1, highlightbackground=self.COLORS["line"], padx=18, pady=16)
        return frame

    def card_title(self, parent, text):
        Label(parent, text=text.upper(), bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x")

    def button(self, parent, text, command, variant="secondary"):
        bg = self.COLORS["accent"] if variant == "primary" else self.COLORS["danger"] if variant == "danger" else self.COLORS["panel3"]
        hover = "#f04b45" if variant == "primary" else "#ff777a" if variant == "danger" else self.COLORS["button_hover"]
        fg = "#ffffff"
        return Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=hover,
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            padx=16,
            pady=10,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
        )

    def pill(self, parent, text, kind):
        label = Label(parent, text=text, padx=12, pady=7, font=("Segoe UI", 9, "bold"), anchor="w")
        self.set_pill(label, text, kind)
        return label

    def set_pill(self, label, text, kind):
        colors = {
            "watch": (self.COLORS["accent"], "#051019"),
            "good": (self.COLORS["accent2"], "#061107"),
            "warn": (self.COLORS["warn"], "#171203"),
            "stop": ("#3a4658", self.COLORS["text"]),
            "danger": (self.COLORS["danger"], "#1b0606"),
        }
        bg, fg = colors.get(kind, colors["stop"])
        label.configure(text=text, bg=bg, fg=fg)

    def setting_row(self, parent, label):
        row = Frame(parent, bg=self.COLORS["panel"])
        row.pack(fill="x", pady=(12, 4))
        Label(row, text=label, bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 10, "bold")).pack(side="left")
        value = Label(row, text="", bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Segoe UI", 10))
        value.pack(side="right")
        return value

    def scale_row(self, parent, label, key, from_, to, suffix, scale_value=None, display_value=None):
        value_label = self.setting_row(parent, label)
        raw_value = self.cfg["overlay"].get(key, DEFAULT_CONFIG["overlay"].get(key))
        display = display_value(raw_value) if display_value else raw_value
        value_label.configure(text=f"{int(round(float(display)))}{suffix}")

        scale = ttk.Scale(parent, from_=from_, to=to, orient="horizontal")
        scale.set(float(display))
        scale.pack(fill="x", pady=(0, 8))

        def on_change(value):
            next_value = scale_value(value) if scale_value else float(value)
            self.cfg["overlay"][key] = next_value
            save_config(self.cfg, force_overlay=True)
            value_label.configure(text=f"{int(round(float(value)))}{suffix}")
            self.update_overlay()
            self.render_overlay_state()
            self.render_home_state()

        scale.configure(command=on_change)
        return value_label

    def timing_input_row(self, parent, label, key, minimum, maximum, suffix):
        row = Frame(parent, bg=self.COLORS["panel"])
        row.pack(fill="x", pady=(12, 4))
        Label(row, text=label, bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 10, "bold")).pack(anchor="w")

        input_row = Frame(parent, bg=self.COLORS["panel"])
        input_row.pack(fill="x", pady=(0, 6))
        entry = Entry(
            input_row,
            bg=self.COLORS["panel2"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["text"],
            relief="flat",
            font=("Consolas", 10),
        )
        entry.insert(0, str(int(self.cfg.get(key, DEFAULT_CONFIG.get(key, minimum)))))
        entry.pack(side="left", fill="x", expand=True, ipady=5)
        Label(input_row, text=suffix, bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 10)).pack(side="left", padx=(8, 0))

        hint = Label(parent, text=f"{minimum}-{maximum} {suffix}", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 8))
        hint.pack(anchor="w", pady=(0, 4))
        self.timing_entries[key] = {
            "entry": entry,
            "label": label,
            "minimum": int(minimum),
            "maximum": int(maximum),
            "suffix": suffix,
        }
        entry.bind("<Return>", lambda _event: self.apply_timing_settings())
        return entry

    def skill_input_row(self, parent, label, key, minimum, maximum, suffix):
        row = Frame(parent, bg=self.COLORS["panel"])
        row.pack(fill="x", pady=(10, 3))
        Label(row, text=label, bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 10, "bold")).pack(anchor="w")

        input_row = Frame(parent, bg=self.COLORS["panel"])
        input_row.pack(fill="x", pady=(0, 4))
        entry = Entry(
            input_row,
            bg=self.COLORS["panel2"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["text"],
            relief="flat",
            font=("Consolas", 10),
        )
        entry.insert(0, str(self.cfg["skillCheck"].get(key, DEFAULT_CONFIG["skillCheck"].get(key, ""))))
        entry.pack(side="left", fill="x", expand=True, ipady=5)
        if suffix:
            Label(input_row, text=suffix, bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 10)).pack(side="left", padx=(8, 0))
            Label(parent, text=f"{minimum}-{maximum} {suffix}", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 2))
        self.skill_entries[key] = {
            "entry": entry,
            "label": label,
            "minimum": minimum,
            "maximum": maximum,
            "suffix": suffix,
        }
        entry.bind("<Return>", lambda _event: self.apply_skill_settings())
        return entry

    def skill_press_binding_buttons(self, parent):
        wrapper = Frame(parent, bg=self.COLORS["panel"])
        wrapper.pack(fill="x", pady=(0, 8))
        Label(
            wrapper,
            text="Quick bindings",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Segoe UI", 8, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        bindings = [
            ("C", "c"),
            ("Space", "space"),
            ("M1", "mouse1"),
            ("M2", "mouse2"),
            ("M3", "mouse3"),
            ("M4", "mouse4"),
            ("M5", "mouse5"),
        ]
        rows = [Frame(wrapper, bg=self.COLORS["panel"]), Frame(wrapper, bg=self.COLORS["panel"])]
        rows[0].pack(fill="x", pady=(0, 5))
        rows[1].pack(fill="x")
        for index, (label, value) in enumerate(bindings):
            row = rows[0] if index < 4 else rows[1]
            self.button(row, label, lambda next_value=value: self.set_skill_press_key(next_value)).pack(side="left", fill="x", expand=True, padx=(0 if index in (0, 4) else 5, 0))
        Label(
            wrapper,
            text="Mouse 4 and Mouse 5 are the side buttons.",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(6, 0))

    def set_skill_press_key(self, value):
        value = str(value or "").strip().lower() or DEFAULT_CONFIG["skillCheck"]["pressKey"]
        self.cfg["skillCheck"]["pressKey"] = value
        meta = getattr(self, "skill_entries", {}).get("pressKey")
        if meta:
            entry = meta["entry"]
            entry.delete(0, END)
            entry.insert(0, value)
        save_config(self.cfg)
        self.refresh_area_labels()
        self.render_home_state()
        self.log(f"Skill check input set to {self.skill_input_display(value)}.")

    def skill_input_display(self, value):
        labels = {
            "mouse1": "Mouse 1",
            "m1": "Mouse 1",
            "mouse2": "Mouse 2",
            "m2": "Mouse 2",
            "mouse3": "Mouse 3",
            "m3": "Mouse 3",
            "mouse4": "Mouse 4",
            "m4": "Mouse 4",
            "x1": "Mouse 4",
            "xbutton1": "Mouse 4",
            "side1": "Mouse 4",
            "mouse5": "Mouse 5",
            "m5": "Mouse 5",
            "x2": "Mouse 5",
            "xbutton2": "Mouse 5",
            "side2": "Mouse 5",
            "space": "Space",
        }
        text = str(value or "").strip().lower()
        return labels.get(text, str(value or "c"))

    def apply_skill_settings(self):
        changed = []
        skill = self.cfg["skillCheck"]
        for key, meta in self.skill_entries.items():
            entry = meta["entry"]
            raw = entry.get().strip()
            old_value = skill.get(key)
            if key == "pressKey":
                value = raw or DEFAULT_CONFIG["skillCheck"][key]
            else:
                try:
                    value = int(float(raw))
                except ValueError:
                    value = int(skill.get(key, DEFAULT_CONFIG["skillCheck"].get(key, meta["minimum"])))
                value = max(int(meta["minimum"]), min(int(meta["maximum"]), value))
            skill[key] = value
            if key == "ringOuterPercent":
                value = max(int(skill.get("ringInnerPercent", 0)) + 1, value)
                skill[key] = value
            elif key == "ringInnerPercent":
                outer = int(skill.get("ringOuterPercent", DEFAULT_CONFIG["skillCheck"]["ringOuterPercent"]))
                if outer <= value:
                    skill["ringOuterPercent"] = min(120, value + 1)
            elif key == "minWhiteAngleSpan":
                maximum = int(skill.get("maxWhiteAngleSpan", DEFAULT_CONFIG["skillCheck"]["maxWhiteAngleSpan"]))
                if maximum < value:
                    skill["maxWhiteAngleSpan"] = value
            entry.delete(0, END)
            entry.insert(0, str(value))
            if value != old_value:
                changed.append(f"{meta['label']} = {value}{meta['suffix']}")

        save_config(self.cfg)
        if changed:
            self.log("Skill check settings applied: " + ", ".join(changed))
        else:
            self.log("Skill check settings applied.")
        return True

    def apply_timing_settings(self):
        changed = []
        for key, meta in self.timing_entries.items():
            entry = meta["entry"]
            raw = entry.get().strip()
            try:
                value = int(float(raw))
            except ValueError:
                value = int(self.cfg.get(key, DEFAULT_CONFIG.get(key, meta["minimum"])))
            value = max(meta["minimum"], min(meta["maximum"], value))
            old_value = int(self.cfg.get(key, 0))
            self.cfg[key] = value
            entry.delete(0, END)
            entry.insert(0, str(value))
            if value != old_value:
                changed.append(f"{meta['label']} = {value}{meta['suffix']}")

        save_config(self.cfg)
        if changed:
            self.log("Timing settings applied: " + ", ".join(changed))
        else:
            self.log("Timing settings applied.")
        return True

    def set_text(self, widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", END)
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def format_box(self, box):
        if not box:
            return "not set"
        scope = "DBD" if isinstance(box, dict) and box.get("relativeTo") == "dbd-window" else "screen"
        return f"{scope} x={box.get('x')} y={box.get('y')} w={box.get('width')} h={box.get('height')}"

    def box_summary(self):
        return f"Trigger box: {self.format_box(self.cfg.get('imageTriggerBox'))}\nText box: {self.format_box(self.cfg.get('textBox'))}"

    def skill_box_summary(self):
        skill = self.cfg.get("skillCheck") or {}
        return f"Skill-check box: {self.format_box(skill.get('box'))}\nInput: {self.skill_input_display(skill.get('pressKey') or 'c')}\nHit rule: red inside white-zone interior"

    def refresh_area_labels(self):
        if hasattr(self, "boxes"):
            self.boxes.configure(text=self.box_summary())
        if hasattr(self, "skill_box_label"):
            self.skill_box_label.configure(text=self.skill_box_summary())
        self.render_home_state()

    def render_home_state(self):
        if not hasattr(self, "home_map_status"):
            return
        map_running = bool(self.cfg.get("mapDetectorEnabled"))
        skill_cfg = self.cfg.get("skillCheck") or {}
        skill_running = bool(skill_cfg.get("enabled"))
        overlay_cfg = self.cfg.get("overlay") or {}
        overlay_enabled = bool(overlay_cfg.get("enabled"))
        overlay_position = overlay_cfg.get("position") or ("top-left" if overlay_cfg.get("side") == "left" else "top-right")
        if hasattr(self, "map_enabled_var"):
            self.map_enabled_var.set(map_running)
        if hasattr(self, "skill_enabled_var"):
            self.skill_enabled_var.set(skill_running)
        if hasattr(self, "overlay_enabled_var"):
            self.overlay_enabled_var.set(overlay_enabled)
        if hasattr(self, "overlay_drag_var"):
            self.overlay_drag_var.set(bool(overlay_cfg.get("dragMode")))
        auto_sprint_cfg = self.cfg.get("autoSprint") or {}
        auto_sprint_enabled = bool(auto_sprint_cfg.get("enabled"))
        if hasattr(self, "auto_sprint_enabled_var"):
            self.auto_sprint_enabled_var.set(auto_sprint_enabled)
        if hasattr(self, "auto_sprint_dbd_only_var"):
            self.auto_sprint_dbd_only_var.set(bool(auto_sprint_cfg.get("dbdOnly", True)))

        map_text = "Watching" if map_running else "Off"
        if self.current_match:
            map_text = f"Matched: {self.current_match['name']}"
        self.home_map_status.configure(text=map_text, fg=self.COLORS["accent2"] if map_running or self.current_match else self.COLORS["text"])
        self.home_map_detail.configure(
            text=(
                f"Trigger: {self.format_box(self.cfg.get('imageTriggerBox'))}\n"
                f"Text: {self.format_box(self.cfg.get('textBox'))}"
            )
        )

        skill_input = self.skill_input_display(skill_cfg.get("pressKey") or "c")
        self.home_skill_status.configure(text="Watching" if skill_running else "Off", fg=self.COLORS["accent2"] if skill_running else self.COLORS["text"])
        self.home_skill_detail.configure(
            text=(
                f"Area: {self.format_box(skill_cfg.get('box'))}\n"
                f"Input: {skill_input}"
            )
        )

        map_name = self.current_match["name"] if self.current_match else self.selected_map_name or "none"
        overlay_state = "On" if overlay_enabled else "Off"
        mouse_state = "drag mode" if overlay_cfg.get("dragMode") else "click-through"
        self.home_overlay_status.configure(
            text=(
                f"Overlay: {overlay_state}\n"
                f"Position: {overlay_position.replace('-', ' ').title()}\n"
                f"Mouse: {mouse_state}\n"
                f"Map: {map_name}"
            )
        )
        if hasattr(self, "home_current_map"):
            self.home_current_map.configure(text=map_name if map_name != "none" else "No map selected")
            if self.current_match:
                current_detail = f"Detected with score {self.current_match.get('score', 0):.2f}"
            else:
                image_count = len(getattr(self, "selected_image_paths", []) or [])
                current_detail = f"Selected manually. {image_count} image{'s' if image_count != 1 else ''} loaded."
            self.home_current_map_detail.configure(text=current_detail)
        if hasattr(self, "home_auto_sprint_status"):
            status = self.auto_sprint_display_text() if auto_sprint_enabled else "Off"
            self.home_auto_sprint_status.configure(text=status, fg=self.auto_sprint_display_color() if auto_sprint_enabled else self.COLORS["text"])
            scope = "DBD only" if auto_sprint_cfg.get("dbdOnly", True) else "global"
            self.home_auto_sprint_detail.configure(text=f"Mode: {scope}\nShift held to sprint\nHold Shift to walk")
        if hasattr(self, "auto_sprint_status"):
            self.auto_sprint_status.configure(text=self.auto_sprint_display_text() if auto_sprint_enabled else "Off", fg=self.auto_sprint_display_color() if auto_sprint_enabled else self.COLORS["text"])
            scope = "only while DBD is focused" if auto_sprint_cfg.get("dbdOnly", True) else "globally"
            self.auto_sprint_detail.configure(text=f"Shift is held {scope}. Hold Shift yourself to walk.")
        if hasattr(self, "auto_sprint_global_pill"):
            if auto_sprint_enabled and self.auto_sprint_mode == "running":
                self.set_pill(self.auto_sprint_global_pill, "Sprint: running", "good")
            elif auto_sprint_enabled and self.auto_sprint_mode == "walking":
                self.set_pill(self.auto_sprint_global_pill, "Sprint: walk", "warn")
            else:
                self.set_pill(self.auto_sprint_global_pill, "Sprint: on" if auto_sprint_enabled else "Sprint: off", "watch" if auto_sprint_enabled else "stop")

    def auto_sprint_display_text(self):
        return {
            "running": "Sprinting",
            "walking": "Walking",
            "waiting for DBD focus": "Waiting",
            "error": "Error",
            "off": "Off",
        }.get(self.auto_sprint_mode, "On")

    def auto_sprint_display_color(self):
        return {
            "running": self.COLORS["accent2"],
            "walking": self.COLORS["warn"],
            "waiting for DBD focus": self.COLORS["muted"],
            "error": self.COLORS["danger"],
            "off": self.COLORS["text"],
        }.get(self.auto_sprint_mode, self.COLORS["accent2"])

    def log(self, message):
        log_to_file(message)
        line = f"[{time.strftime('%H:%M:%S')}] {message}\n"
        if hasattr(self, "log_box"):
            self.log_box.configure(state="normal")
            self.log_box.insert("1.0", line)
            self.log_box.delete("220.0", END)
            self.log_box.configure(state="disabled")
        if hasattr(self, "home_activity"):
            self.home_activity.configure(state="normal")
            self.home_activity.insert("1.0", line)
            self.home_activity.delete("160.0", END)
            self.home_activity.configure(state="disabled")

    def start_detection(self):
        self.apply_timing_settings()
        self.cfg["mapDetectorEnabled"] = True
        save_config(self.cfg)
        self.set_pill(self.run_pill, "Map: watching", "watch")
        self.status.configure(text="Waiting for trigger image.")
        self.detector.start()
        self.render_home_state()

    def stop_detection(self):
        self.cfg["mapDetectorEnabled"] = False
        save_config(self.cfg)
        self.detector.stop()
        self.set_pill(self.run_pill, "Map: off", "stop")
        self.status.configure(text="Stopped.")
        self.render_home_state()

    def start_skill_checks(self):
        self.apply_skill_settings()
        self.cfg["skillCheck"]["enabled"] = True
        save_config(self.cfg)
        self.set_pill(self.skill_pill, "Watching", "watch")
        self.set_pill(self.skill_global_pill, "Skill: on", "watch")
        self.set_pill(self.skill_white_pill, "White: no", "stop")
        self.set_pill(self.skill_zone_pill, "Markers: 0", "stop")
        self.set_pill(self.skill_red_pill, "Red in zone: no", "stop")
        self.set_pill(self.skill_hit_pill, "Hit: no", "stop")
        self.skill_status.configure(text="Watching skill-check area.")
        self.skill_detector.start()
        self.render_home_state()

    def stop_skill_checks(self):
        self.cfg["skillCheck"]["enabled"] = False
        save_config(self.cfg)
        self.skill_detector.stop()
        self.skill_debug_overlay.close()
        self.set_pill(self.skill_pill, "Stopped", "stop")
        self.set_pill(self.skill_global_pill, "Skill: off", "stop")
        self.set_pill(self.skill_white_pill, "White: no", "stop")
        self.set_pill(self.skill_zone_pill, "Markers: 0", "stop")
        self.set_pill(self.skill_red_pill, "Red in zone: no", "stop")
        self.set_pill(self.skill_hit_pill, "Hit: no", "stop")
        self.skill_preview_photo = None
        self.skill_preview.configure(image="", text="Live preview will appear while watching.")
        self.skill_status.configure(text="Stopped.")
        self.render_home_state()

    def start_auto_sprint(self):
        self.cfg["autoSprint"]["enabled"] = True
        self.cfg["autoSprint"]["dbdOnly"] = bool(self.auto_sprint_dbd_only_var.get())
        save_config(self.cfg)
        self.auto_sprint_mode = "waiting for DBD focus"
        self.auto_sprint.start()
        self.render_home_state()

    def stop_auto_sprint(self):
        self.cfg["autoSprint"]["enabled"] = False
        save_config(self.cfg)
        self.auto_sprint_mode = "off"
        self.auto_sprint.stop()
        self.render_home_state()

    def toggle_skill_debug_overlay(self):
        skill = self.cfg["skillCheck"]
        skill["screenDebugOverlay"] = not bool(skill.get("screenDebugOverlay"))
        save_config(self.cfg)
        if skill["screenDebugOverlay"]:
            self.skill_status.configure(text="Screen debug overlay enabled.")
            self.log("Skill check screen debug overlay enabled.")
        else:
            self.skill_debug_overlay.close()
            self.skill_status.configure(text="Screen debug overlay disabled.")
            self.log("Skill check screen debug overlay disabled.")

    def toggle_ocr_debug_images(self):
        self.cfg["saveOcrDebugImages"] = not bool(self.cfg.get("saveOcrDebugImages"))
        save_config(self.cfg)
        state = "enabled" if self.cfg["saveOcrDebugImages"] else "disabled"
        self.status.configure(text=f"OCR debug image saving {state}.")
        self.log(f"OCR debug image saving {state}.")

    def toggle_skill_debug_images(self):
        skill = self.cfg["skillCheck"]
        skill["saveDebugImages"] = not bool(skill.get("saveDebugImages"))
        save_config(self.cfg)
        state = "enabled" if skill["saveDebugImages"] else "disabled"
        self.skill_status.configure(text=f"Skill debug image saving {state}.")
        self.log(f"Skill debug image saving {state}.")

    def remove_debug_path(self, path):
        base = ASSET_DIR.resolve()
        target = Path(path).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            raise ValueError(f"Refusing to remove outside assets: {target}")
        if target.is_dir():
            count = sum(1 for item in target.rglob("*") if item.is_file())
            shutil.rmtree(target)
            return count
        if target.is_file():
            target.unlink()
            return 1
        return 0

    def clear_debug_images(self):
        targets = [
            OCR_DEBUG_DIR,
            SKILL_DEBUG_DIR,
            ASSET_DIR / "map-original-backups",
            DEBUG_TRIGGER_CURRENT_PATH,
            DEBUG_TEXT_AREA_PATH,
            DEBUG_TEXT_AREA_PROCESSED_PATH,
        ]
        try:
            removed = sum(self.remove_debug_path(path) for path in targets)
        except Exception as exc:
            self.status.configure(text=f"Debug cleanup failed: {exc}")
            self.log(f"Debug cleanup failed: {exc}")
            return
        message = f"Removed {removed} generated debug file{'s' if removed != 1 else ''}."
        self.status.configure(text=message)
        self.skill_status.configure(text=message)
        self.log(message)

    def test_skill_input(self, apply_settings=True, source="button", hotkey=None):
        if apply_settings:
            self.apply_skill_settings()
        input_name = self.cfg["skillCheck"].get("pressKey") or "c"
        try:
            activate_windows_input(input_name)
            self.set_pill(self.skill_hit_pill, "Hit: SENT", "good")
            detail = f" from {hotkey}" if hotkey else ""
            self.skill_status.configure(text=f"Test sent {input_name}{detail}.")
            self.log(f"Skill check test sent {input_name}{detail} ({source}).")
        except Exception as exc:
            self.skill_status.configure(text=f"Test input failed: {exc}")
            self.log(f"Skill check test input failed: {exc}")

    def open_skill_debug_folder(self):
        SKILL_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(SKILL_DEBUG_DIR)
        except Exception as exc:
            self.log(f"Could not open skill debug folder: {exc}")

    def ensure_ocr_installed_async(self):
        if self.detector.tesseract:
            self.log(f"OCR already installed: {self.detector.tesseract}")
            return
        if self.installing_ocr:
            self.log("OCR install is already running.")
            return
        self.installing_ocr = True
        self.log("Installing Tesseract OCR with winget. Windows may show an installer or permission prompt.")

        def worker():
            ok, message = install_tesseract_with_winget()
            self.events.put(("ocr-install", {"ok": ok, "message": message}))

        threading.Thread(target=worker, daemon=True).start()

    def process_events(self):
        handled_event = False
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            handled_event = True
            if kind == "log":
                self.log(payload)
            elif kind == "state":
                self.status.configure(text=payload)
                if "Waiting" in payload or "Trigger visible" in payload or "OCR scanning" in payload or "OCR capturing" in payload:
                    self.set_pill(self.run_pill, "Map: watching", "watch")
            elif kind == "score":
                self.score.configure(text=payload)
            elif kind == "skill-state":
                self.skill_status.configure(text=payload)
                if "Watching" in payload:
                    self.set_pill(self.skill_pill, "Watching", "watch")
                    self.set_pill(self.skill_global_pill, "Skill: on", "watch")
            elif kind == "skill-score":
                self.skill_score.configure(text=payload)
            elif kind == "skill-visual":
                armed = bool(payload.get("armed"))
                hit = bool(payload.get("hit"))
                cooldown = bool(payload.get("cooldown"))
                red_in_zone = int(payload.get("redInZone") or 0)
                red_total = int(payload.get("redTotal") or 0)
                memory = int(payload.get("memory") or 0)
                zones = int(payload.get("zones") or 0)
                hit_zones = int(payload.get("hitZones") or 0)
                rgb = payload.get("rgb")
                overlay_rgba = payload.get("overlayRgba")
                overlay_box = payload.get("box")
                width = int(payload.get("width") or 0)
                height = int(payload.get("height") or 0)
                if rgb and width > 0 and height > 0:
                    try:
                        image = Image.frombytes("RGB", (width, height), rgb)
                        image.thumbnail((360, 260), Image.Resampling.NEAREST)
                        self.skill_preview_photo = ImageTk.PhotoImage(image)
                        self.skill_preview.configure(image=self.skill_preview_photo, text="")
                    except Exception:
                        pass
                if overlay_rgba and overlay_box and width > 0 and height > 0:
                    self.skill_debug_overlay.update(overlay_box, overlay_rgba, width, height)
                self.set_pill(self.skill_white_pill, f"White: {'seen' if armed else 'no'}", "good" if armed else "stop")
                zone_kind = "good" if zones and hit_zones >= zones else "warn" if zones else "stop"
                self.set_pill(self.skill_zone_pill, f"Markers: {zones}", zone_kind)
                self.set_pill(self.skill_global_pill, f"Skill: on {zones}", "watch")
                self.set_pill(self.skill_red_pill, f"Red in target: {red_in_zone}", "warn" if red_in_zone else "stop")
                hit_text = "Hit: SENT" if hit else "Hit: cooldown" if cooldown else "Hit: no"
                self.set_pill(self.skill_hit_pill, hit_text, "good" if hit else "warn" if cooldown else "stop")
                if hit:
                    self.skill_status.configure(text=f"NOW: sent input; red inside target {red_in_zone}; markers {zones}.")
                elif cooldown:
                    self.skill_status.configure(text=f"NOW: red still inside the same marker ({red_in_zone}); waiting to re-arm.")
                elif armed and red_in_zone:
                    self.skill_status.configure(text=f"NOW: red inside target ({red_in_zone}); markers {zones}.")
                elif armed:
                    self.skill_status.configure(text=f"NOW: found {zones} marker{'s' if zones != 1 else ''}; red in target 0; total red {red_total}.")
                else:
                    self.skill_status.configure(text=f"NOW: watching; looking for a big enough white success zone; total red {red_total}.")
            elif kind == "skill-hit":
                self.skill_status.configure(text=payload)
                self.set_pill(self.skill_pill, "Pressed", "good")
                self.set_pill(self.skill_hit_pill, "Hit: SENT", "good")
                self.log(f"Skill check {payload}.")
            elif kind == "skill-test-input":
                if payload.get("ok"):
                    input_name = payload.get("input") or self.cfg["skillCheck"].get("pressKey") or "c"
                    self.set_pill(self.skill_hit_pill, "Hit: SENT", "good")
                    self.skill_status.configure(text=f"Sent {input_name}.")
                    self.log(f"Skill check sent {input_name}.")
                else:
                    self.skill_status.configure(text=f"Input failed: {payload.get('message')}")
                    self.log(f"Skill check input failed: {payload.get('message')}")
            elif kind == "auto-sprint-state":
                text = str(payload)
                self.auto_sprint_mode = text if not text.startswith("error") else "error"
                if hasattr(self, "auto_sprint_status"):
                    if text == "off":
                        self.auto_sprint_status.configure(text="Off", fg=self.COLORS["text"])
                    elif text.startswith("error"):
                        self.auto_sprint_status.configure(text="Error", fg=self.COLORS["danger"])
                    elif text == "walking":
                        self.auto_sprint_status.configure(text="Walking", fg=self.COLORS["warn"])
                    elif text == "running":
                        self.auto_sprint_status.configure(text="Sprinting", fg=self.COLORS["accent2"])
                    else:
                        self.auto_sprint_status.configure(text="Waiting", fg=self.COLORS["muted"])
                if hasattr(self, "auto_sprint_global_pill"):
                    if text == "running":
                        self.set_pill(self.auto_sprint_global_pill, "Sprint: running", "good")
                    elif text == "walking":
                        self.set_pill(self.auto_sprint_global_pill, "Sprint: walk", "warn")
                    elif text.startswith("error"):
                        self.set_pill(self.auto_sprint_global_pill, "Sprint: error", "danger")
                    else:
                        enabled = bool((self.cfg.get("autoSprint") or {}).get("enabled"))
                        self.set_pill(self.auto_sprint_global_pill, "Sprint: on" if enabled else "Sprint: off", "watch" if enabled else "stop")
            elif kind == "ocr":
                self.set_text(self.ocr, payload)
            elif kind == "match":
                self.current_match = payload
                self.status.configure(text=f"Matched map: {payload['name']} ({payload['score']:.2f})")
                self.set_pill(self.run_pill, "Map: matched", "good")
                self.set_text(self.ocr, f"{payload['name']}\n\nRaw OCR:\n{payload['raw']}")
                self.suppress_overlay_updates = True
                try:
                    self.select_map_by_name(payload["name"])
                finally:
                    self.suppress_overlay_updates = False
                self.update_overlay(force_recreate=True)
                self.render_overlay_state()
                self.render_home_state()
            elif kind == "ocr-install":
                self.installing_ocr = False
                if payload.get("ok"):
                    self.detector.tesseract = find_tesseract()
                    if self.detector.tesseract:
                        self.log(f"OCR installed and ready: {self.detector.tesseract}")
                        self.status.configure(text="OCR installed and ready.")
                    else:
                        self.log("OCR installer finished, but tesseract.exe was not found yet. Restarting the app may finish PATH refresh.")
                else:
                    self.log(f"OCR install failed: {payload.get('message') or 'unknown error'}")
                    self.status.configure(text="OCR install failed. Check the log.")
        if handled_event:
            self.render_home_state()
        self.root.after(50, self.process_events)

    def render_map_view(self):
        map_name = self.selected_map_name or (self.current_match["name"] if self.current_match else None)
        if not map_name:
            self.map_photo = None
            self.map_name.configure(text="No map selected")
            self.map_realm.configure(text="")
            self.current_map_label.configure(text="Current detected: none")
            self.image_count_label.configure(text="")
            self.image_list.delete(0, END)
            self.map_image.configure(image="", text="No local map image loaded yet.")
            self.render_home_state()
            return

        library_entry = self.selected_library_entry()
        entry = library_entry or map_entry_for_name(map_name)
        self.map_name.configure(text=entry["name"])
        aliases = f" | aliases: {', '.join(entry['aliases'][:4])}" if entry["aliases"] else ""
        self.map_realm.configure(text=f"{entry['realm'] or 'Unknown realm'}{aliases}")
        if self.current_match:
            self.current_map_label.configure(text=f"Current detected: {self.current_match['name']} ({self.current_match['score']:.2f})")
        else:
            self.current_map_label.configure(text="Current detected: none")

        self.selected_image_paths = list(entry.get("images", [])) if isinstance(entry, dict) and "images" in entry else find_map_images(entry["name"])
        self.image_list.delete(0, END)
        for path in self.selected_image_paths:
            self.image_list.insert(END, path.name)
        count = len(self.selected_image_paths)
        self.image_count_label.configure(text=f"{count} local image{'s' if count != 1 else ''} found")

        if self.selected_image_index >= count:
            self.selected_image_index = 0
        if count:
            self.image_list.selection_clear(0, END)
            self.image_list.selection_set(self.selected_image_index)
            self.image_list.see(self.selected_image_index)
            self.render_selected_map_image()
        else:
            self.map_photo = None
            self.map_image.configure(image="", text=f"No local image found for {entry['name']}.")
            if not self.suppress_overlay_updates:
                self.update_overlay()
        self.render_home_state()

    def render_selected_map_image(self):
        if not self.selected_image_paths:
            self.map_photo = None
            self.map_image.configure(image="", text="No local map image loaded yet.")
            if not self.suppress_overlay_updates:
                self.update_overlay()
            self.render_home_state()
            return
        image_path = self.selected_image_paths[self.selected_image_index]
        try:
            image = Image.open(image_path).convert("RGB")
            image.thumbnail((420, 420), Image.Resampling.LANCZOS)
            self.map_photo = ImageTk.PhotoImage(image)
            self.map_image.configure(image=self.map_photo, text="")
            if not self.suppress_overlay_updates:
                self.update_overlay()
            self.render_home_state()
        except Exception as exc:
            self.map_photo = None
            self.map_image.configure(image="", text=f"Could not load map image: {exc}")
            self.render_home_state()

    def select_map_by_name(self, map_name):
        for index, entry in enumerate(self.map_library_entries):
            if entry["name"] == map_name:
                self.map_list.selection_clear(0, END)
                self.map_list.selection_set(index)
                self.map_list.see(index)
                self.selected_map_name = entry["name"]
                self.selected_image_index = 0
                self.render_map_view()
                return
        self.selected_map_name = map_name
        self.selected_image_index = 0
        self.render_map_view()

    def on_map_selected(self, _event=None):
        selection = self.map_list.curselection()
        if not selection:
            return
        index = selection[0]
        self.selected_map_name = self.map_library_entries[index]["name"]
        self.selected_image_index = 0
        self.render_map_view()

    def selected_library_entry(self):
        for entry in self.map_library_entries:
            if entry["name"] == self.selected_map_name:
                return entry
        return None

    def on_image_selected(self, _event=None):
        selection = self.image_list.curselection()
        if not selection:
            return
        self.selected_image_index = selection[0]
        self.render_selected_map_image()

    def selected_overlay_image_path(self):
        if self.current_match:
            return find_map_image(self.current_match["name"])
        if self.selected_image_paths and 0 <= self.selected_image_index < len(self.selected_image_paths):
            return self.selected_image_paths[self.selected_image_index]
        if self.selected_map_name:
            return find_map_image(self.selected_map_name)
        return None

    def update_overlay(self, force_recreate=False):
        self.overlay.update(
            self.current_match,
            image_path=self.selected_overlay_image_path(),
            map_name=self.selected_map_name,
            force_recreate=force_recreate,
        )
        if self.overlay.last_error:
            message = self.overlay.last_error
        elif self.overlay.last_image_path:
            message = f"Overlay image: {self.overlay.last_image_path}"
        else:
            message = "Overlay has no map image loaded."
        if message != self.last_overlay_log:
            self.last_overlay_log = message
            self.log(message)

    def render_overlay_state(self):
        overlay_cfg = self.cfg.get("overlay") or {}
        enabled = bool(overlay_cfg.get("enabled"))
        position = overlay_cfg.get("position") or ("top-left" if overlay_cfg.get("side") == "left" else "top-right")
        self.set_pill(self.overlay_pill, "On" if enabled else "Off", "good" if enabled else "stop")
        self.position_label.configure(text=position.replace("-", " ").title())
        detail = "Overlay is enabled and click-through." if enabled else "Overlay is disabled."
        if enabled and overlay_cfg.get("dragMode"):
            detail = "Overlay drag mode is enabled. It can be moved with the mouse."
        detail += f"\nPosition: {position.replace('-', ' ').title()}"
        detail += f"\nMouse: {'drag mode' if overlay_cfg.get('dragMode') else 'click-through'}"
        if self.current_match:
            detail += f"\nCurrent map: {self.current_match['name']}"
        self.overlay_detail.configure(text=detail)

    def toggle_overlay(self):
        self.cfg["overlay"]["enabled"] = not bool(self.cfg["overlay"].get("enabled"))
        save_config(self.cfg, force_overlay=True)
        self.update_overlay()
        self.render_overlay_state()
        self.render_home_state()

    def toggle_overlay_drag_mode(self):
        self.cfg["overlay"]["dragMode"] = not bool(self.cfg["overlay"].get("dragMode"))
        save_config(self.cfg, force_overlay=True)
        self.update_overlay()
        self.render_overlay_state()
        self.render_home_state()

    def set_overlay_position(self, position):
        allowed = {"top-left", "top-right", "bottom-left", "bottom-right"}
        self.cfg["overlay"]["position"] = position if position in allowed else "top-left"
        self.cfg["overlay"]["side"] = "left" if "left" in self.cfg["overlay"]["position"] else "right"
        self.cfg["overlay"]["customPosition"] = False
        self.cfg["overlay"]["customX"] = None
        self.cfg["overlay"]["customY"] = None
        save_config(self.cfg, force_overlay=True)
        self.update_overlay(force_recreate=True)
        self.render_overlay_state()
        self.render_home_state()

    def select_area(self, kind, frozen=False):
        if self.area_selector_open:
            return
        self.area_selector_open = True
        selection_bounds = find_dbd_window_bounds()
        if selection_bounds:
            screen_x = int(selection_bounds["x"])
            screen_y = int(selection_bounds["y"])
            width = int(selection_bounds["width"])
            height = int(selection_bounds["height"])
            selector_scope = "DBD window"
        else:
            screen_x = 0
            screen_y = 0
            width = self.root.winfo_screenwidth()
            height = self.root.winfo_screenheight()
            selector_scope = "screen"
        frozen_photo = None
        freeze_screen = frozen or kind in {"trigger", "text"}
        if freeze_screen:
            try:
                with mss.MSS() as sct:
                    shot = sct.grab({"left": screen_x, "top": screen_y, "width": width, "height": height})
                frozen_image = Image.frombytes("RGB", (shot.width, shot.height), shot.rgb)
                frozen_photo = ImageTk.PhotoImage(frozen_image)
            except Exception as exc:
                self.log(f"Could not freeze screen for selector: {exc}")

        self.detector.stop()
        self.skill_detector.stop()
        self.skill_debug_overlay.close()
        self.set_pill(self.run_pill, "Map: off", "stop")
        self.set_pill(self.skill_global_pill, "Skill: off", "stop")
        self.set_pill(self.skill_pill, "Stopped", "stop")
        selector = Toplevel(self.root)
        selector.overrideredirect(True)
        selector.attributes("-topmost", True)
        selector.attributes("-alpha", 1.0 if frozen_photo else 0.28)
        selector.configure(bg="black")
        selector.geometry(f"{width}x{height}+{screen_x}+{screen_y}")
        selector.focus_force()

        background = None
        if frozen_photo:
            self.selector_photo = frozen_photo
            background = Label(selector, image=self.selector_photo, borderwidth=0)
            background.place(x=0, y=0, width=width, height=height)
        else:
            self.selector_photo = None

        def close_selector():
            self.area_selector_open = False
            self.selector_photo = None
            if selector.winfo_exists():
                selector.destroy()

        hint = Label(
            selector,
            text={
                "trigger": "Drag around the trigger image.",
                "text": "Drag around the OCR text area.",
                "skill": "Frozen screen: drag around the skill-check circle.",
            }.get(kind, "Drag around the area.") + f" ({selector_scope})",
            bg="#000000",
            fg="#ffffff",
            font=("Segoe UI", 14, "bold"),
            padx=12,
            pady=8,
        )
        hint.place(relx=0.5, y=24, anchor="n")
        rect = Frame(selector, bg="#34d7ff")
        drag = {"start": None, "active": False}
        pending = {"box": None}

        confirm_panel = Frame(selector, bg="#151d29", highlightthickness=1, highlightbackground="#56d0ff", padx=12, pady=10)
        confirm_text = Label(
            confirm_panel,
            text="",
            bg="#151d29",
            fg="#edf2f7",
            font=("Consolas", 10),
            justify="left",
        )
        confirm_text.pack(fill="x", pady=(0, 8))
        confirm_buttons = Frame(confirm_panel, bg="#151d29")
        confirm_buttons.pack(fill="x")

        def draw(a, b):
            x = min(a[0], b[0])
            y = min(a[1], b[1])
            w = abs(a[0] - b[0])
            h = abs(a[1] - b[1])
            rect.place(x=x - screen_x, y=y - screen_y, width=max(w, 2), height=max(h, 2))

        def commit_box(box):
            if not box:
                return
            stored_box = make_dbd_relative_box(box)
            if kind == "trigger":
                self.cfg["imageTriggerBox"] = stored_box
                self.detector.template = None
                save_config(self.cfg)
                self.refresh_area_labels()
                self.root.after(300, self.recapture_trigger)
                self.log(f"Trigger area applied: {stored_box}")
            elif kind == "text":
                self.cfg["textBox"] = stored_box
                save_config(self.cfg)
                self.refresh_area_labels()
                self.log(f"Text area applied: {stored_box}")
            elif kind == "skill":
                self.cfg["skillCheck"]["box"] = stored_box
                save_config(self.cfg)
                self.refresh_area_labels()
                self.log(f"Skill check area applied: {stored_box}")

        def apply_selection():
            box = pending["box"]
            close_selector()
            commit_box(box)

        def cancel_selection():
            close_selector()
            self.log("Area selection canceled.")

        self.button(confirm_buttons, "Apply", apply_selection, "primary").pack(side="left", padx=(0, 8))
        self.button(confirm_buttons, "Cancel", cancel_selection, "danger").pack(side="left")

        def event_is_on_confirm_panel(event):
            widget = getattr(event, "widget", None)
            while widget:
                if widget == confirm_panel:
                    return True
                try:
                    widget = widget.master
                except Exception:
                    return False
            return False

        def show_confirmation(box):
            pending["box"] = box
            drag["start"] = None
            drag["active"] = False
            confirm_text.configure(
                text=f"Selected area\nX {box['x']}  Y {box['y']}\nW {box['width']}  H {box['height']}"
            )
            panel_x = min(max(box["x"] - screen_x, 12), max(12, width - 260))
            panel_y = min(max(box["y"] - screen_y + box["height"] + 10, 72), max(72, height - 130))
            confirm_panel.place(x=panel_x, y=panel_y, width=248)
            hint.configure(text="Review the selected area, then Apply or Cancel.")

        def start_drag(event):
            if event_is_on_confirm_panel(event):
                return "break"
            if pending["box"]:
                pending["box"] = None
                confirm_panel.place_forget()
                rect.place_forget()
            drag["start"] = (event.x_root, event.y_root)
            drag["active"] = True
            draw(drag["start"], drag["start"])
            hint.configure(text="Drag to resize the blue area, then release.")

        def update_drag(event):
            if event_is_on_confirm_panel(event):
                return "break"
            if drag["active"] and drag["start"]:
                draw(drag["start"], (event.x_root, event.y_root))

        def finish_drag(event):
            if event_is_on_confirm_panel(event):
                return "break"
            if not drag["active"] or not drag["start"]:
                return
            drag["active"] = False
            a = drag["start"]
            point = (event.x_root, event.y_root)
            box = clean_box({
                "x": min(a[0], point[0]),
                "y": min(a[1], point[1]),
                "width": abs(a[0] - point[0]),
                "height": abs(a[1] - point[1]),
            })
            if not box:
                drag["start"] = None
                rect.place_forget()
                hint.configure(text="Area was too small. Drag again, or press Escape to cancel.")
                return
            draw((box["x"], box["y"]), (box["x"] + box["width"], box["y"] + box["height"]))
            show_confirmation(box)

        for widget in (selector, background, hint, rect):
            if widget:
                widget.bind("<ButtonPress-1>", start_drag)
                widget.bind("<B1-Motion>", update_drag)
                widget.bind("<ButtonRelease-1>", finish_drag)
                widget.bind("<Escape>", lambda _event: cancel_selection())
        selector.bind("<Escape>", lambda _event: cancel_selection())

    def recapture_trigger(self):
        box = self.cfg.get("imageTriggerBox")
        if not box:
            messagebox.showinfo("Trigger area", "Set the trigger area first.")
            return
        with mss.MSS() as sct:
            rgb, width, height = self.detector.capture_box(sct, box)
        ASSET_DIR.mkdir(parents=True, exist_ok=True)
        Image.frombytes("RGB", (width, height), rgb).save(TEMPLATE_PATH)
        self.detector.template = None
        self.log(f"Saved trigger image: {TEMPLATE_PATH}")

    def on_close(self):
        self.detector.stop()
        self.skill_detector.stop()
        self.auto_sprint.stop()
        self.skill_debug_overlay.close()
        self.overlay.close()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def self_test():
    cfg = load_config()
    detector = Detector(cfg, lambda _event: None)
    if not TEMPLATE_PATH.exists():
        print("No trigger template exists:", TEMPLATE_PATH)
        return 1
    detector.template = None
    template = detector.load_template()
    with mss.MSS() as sct:
        visible, reason = detector.detect_trigger(sct)
    print(json.dumps({
        "template": {"width": template.width, "height": template.height, "foregroundRatio": template.foreground_ratio},
        "currentScreenVisible": visible,
        "reason": reason,
        "tesseract": detector.tesseract,
    }, indent=2))
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    App().run()
