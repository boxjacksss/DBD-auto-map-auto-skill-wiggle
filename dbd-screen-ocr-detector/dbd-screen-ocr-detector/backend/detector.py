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
from tkinter import BOTH, END, LEFT, RIGHT, Y, Button, Canvas, Entry, Frame, Label, Listbox, Scrollbar, Text, Tk, Toplevel, messagebox, ttk

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
OCR_QUEUE_MAX = 24

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
        "saveDebugImages": False,
        "whiteMin": 185,
        "whiteSpreadMax": 90,
        "redMin": 150,
        "redOtherMax": 150,
        "hitTolerancePx": 2,
        "angleToleranceDeg": 8,
        "hitDepthPercent": 25,
        "hitWindowEndPercent": 92,
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
    "terrorRadius": {
        "enabled": False,
        "box": {"x": 840, "y": 390, "width": 240, "height": 240},
        "scanMs": 50,
        "radiusMeters": 32,
        "redMin": 115,
        "redDominance": 28,
        "minRedPixels": 10,
        "fullRedPercent": 8,
        "pulseThreshold": 8,
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
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
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
    skill["screenDebugOverlay"] = bool(skill.get("screenDebugOverlay", defaults["screenDebugOverlay"]))
    skill["saveDebugImages"] = bool(skill.get("saveDebugImages", defaults["saveDebugImages"]))
    skill["whiteMin"] = max(120, min(255, int(float(skill_value("whiteMin")))))
    skill["whiteSpreadMax"] = max(10, min(160, int(float(skill_value("whiteSpreadMax")))))
    skill["redMin"] = max(80, min(255, int(float(skill_value("redMin")))))
    skill["redOtherMax"] = max(0, min(220, int(float(skill_value("redOtherMax")))))
    skill["hitTolerancePx"] = max(0, min(20, int(float(skill_value("hitTolerancePx")))))
    skill["angleToleranceDeg"] = max(1, min(45, int(float(skill_value("angleToleranceDeg")))))
    skill["hitDepthPercent"] = max(0, min(95, int(float(skill_value("hitDepthPercent")))))
    skill["hitWindowEndPercent"] = max(skill["hitDepthPercent"], min(100, int(float(skill_value("hitWindowEndPercent")))))
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
    terror = cfg.get("terrorRadius") or {}
    terror_defaults = DEFAULT_CONFIG["terrorRadius"]

    def terror_value(key):
        value = terror.get(key)
        return terror_defaults[key] if value is None or value == "" else value

    terror["box"] = clean_box(terror.get("box")) or terror_defaults["box"]
    terror["enabled"] = bool(terror.get("enabled", terror_defaults["enabled"]))
    terror["scanMs"] = max(25, min(1000, int(float(terror_value("scanMs")))))
    terror["radiusMeters"] = max(8, min(80, int(float(terror_value("radiusMeters")))))
    terror["redMin"] = max(40, min(255, int(float(terror_value("redMin")))))
    terror["redDominance"] = max(0, min(160, int(float(terror_value("redDominance")))))
    terror["minRedPixels"] = max(1, min(1000, int(float(terror_value("minRedPixels")))))
    terror["fullRedPercent"] = max(1, min(80, int(float(terror_value("fullRedPercent")))))
    terror["pulseThreshold"] = max(1, min(80, int(float(terror_value("pulseThreshold")))))
    cfg["terrorRadius"] = terror
    return cfg


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


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
    import ctypes

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
        vk_scan = ctypes.windll.user32.VkKeyScanW(ord(value))
        if vk_scan == -1:
            raise RuntimeError(f"Unsupported key: {input_name}")
        vk = vk_scan & 0xFF
    if vk is None:
        raise RuntimeError(f"Unsupported key: {input_name}")
    return vk


def activate_windows_input(input_name):
    if os.name != "nt":
        raise RuntimeError("Auto input is only supported on Windows.")
    import ctypes

    value = str(input_name or "").strip().lower()
    mouse_inputs = {
        "mouse1": (0x0002, 0x0004, 0),
        "m1": (0x0002, 0x0004, 0),
        "left": (0x0002, 0x0004, 0),
        "leftclick": (0x0002, 0x0004, 0),
        "left click": (0x0002, 0x0004, 0),
        "mouse2": (0x0008, 0x0010, 0),
        "m2": (0x0008, 0x0010, 0),
        "right": (0x0008, 0x0010, 0),
        "rightclick": (0x0008, 0x0010, 0),
        "right click": (0x0008, 0x0010, 0),
        "mouse3": (0x0020, 0x0040, 0),
        "m3": (0x0020, 0x0040, 0),
        "middle": (0x0020, 0x0040, 0),
        "middleclick": (0x0020, 0x0040, 0),
        "middle click": (0x0020, 0x0040, 0),
        "mouse4": (0x0080, 0x0100, 0x0001),
        "m4": (0x0080, 0x0100, 0x0001),
        "x1": (0x0080, 0x0100, 0x0001),
        "back": (0x0080, 0x0100, 0x0001),
        "mouse5": (0x0080, 0x0100, 0x0002),
        "m5": (0x0080, 0x0100, 0x0002),
        "x2": (0x0080, 0x0100, 0x0002),
        "forward": (0x0080, 0x0100, 0x0002),
    }
    if value in mouse_inputs:
        down, up, data = mouse_inputs[value]
        ctypes.windll.user32.mouse_event(down, 0, 0, data, 0)
        ctypes.windll.user32.mouse_event(up, 0, 0, data, 0)
        return

    vk = windows_virtual_key(value)
    scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
    ctypes.windll.user32.keybd_event(vk, scan, 0, 0)
    ctypes.windll.user32.keybd_event(vk, scan, 0x0002, 0)


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
        self.white_candidate = set()
        self.white_angle_candidate = set()
        self.white_candidate_since = 0
        self.last_debug_at = 0
        self.last_visual_emit_at = 0
        self.debug_capture_id = 0
        self.debug_location_logged = False
        self.geometry_cache_key = None
        self.geometry_cache = None
        self.last_red_angle = None
        self.last_red_seen_at = 0
        self.red_direction = 1

    def reset_skill_state(self):
        self.white_history = set()
        self.white_angle_history = set()
        self.white_hit_angles = set()
        self.white_hit_mask = set()
        self.white_hit_tolerance = None
        self.white_zones = []
        self.hit_zone_ids = set()
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

    def angle_progress(self, zone, angle):
        zone_min = float(zone.get("unwrappedMin", 0))
        zone_max = float(zone.get("unwrappedMax", zone_min + 1))
        span = max(1.0, zone_max - zone_min)
        candidates = [angle - 720, angle - 360, angle, angle + 360, angle + 720]
        value = min(
            candidates,
            key=lambda item: 0 if zone_min <= item <= zone_max else min(abs(item - zone_min), abs(item - zone_max)),
        )
        progress = (value - zone_min) / span
        if self.red_direction < 0:
            progress = 1 - progress
        return progress

    def update_red_direction(self, red_ring_points):
        now = time.perf_counter()
        if not red_ring_points:
            if self.last_red_seen_at and now - self.last_red_seen_at > 0.25:
                self.last_red_angle = None
            return
        sin_total = sum(math.sin(math.radians(angle)) for _x, _y, angle in red_ring_points)
        cos_total = sum(math.cos(math.radians(angle)) for _x, _y, angle in red_ring_points)
        if not sin_total and not cos_total:
            return
        current = (math.degrees(math.atan2(sin_total, cos_total)) + 360) % 360
        if self.last_red_seen_at and now - self.last_red_seen_at > 0.25:
            self.last_red_angle = None
        if self.last_red_angle is not None:
            delta = ((current - self.last_red_angle + 540) % 360) - 180
            if 1 <= abs(delta) <= 90:
                self.red_direction = 1 if delta > 0 else -1
        self.last_red_angle = current
        self.last_red_seen_at = now

    def log(self, message):
        self.emit(("log", message))

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.last_press_at = 0
        self.reset_skill_state()
        self.last_debug_at = 0
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
        max_radial_span = max(max_radial_span_setting, min(width, height) * 0.09)
        for zone_id, run in enumerate(self.contiguous_angle_runs(self.white_angle_history)):
            zone_angles = set(run)
            unwrapped_run = self.unwrap_angle_run(run)
            unwrapped_min = min(unwrapped_run) if unwrapped_run else 0
            unwrapped_max = max(unwrapped_run) if unwrapped_run else unwrapped_min
            zone_hit_angles = set()
            for angle in zone_angles:
                for delta in range(-angle_tolerance, angle_tolerance + 1):
                    zone_hit_angles.add((angle + delta) % 360)
            zone_points = {point for point in self.white_history if angle_by_point.get(point) in zone_angles}
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
            if len(zone_points) >= min_zone_pixels and radial_span <= max_radial_span:
                self.white_zones.append({
                    "id": zone_id,
                    "angles": zone_angles,
                    "hitAngles": zone_hit_angles,
                    "points": zone_points,
                    "mask": zone_mask,
                    "middleMask": middle_mask,
                    "radialMin": radial_min,
                    "radialMax": radial_max,
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
        hit_depth = int(cfg.get("hitDepthPercent", DEFAULT_CONFIG["skillCheck"]["hitDepthPercent"])) / 100
        hit_window_end = int(cfg.get("hitWindowEndPercent", DEFAULT_CONFIG["skillCheck"]["hitWindowEndPercent"])) / 100
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
            return False, 0, 0, set(), [], red_all_points, None, 0, 0

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

        if len(white_zone_points) >= min_white and white_angle_bins and len(self.white_history) < min_white:
            if not self.white_candidate:
                self.white_candidate = white_zone_points
                self.white_angle_candidate = white_angle_bins
                self.white_candidate_since = now
            else:
                overlap = len(white_angle_bins & self.white_angle_candidate)
                smaller = max(1, min(len(white_angle_bins), len(self.white_angle_candidate)))
                if overlap / smaller < 0.25:
                    self.white_candidate = white_zone_points
                    self.white_angle_candidate = white_angle_bins
                    self.white_candidate_since = now
                else:
                    self.white_candidate = white_zone_points
                    self.white_angle_candidate = white_angle_bins
            if now - self.white_candidate_since >= white_stable_seconds:
                self.set_learned_white_zone(self.white_candidate, self.white_angle_candidate, width, height, hit_tolerance)
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
        active_zone_points = {}
        for x, y, red_angle in red_ring_points:
            for zone in self.white_zones:
                red_is_on_white = (x, y) in zone["middleMask"]
                red_is_in_white_angle = red_angle in zone["hitAngles"]
                red_progress = self.angle_progress(zone, red_angle)
                red_is_in_hit_window = hit_depth <= red_progress <= hit_window_end
                if red_is_on_white and red_is_in_white_angle and red_is_in_hit_window:
                    zone_id = zone["id"]
                    active_zone_counts[zone_id] = active_zone_counts.get(zone_id, 0) + 1
                    active_zone_points.setdefault(zone_id, []).append((x, y))
                    break

        active_zone_ids = {zone_id for zone_id, count in active_zone_counts.items() if count >= min_red}
        for zone_id in list(self.hit_zone_ids):
            if zone_id not in active_zone_ids:
                self.hit_zone_ids.discard(zone_id)

        for zone_id, count in active_zone_counts.items():
            if zone_id in self.hit_zone_ids:
                continue
            if count > best_zone_count:
                best_zone_count = count
                hit_zone_id = zone_id
        if hit_zone_id is not None:
            red_zone_points = active_zone_points.get(hit_zone_id, [])
        hit = hit_zone_id is not None and best_zone_count >= min_red
        return hit, len(white_zone_points), len(red_zone_points), white_zone_points, red_zone_points, red_all_points, hit_zone_id, len(self.white_zones), len(self.hit_zone_ids)

    def build_highlight_preview(self, rgb, width, height, white_points, red_zone_points, red_all_points):
        image = Image.frombytes("RGB", (width, height), rgb).convert("RGBA")
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        def mark(points, color, radius):
            for x, y in points:
                draw.rectangle((x - radius, y - radius, x + radius, y + radius), fill=color)

        middle_points = set()
        for zone in self.white_zones:
            middle_points.update(zone.get("middleMask", set()))
        mark(self.white_history, (64, 220, 255, 90), 1)
        mark(middle_points, (64, 255, 220, 170), 1)
        mark(white_points, (255, 255, 255, 190), 1)
        mark(red_all_points, (255, 160, 0, 155), 1)
        mark(red_zone_points, (255, 0, 0, 235), 2)
        return Image.alpha_composite(image, overlay).convert("RGB").tobytes()

    def build_screen_debug_overlay(self, width, height, white_points, red_zone_points, red_all_points):
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        def mark(points, color, radius):
            for x, y in points:
                draw.rectangle((x - radius, y - radius, x + radius, y + radius), fill=color)

        radius_by_point = (self.geometry_cache or {}).get("radiusByPoint", {})
        boundary_points = set()
        for zone in self.white_zones:
            mid = float(zone.get("radialMid") or 0)
            half = float(zone.get("middleHalfSpan") or 1.5)
            for point in zone.get("middleMask", set()):
                radius = radius_by_point.get(point)
                if radius is None:
                    continue
                if abs(abs(radius - mid) - half) <= 0.75:
                    boundary_points.add(point)

        # Sparse, high-saturation non-white/non-red colors avoid feeding back into
        # detection if Windows includes the overlay in screen capture.
        mark(boundary_points, (45, 255, 220, 190), 0)
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
        if not hit and len(white_points) < min_white:
            return
        if not hit and now - self.last_debug_at < 0.1:
            return
        self.last_debug_at = now
        self.debug_capture_id += 1
        SKILL_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        raw_image = Image.frombytes("RGB", (width, height), rgb)
        mask = Image.new("RGB", (width, height), "#05070a")
        mask_pixels = mask.load()
        for x, y in self.white_history:
            if 0 <= x < width and 0 <= y < height:
                mask_pixels[x, y] = (30, 120, 150)
        for zone in self.white_zones:
            for x, y in zone.get("middleMask", set()):
                if 0 <= x < width and 0 <= y < height:
                    mask_pixels[x, y] = (80, 255, 220)
        for x, y in white_points:
            mask_pixels[x, y] = (255, 255, 255)
        for x, y in red_all_points:
            mask_pixels[x, y] = (255, 160, 0)
        for x, y in red_zone_points:
            mask_pixels[x, y] = (255, 0, 0)

        latest_raw = SKILL_DEBUG_DIR / "latest-raw.png"
        latest_mask = SKILL_DEBUG_DIR / "latest-mask.png"
        self.save_image_atomic(raw_image, latest_raw)
        self.save_image_atomic(mask, latest_mask)
        if hit:
            millis = int((now % 1) * 1000)
            stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{millis:03d}"
            self.save_image_atomic(raw_image, SKILL_DEBUG_DIR / f"{stamp}-hit-raw.png")
            self.save_image_atomic(mask, SKILL_DEBUG_DIR / f"{stamp}-hit-mask.png")
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
                        hit_zone_count = len(self.hit_zone_ids)
                        self.emit(("skill-hit", f"Pressed {cfg.get('pressKey') or 'c'} ({hit_zone_count}/{zone_count} zones)"))
                    self.save_debug_images(rgb, width, height, white_points, red_zone_points, red_all_points, can_press)
                    emit_visual = can_press or time.perf_counter() - self.last_visual_emit_at >= 0.075
                    if emit_visual:
                        self.last_visual_emit_at = time.perf_counter()
                        armed = len(self.white_history) >= int(cfg["minWhitePixels"])
                        preview_rgb = self.build_highlight_preview(rgb, width, height, white_points, red_zone_points, red_all_points)
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
                        self.emit(("skill-score", f"white now {white_count}, remembered {len(self.white_history)}, zones {hit_zone_count}/{zone_count}, red in white {red_count}, red total {len(red_all_points) if armed else 0}"))
                        if hit and not can_press:
                            self.emit(("skill-state", "NOW: red in a learned white zone that was already pressed."))
                        else:
                            if armed:
                                self.emit(("skill-state", f"NOW: white learned; waiting for red inside it ({hit_zone_count}/{zone_count} zones hit)."))
                            else:
                                self.emit(("skill-state", "NOW: looking for white success zone."))
                    scan_ms = int(cfg["scanMs"])
                    if scan_ms > 1:
                        self.stop_event.wait(scan_ms / 1000)
                except Exception as exc:
                    self.emit(("skill-state", str(exc)))
                    self.log(f"Skill check error: {exc}")
                    self.stop_event.wait(1)


class TerrorRadiusDetector:
    def __init__(self, cfg, emit):
        self.cfg = cfg
        self.emit = emit
        self.stop_event = threading.Event()
        self.thread = None
        self.smoothed_strength = 0.0
        self.last_strength = 0.0
        self.last_peak_at = 0.0
        self.beat_times = []
        self.heart_center = None
        self.heart_center_full = None
        self.frame_index = 0
        self.last_visual_emit_at = 0.0
        self.last_score_emit_at = 0.0

    def log(self, message):
        self.emit(("log", message))

    def reset_state(self):
        self.smoothed_strength = 0.0
        self.last_strength = 0.0
        self.last_peak_at = 0.0
        self.beat_times = []
        self.heart_center = None
        self.heart_center_full = None
        self.frame_index = 0
        self.last_visual_emit_at = 0.0
        self.last_score_emit_at = 0.0

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.reset_state()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        self.log("Terror radius watcher started. It captures only the selected visual-heart area.")

    def stop(self):
        self.stop_event.set()
        self.reset_state()
        self.log("Terror radius watcher stopped.")

    def capture_box(self, sct, box):
        box = resolve_screen_box(box)
        if not box:
            raise RuntimeError("Selected terror-radius area is not valid.")
        region = {
            "left": int(box["x"]),
            "top": int(box["y"]),
            "width": int(box["width"]),
            "height": int(box["height"]),
        }
        shot = sct.grab(region)
        return shot.rgb, shot.width, shot.height, 0, 0

    def scan_red_candidates(self, rgb, width, height, roi=None, step=1):
        cfg = self.cfg["terrorRadius"]
        red_min = int(cfg["redMin"])
        red_dominance = int(cfg["redDominance"])
        if roi:
            start_x, start_y, end_x, end_y = roi
            start_x = max(0, min(width - 1, int(start_x)))
            start_y = max(0, min(height - 1, int(start_y)))
            end_x = max(start_x + 1, min(width, int(end_x)))
            end_y = max(start_y + 1, min(height, int(end_y)))
        else:
            start_x, start_y, end_x, end_y = 0, 0, width, height

        candidates = []
        score_total = 0.0
        sx = 0.0
        sy = 0.0
        for y in range(start_y, end_y, step):
            row = y * width * 3
            for x in range(start_x, end_x, step):
                i = row + x * 3
                r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
                dominance = r - max(g, b)
                if r >= red_min and dominance >= red_dominance:
                    score = (dominance / 255) * (r / 255)
                    candidates.append((x, y, score))
                    score_total += score
                    sx += x * score
                    sy += y * score

        if not candidates:
            return [], 0.0, None
        total = max(0.001, score_total)
        return candidates, score_total, (sx / total, sy / total)

    def estimate_heart_center(self, candidates, width, height):
        if not candidates:
            return None
        bin_size = max(6, int(min(width, height) * 0.045))
        bins = {}
        for x, y, score in candidates:
            key = (int(x // bin_size), int(y // bin_size))
            bins[key] = bins.get(key, 0.0) + score
        best_key = max(bins, key=bins.get)
        seed_x = (best_key[0] + 0.5) * bin_size
        seed_y = (best_key[1] + 0.5) * bin_size
        core_radius = max(10, min(width, height) * 0.16)
        sx = sy = total = 0.0
        for x, y, score in candidates:
            if (x - seed_x) ** 2 + (y - seed_y) ** 2 <= core_radius ** 2:
                sx += x * score
                sy += y * score
                total += score
        if total <= 0:
            return seed_x, seed_y
        return sx / total, sy / total

    def analyze(self, rgb, width, height, offset_x=0, offset_y=0):
        cfg = self.cfg["terrorRadius"]
        min_red = int(cfg["minRedPixels"])
        full_red_fraction = max(0.01, int(cfg["fullRedPercent"]) / 100)
        pulse_threshold = int(cfg["pulseThreshold"]) / 100
        radius_meters = int(cfg["radiusMeters"])
        min_dim = max(1, min(width, height))
        area = max(1, width * height)

        self.frame_index += 1
        if self.heart_center_full:
            local_x = self.heart_center_full[0] - offset_x
            local_y = self.heart_center_full[1] - offset_y
            if 0 <= local_x < width and 0 <= local_y < height:
                self.heart_center = (local_x, local_y)
            elif self.frame_index % 10 == 0:
                self.heart_center = None

        use_full_scan = self.heart_center is None or self.frame_index % 10 == 0
        scan_step = 2 if area > 50000 else 1
        roi = None
        if not use_full_scan and self.heart_center:
            cx, cy = self.heart_center
            follow_radius = max(48, min_dim * 0.42)
            roi = (cx - follow_radius, cy - follow_radius, cx + follow_radius, cy + follow_radius)

        candidates, red_score_total, weighted_center = self.scan_red_candidates(rgb, width, height, roi=roi, step=1)
        if len(candidates) < min_red and roi:
            candidates, red_score_total, weighted_center = self.scan_red_candidates(rgb, width, height, step=scan_step)

        red_count = len(candidates)
        estimated_center = self.estimate_heart_center(candidates, width, height) or weighted_center
        if estimated_center:
            if self.heart_center:
                old_x, old_y = self.heart_center
                self.heart_center = (old_x * 0.62 + estimated_center[0] * 0.38, old_y * 0.62 + estimated_center[1] * 0.38)
            else:
                self.heart_center = estimated_center
            self.heart_center_full = (offset_x + self.heart_center[0], offset_y + self.heart_center[1])

        heart_seen = red_count >= min_red and self.heart_center is not None
        core_radius = max(9, min_dim * 0.15)
        string_outer_radius = max(core_radius + 12, min_dim * 0.46)
        string_points = []
        heart_points = []
        string_score_total = 0.0
        if heart_seen:
            cx, cy = self.heart_center
            core_sq = core_radius ** 2
            outer_sq = string_outer_radius ** 2
            for x, y, score in candidates:
                dist_sq = (x - cx) ** 2 + (y - cy) ** 2
                if dist_sq <= core_sq:
                    heart_points.append((x, y))
                elif dist_sq <= outer_sq:
                    string_points.append((x, y))
                    string_score_total += score

        string_count = len(string_points)
        raw_strength = 0.0
        strings_seen = heart_seen and string_count >= min_red
        if strings_seen:
            average_string_score = string_score_total / string_count if string_count else 0.0
            string_target = max(min_red * 5, int(min_dim * max(0.35, full_red_fraction * 4)))
            coverage_strength = min(1.0, string_count / string_target)
            color_strength = min(1.0, average_string_score / 0.55)
            raw_strength = (coverage_strength * 0.7) + (color_strength * 0.3)

        alpha = 0.42 if raw_strength >= self.smoothed_strength else 0.24
        self.smoothed_strength = (self.smoothed_strength * (1 - alpha)) + (raw_strength * alpha)
        if not strings_seen and self.smoothed_strength < 0.03:
            self.smoothed_strength = 0.0

        now = time.perf_counter()
        beat = False
        if strings_seen and self.smoothed_strength >= pulse_threshold:
            rising = self.smoothed_strength - self.last_strength
            if rising >= max(0.02, pulse_threshold * 0.25) and now - self.last_peak_at >= 0.24:
                beat = True
                self.last_peak_at = now
                self.beat_times.append(now)
                self.beat_times = self.beat_times[-8:]
        self.last_strength = self.smoothed_strength

        bpm = 0
        if len(self.beat_times) >= 2:
            intervals = [b - a for a, b in zip(self.beat_times, self.beat_times[1:]) if b > a]
            if intervals:
                bpm = int(round(60 / (sum(intervals) / len(intervals))))

        normalized = max(0.0, min(1.0, self.smoothed_strength))
        estimated_distance = radius_meters * (1 - normalized) if strings_seen else None
        if not heart_seen:
            layer = "Outside"
            distance_label = f">{radius_meters}m or hidden"
        elif not strings_seen:
            layer = "Heart"
            distance_label = "watching strings"
        elif normalized < 0.34:
            layer = "Far"
            distance_label = f"{int(round(radius_meters * 2 / 3))}-{radius_meters}m"
        elif normalized < 0.67:
            layer = "Near"
            distance_label = f"{int(round(radius_meters / 3))}-{int(round(radius_meters * 2 / 3))}m"
        else:
            layer = "Close"
            distance_label = f"0-{int(round(radius_meters / 3))}m"

        return {
            "detected": heart_seen,
            "stringsSeen": strings_seen,
            "beat": beat,
            "redCount": red_count,
            "heartCount": len(heart_points),
            "stringCount": string_count,
            "rawStrength": raw_strength,
            "strength": normalized,
            "bpm": bpm,
            "layer": layer,
            "radiusMeters": radius_meters,
            "estimatedDistance": estimated_distance,
            "distanceLabel": distance_label,
            "heartCenter": self.heart_center,
            "heartPoints": heart_points,
            "stringPoints": string_points,
        }

    def build_preview(self, rgb, width, height, heart_center, heart_points, string_points):
        image = Image.frombytes("RGB", (width, height), rgb).convert("RGBA")
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for x, y in heart_points:
            draw.point((x, y), fill=(255, 210, 60, 180))
        for x, y in string_points:
            draw.rectangle((x - 1, y - 1, x + 1, y + 1), fill=(255, 35, 35, 210))
        if heart_center:
            cx, cy = heart_center
            radius = max(6, min(width, height) * 0.15)
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(255, 210, 60, 220), width=2)
        return Image.alpha_composite(image, overlay).convert("RGB").tobytes()

    def run(self):
        with mss.MSS() as sct:
            while not self.stop_event.is_set():
                try:
                    cfg = self.cfg["terrorRadius"]
                    box = cfg.get("box")
                    if not box:
                        self.emit(("terror-state", "No terror-radius area set."))
                        self.stop_event.wait(0.5)
                        continue

                    rgb, width, height, offset_x, offset_y = self.capture_box(sct, box)
                    result = self.analyze(rgb, width, height, offset_x, offset_y)
                    now = time.perf_counter()
                    include_preview = result["beat"] or now - self.last_visual_emit_at >= 0.12
                    if include_preview:
                        self.last_visual_emit_at = now
                        preview_rgb = self.build_preview(
                            rgb,
                            width,
                            height,
                            result["heartCenter"],
                            result["heartPoints"],
                            result["stringPoints"],
                        )
                        self.emit(("terror-visual", {
                            "detected": result["detected"],
                            "stringsSeen": result["stringsSeen"],
                            "beat": result["beat"],
                            "redCount": result["redCount"],
                            "heartCount": result["heartCount"],
                            "stringCount": result["stringCount"],
                            "strength": result["strength"],
                            "bpm": result["bpm"],
                            "layer": result["layer"],
                            "radiusMeters": result["radiusMeters"],
                            "estimatedDistance": result["estimatedDistance"],
                            "distanceLabel": result["distanceLabel"],
                            "rgb": preview_rgb,
                            "width": width,
                            "height": height,
                        }))
                    if result["beat"] or now - self.last_score_emit_at >= 0.2:
                        self.last_score_emit_at = now
                        if result["detected"]:
                            distance = result["estimatedDistance"]
                            distance_text = f"{distance:.1f}m" if distance is not None else result["distanceLabel"]
                            self.emit(("terror-score", f"{result['layer']} | approx {distance_text} | strings {result['stringCount']} | heart {result['heartCount']} | intensity {result['strength']:.2f} | bpm {result['bpm'] or '--'}"))
                            if result["stringsSeen"]:
                                self.emit(("terror-state", f"Terror strings detected: {result['layer']} ({result['distanceLabel']})."))
                            else:
                                self.emit(("terror-state", "Heart tracked; waiting for heartbeat strings."))
                        else:
                            self.emit(("terror-score", f"Outside or hidden | red {result['redCount']} | strings {result['stringCount']} | intensity {result['strength']:.2f}"))
                            self.emit(("terror-state", "No visual heartbeat heart detected."))
                    self.stop_event.wait(int(cfg["scanMs"]) / 1000)
                except Exception as exc:
                    self.emit(("terror-state", str(exc)))
                    self.log(f"Terror radius error: {exc}")
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
            result = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=10, cwd=PROJECT_DIR)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "Tesseract OCR failed.")
            return {
                "label": f"{label}/psm{psm}",
                "text": result.stdout.strip(),
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

    def read_text_candidates_from_image(self, image, raw_path=None):
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

        primary_variants = full_variants[:2]
        secondary_variants = full_variants[2:]
        for label, variant in primary_variants:
            candidate = self.run_tesseract(variant, label, 7)
            candidates.append(candidate)
            if match_map_name(candidate["text"]):
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
            recent_reasons = [ocr_noise_reason(item["text"]) for item in candidates[-2:]]
            if len(candidates) >= 2 and all(reason and reason != "no readable text" for reason in recent_reasons):
                return candidates

        for label, variant in secondary_variants:
            candidate = self.run_tesseract(variant, label, 7)
            candidates.append(candidate)
            if match_map_name(candidate["text"]):
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
        while True:
            try:
                work_queue.get_nowait()
                work_queue.task_done()
            except queue.Empty:
                break

    def process_ocr_job(self, job, work_queue=None):
        started = time.perf_counter()
        candidates = self.read_text_candidates_from_image(job["image"], job.get("raw_path"))
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
            save_config(self.cfg)
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
                self.set_overlay_hwnd_enabled(user32, hwnd, False)
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
            ws_ex_transparent = 0x00000020
            ws_ex_toolwindow = 0x00000080
            ws_ex_noactivate = 0x08000000
            swp_framechanged = 0x0020
            style = user32.GetWindowLongW(hwnd, gwl_exstyle)
            user32.SetWindowLongW(
                hwnd,
                gwl_exstyle,
                style | ws_ex_transparent | ws_ex_toolwindow | ws_ex_noactivate,
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
            httransparent = -1
            gwlp_wndproc = -4
            wndproc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
            set_window_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            call_window_proc = user32.CallWindowProcW
            set_window_long.restype = ctypes.c_void_p
            call_window_proc.restype = ctypes.c_ssize_t
            original = {"value": None}

            @wndproc_type
            def wndproc(window, message, wparam, lparam):
                if message == wm_nchittest:
                    return httransparent
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
        "bg": "#0f141c",
        "panel": "#151d29",
        "panel2": "#101722",
        "line": "#273344",
        "text": "#edf2f7",
        "muted": "#98a6b8",
        "accent": "#56d0ff",
        "accent2": "#8bd17c",
        "warn": "#ffd166",
        "danger": "#ff6b6b",
        "button": "#243246",
        "button_hover": "#2e4059",
    }

    def __init__(self):
        self.cfg = load_config()
        save_config(self.cfg)
        self.events = queue.Queue()
        self.detector = Detector(self.cfg, self.events.put)
        self.skill_detector = SkillCheckDetector(self.cfg, self.events.put)
        self.terror_detector = TerrorRadiusDetector(self.cfg, self.events.put)
        self.current_match = None
        self.map_library_entries = build_map_library_entries()
        self.selected_map_name = self.map_library_entries[0]["name"] if self.map_library_entries else None
        self.selected_image_paths = []
        self.selected_image_index = 0
        self.map_photo = None
        self.terror_preview_photo = None
        self.installing_ocr = False
        self.last_overlay_log = ""
        self.suppress_overlay_updates = False
        self.area_selector_open = False
        self.selector_photo = None

        self.root = Tk()
        self.root.title("DBD Screen OCR Detector")
        self.root.geometry("980x720")
        self.root.minsize(900, 640)
        self.root.configure(bg=self.COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.configure_style()
        self.build_ui()

        self.overlay = MapOverlay(self.root, self.cfg)
        self.skill_debug_overlay = SkillDebugOverlay(self.root, self.cfg)
        self.render_map_view()
        self.update_overlay()
        self.render_overlay_state()
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
        style.configure("TNotebook.Tab", background="#192231", foreground=self.COLORS["muted"], padding=(18, 9), borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", self.COLORS["panel"])], foreground=[("selected", self.COLORS["text"])])
        style.configure("Horizontal.TScale", background=self.COLORS["panel"], troughcolor=self.COLORS["panel2"])

    def build_ui(self):
        shell = Frame(self.root, bg=self.COLORS["bg"])
        shell.pack(fill=BOTH, expand=True, padx=18, pady=16)

        header = Frame(shell, bg=self.COLORS["bg"])
        header.pack(fill="x", pady=(0, 14))
        title_block = Frame(header, bg=self.COLORS["bg"])
        title_block.pack(side="left", fill="x", expand=True)
        Label(
            title_block,
            text="DBD Screen OCR Detector",
            bg=self.COLORS["bg"],
            fg=self.COLORS["text"],
            font=("Segoe UI", 22, "bold"),
        ).pack(anchor="w")
        Label(
            title_block,
            text="Region-only trigger watch, OCR after disappearance, click-through map overlay.",
            bg=self.COLORS["bg"],
            fg=self.COLORS["muted"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(3, 0))

        status_group = Frame(header, bg=self.COLORS["bg"])
        status_group.pack(side="right", padx=(12, 0))
        self.terror_global_pill = self.pill(status_group, "Terror: off", "stop")
        self.terror_global_pill.pack(side="right", padx=(8, 0))
        self.skill_global_pill = self.pill(status_group, "Skill: off", "stop")
        self.skill_global_pill.pack(side="right", padx=(8, 0))
        self.run_pill = self.pill(status_group, "Map: off", "stop")
        self.run_pill.pack(side="right")

        self.tabs = ttk.Notebook(shell)
        self.tabs.pack(fill=BOTH, expand=True)
        self.detector_tab = Frame(self.tabs, bg=self.COLORS["bg"])
        self.skill_tab = Frame(self.tabs, bg=self.COLORS["bg"])
        self.terror_tab = Frame(self.tabs, bg=self.COLORS["bg"])
        self.timing_tab = Frame(self.tabs, bg=self.COLORS["bg"])
        self.map_tab = Frame(self.tabs, bg=self.COLORS["bg"])
        self.overlay_tab = Frame(self.tabs, bg=self.COLORS["bg"])
        self.tabs.add(self.detector_tab, text="Map Detector")
        self.tabs.add(self.skill_tab, text="Skill Checks")
        self.tabs.add(self.terror_tab, text="Terror Radius")
        self.tabs.add(self.timing_tab, text="Timing Settings")
        self.tabs.add(self.map_tab, text="Map Viewer")
        self.tabs.add(self.overlay_tab, text="Overlay Settings")

        self.build_detector_tab()
        self.build_skill_tab()
        self.build_terror_tab()
        self.build_timing_tab()
        self.build_map_tab()
        self.build_overlay_tab()

    def build_detector_tab(self):
        grid = Frame(self.detector_tab, bg=self.COLORS["bg"])
        grid.pack(fill=BOTH, expand=True, pady=14)
        grid.grid_columnconfigure(0, weight=2)
        grid.grid_columnconfigure(1, weight=1)
        grid.grid_rowconfigure(1, weight=1)

        status_card = self.card(grid)
        status_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 12))
        self.card_title(status_card, "Watch Status")
        self.status = Label(status_card, text="Ready.", anchor="w", bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Segoe UI", 14, "bold"))
        self.status.pack(fill="x", pady=(6, 6))
        self.score = Label(status_card, text="No trigger score yet.", anchor="w", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Consolas", 10))
        self.score.pack(fill="x")

        controls = Frame(status_card, bg=self.COLORS["panel"])
        controls.pack(fill="x", pady=(16, 0))
        self.button(controls, "Enable Map Detector", self.start_detection, "primary").pack(side="left", padx=(0, 8))
        self.button(controls, "Disable", self.stop_detection, "danger").pack(side="left", padx=(0, 8))

        setup_card = self.card(grid)
        setup_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=(0, 12))
        self.card_title(setup_card, "Setup")
        self.boxes = Label(setup_card, text=self.box_summary(), anchor="w", justify="left", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Consolas", 9))
        self.boxes.pack(fill="x", pady=(6, 14))
        self.button(setup_card, "Set Trigger Area", lambda: self.select_area("trigger"), "primary").pack(fill="x", pady=(0, 8))
        self.button(setup_card, "Recapture Trigger", lambda: self.select_area("trigger")).pack(fill="x", pady=(0, 8))
        self.button(setup_card, "Set Text Area", lambda: self.select_area("text")).pack(fill="x", pady=(0, 8))
        self.button(setup_card, "Toggle OCR Debug Images", self.toggle_ocr_debug_images).pack(fill="x", pady=(0, 8))
        self.button(setup_card, "Clear Debug Images", self.clear_debug_images).pack(fill="x")

        ocr_card = self.card(grid)
        ocr_card.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        self.card_title(ocr_card, "OCR Output")
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
        self.card_title(log_card, "Log")
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
        body = Frame(self.skill_tab, bg=self.COLORS["bg"])
        body.pack(fill=BOTH, expand=True, pady=14)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        state = self.card(body)
        state.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.card_title(state, "Skill Check Watcher")
        self.skill_pill = self.pill(state, "Stopped", "stop")
        self.skill_pill.pack(anchor="w", pady=(8, 10))
        self.skill_status = Label(state, text="Ready.", anchor="w", bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Segoe UI", 14, "bold"))
        self.skill_status.pack(fill="x", pady=(6, 6))
        self.skill_score = Label(state, text="No scan yet.", anchor="w", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Consolas", 10))
        self.skill_score.pack(fill="x")
        now_row = Frame(state, bg=self.COLORS["panel"])
        now_row.pack(fill="x", pady=(12, 0))
        self.skill_white_pill = self.pill(now_row, "White: no", "stop")
        self.skill_white_pill.pack(side="left", padx=(0, 8))
        self.skill_zone_pill = self.pill(now_row, "Zones: 0/0", "stop")
        self.skill_zone_pill.pack(side="left", padx=(0, 8))
        self.skill_red_pill = self.pill(now_row, "Red in zone: no", "stop")
        self.skill_red_pill.pack(side="left", padx=(0, 8))
        self.skill_hit_pill = self.pill(now_row, "Hit: no", "stop")
        self.skill_hit_pill.pack(side="left")
        self.skill_preview_photo = None
        self.skill_preview = Label(state, text="Live preview will appear while watching.", bg=self.COLORS["panel2"], fg=self.COLORS["muted"], font=("Segoe UI", 10), compound="center")
        self.skill_preview.pack(fill=BOTH, expand=True, pady=(14, 0))
        self.skill_preview_legend = Label(
            state,
            text="Preview: white=current zone, cyan=armed middle band, orange=red needle, red=red inside middle band. Screen overlay uses sparse cyan boundaries and magenta hit dots.",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.skill_preview_legend.pack(fill="x", pady=(6, 0))
        self.skill_box_label = Label(state, text=self.skill_box_summary(), anchor="w", justify="left", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Consolas", 9))
        self.skill_box_label.pack(fill="x", pady=(12, 14))
        controls = Frame(state, bg=self.COLORS["panel"])
        controls.pack(fill="x")
        self.button(controls, "Enable Skill Checks", self.start_skill_checks, "primary").pack(side="left", padx=(0, 8))
        self.button(controls, "Disable", self.stop_skill_checks, "danger").pack(side="left")
        self.button(state, "Set Skill Check Area", lambda: self.select_area("skill", frozen=True), "primary").pack(fill="x", pady=(16, 8))
        self.button(state, "Toggle Screen Debug Overlay", self.toggle_skill_debug_overlay).pack(fill="x", pady=(0, 8))
        self.button(state, "Toggle Debug Image Saving", self.toggle_skill_debug_images).pack(fill="x", pady=(0, 8))
        self.button(state, "Open Debug Folder", self.open_skill_debug_folder).pack(fill="x")

        settings = self.card(body)
        settings.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.card_title(settings, "Skill Check Settings")
        Label(
            settings,
            text="Use a tight box around the skill-check circle. Smaller boxes are faster and more accurate.",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            wraplength=380,
            justify="left",
            font=("Segoe UI", 10),
        ).pack(fill="x", pady=(8, 8))

        self.skill_entries = {}
        self.skill_input_row(settings, "Press input", "pressKey", "", "", "")
        self.skill_input_row(settings, "White minimum", "whiteMin", 120, 255, "rgb")
        self.skill_input_row(settings, "White spread", "whiteSpreadMax", 10, 160, "rgb")
        self.skill_input_row(settings, "White zone size", "minWhitePixels", 1, 200, "px")
        self.skill_input_row(settings, "Single zone size", "minWhiteZonePixels", 1, 300, "px")
        self.skill_input_row(settings, "Zone thickness max", "maxWhiteZoneRadialSpan", 1, 80, "px")
        self.skill_input_row(settings, "Zone gap merge", "whiteAngleGapDeg", 0, 30, "deg")
        self.skill_input_row(settings, "White angle span", "minWhiteAngleSpan", 1, 90, "deg")
        self.skill_input_row(settings, "Ring evidence", "minRingOutlineBins", 0, 360, "deg")
        self.skill_input_row(settings, "Ring max fill", "maxRingOutlinePercent", 1, 100, "%")
        self.skill_input_row(settings, "Center prompt", "minCenterPromptPixels", 0, 2000, "px")
        self.skill_input_row(settings, "Center max", "maxCenterPromptPixels", 0, 5000, "px")
        self.skill_input_row(settings, "Red minimum", "redMin", 80, 255, "rgb")
        self.skill_input_row(settings, "Red other max", "redOtherMax", 0, 220, "rgb")
        self.skill_input_row(settings, "Hit tolerance", "hitTolerancePx", 0, 20, "px")
        self.skill_input_row(settings, "Angle tolerance", "angleToleranceDeg", 1, 45, "deg")
        self.skill_input_row(settings, "Hit depth", "hitDepthPercent", 0, 95, "%")
        self.skill_input_row(settings, "Hit window end", "hitWindowEndPercent", 0, 100, "%")
        self.skill_input_row(settings, "Red hit pixels", "minRedPixels", 1, 200, "px")
        self.skill_input_row(settings, "Ring inner", "ringInnerPercent", 0, 100, "%")
        self.skill_input_row(settings, "Ring outer", "ringOuterPercent", 1, 120, "%")
        self.button(settings, "Apply Skill Check Settings", self.apply_skill_settings, "primary").pack(fill="x", pady=(14, 0))

    def build_terror_tab(self):
        body = Frame(self.terror_tab, bg=self.COLORS["bg"])
        body.pack(fill=BOTH, expand=True, pady=14)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        state = self.card(body)
        state.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.card_title(state, "Terror Radius Distance")
        self.terror_pill = self.pill(state, "Stopped", "stop")
        self.terror_pill.pack(anchor="w", pady=(8, 10))
        self.terror_status = Label(state, text="Ready.", anchor="w", bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Segoe UI", 14, "bold"))
        self.terror_status.pack(fill="x", pady=(6, 6))
        self.terror_score = Label(state, text="No scan yet.", anchor="w", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Consolas", 10))
        self.terror_score.pack(fill="x")

        now_row = Frame(state, bg=self.COLORS["panel"])
        now_row.pack(fill="x", pady=(12, 0))
        self.terror_detect_pill = self.pill(now_row, "Heart: no", "stop")
        self.terror_detect_pill.pack(side="left", padx=(0, 8))
        self.terror_layer_pill = self.pill(now_row, "Layer: --", "stop")
        self.terror_layer_pill.pack(side="left", padx=(0, 8))
        self.terror_beat_pill = self.pill(now_row, "Beat: --", "stop")
        self.terror_beat_pill.pack(side="left")

        self.terror_preview = Label(state, text="Live preview will appear while watching.", bg=self.COLORS["panel2"], fg=self.COLORS["muted"], font=("Segoe UI", 10), compound="center")
        self.terror_preview.pack(fill=BOTH, expand=True, pady=(14, 0))
        Label(
            state,
            text="Preview: yellow = tracked heart, red = heartbeat strings counted for distance",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill="x", pady=(6, 0))
        self.terror_box_label = Label(state, text=self.terror_box_summary(), anchor="w", justify="left", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Consolas", 9))
        self.terror_box_label.pack(fill="x", pady=(12, 14))

        controls = Frame(state, bg=self.COLORS["panel"])
        controls.pack(fill="x")
        self.button(controls, "Enable Terror Radius", self.start_terror_radius, "primary").pack(side="left", padx=(0, 8))
        self.button(controls, "Disable", self.stop_terror_radius, "danger").pack(side="left")
        self.button(state, "Set Terror Radius Area", lambda: self.select_area("terror"), "primary").pack(fill="x", pady=(16, 0))

        settings = self.card(body)
        settings.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.card_title(settings, "Terror Radius Settings")
        Label(
            settings,
            text="Use a tight box around the visual heartbeat. Set radius to the killer's expected terror radius for better meter estimates.",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            wraplength=380,
            justify="left",
            font=("Segoe UI", 10),
        ).pack(fill="x", pady=(8, 8))

        self.terror_entries = {}
        self.terror_box_entries = {}
        self.card_title(settings, "Area Coordinates")
        self.terror_box_input_row(settings, "X", "x", 0, 10000, "px")
        self.terror_box_input_row(settings, "Y", "y", 0, 10000, "px")
        self.terror_box_input_row(settings, "Width", "width", 6, 4000, "px")
        self.terror_box_input_row(settings, "Height", "height", 6, 4000, "px")
        self.button(settings, "Apply Area Coordinates", self.apply_terror_area_coordinates).pack(fill="x", pady=(8, 12))
        self.card_title(settings, "Detection")
        self.terror_input_row(settings, "Scan interval", "scanMs", 25, 1000, "ms")
        self.terror_input_row(settings, "Radius size", "radiusMeters", 8, 80, "m")
        self.terror_input_row(settings, "Red minimum", "redMin", 40, 255, "rgb")
        self.terror_input_row(settings, "Red dominance", "redDominance", 0, 160, "rgb")
        self.terror_input_row(settings, "Minimum red pixels", "minRedPixels", 1, 1000, "px")
        self.terror_input_row(settings, "Full red area", "fullRedPercent", 1, 80, "%")
        self.terror_input_row(settings, "Pulse threshold", "pulseThreshold", 1, 80, "%")
        self.button(settings, "Apply Terror Radius Settings", self.apply_terror_settings, "primary").pack(fill="x", pady=(14, 0))

    def build_timing_tab(self):
        body = Frame(self.timing_tab, bg=self.COLORS["bg"])
        body.pack(fill=BOTH, expand=True, pady=14)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        settings = self.card(body)
        settings.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.card_title(settings, "Timing Settings")
        Label(
            settings,
            text="Type millisecond values, then click Apply. Start Watching also applies pending edits first.",
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            wraplength=380,
            justify="left",
            font=("Segoe UI", 10),
        ).pack(fill="x", pady=(8, 8))

        self.timing_entries = {}
        self.timing_input_row(settings, "Search delay", "scanMs", 100, 5000, "ms")
        self.timing_input_row(settings, "Disappear check", "triggerSeenScanMs", 50, 2000, "ms")
        self.timing_input_row(settings, "OCR interval", "ocrIntervalMs", 50, 10000, "ms")
        self.timing_input_row(settings, "OCR window", "ocrWindowMs", 1000, 120000, "ms")
        self.button(settings, "Apply Timing Settings", self.apply_timing_settings, "primary").pack(fill="x", pady=(14, 0))

        notes = self.card(body)
        notes.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.card_title(notes, "What They Do")
        timing_help = (
            "Search delay: how often the app checks for the trigger before it is visible.\n\n"
            "Disappear check: how often it checks for the trigger to disappear after it was found.\n\n"
            "OCR interval: how often OCR repeats during the OCR window.\n\n"
            "OCR window: how long OCR keeps trying after the trigger disappears."
        )
        Label(
            notes,
            text=timing_help,
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            justify="left",
            wraplength=420,
            font=("Segoe UI", 11),
        ).pack(fill=BOTH, expand=True, pady=(10, 0))

    def build_map_tab(self):
        body = Frame(self.map_tab, bg=self.COLORS["bg"])
        body.pack(fill=BOTH, expand=True, pady=14)
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

    def build_overlay_tab(self):
        body = Frame(self.overlay_tab, bg=self.COLORS["bg"])
        body.pack(fill=BOTH, expand=True, pady=14)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        state = self.card(body)
        state.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.card_title(state, "Screen Map Overlay")
        self.overlay_pill = self.pill(state, "Off", "stop")
        self.overlay_pill.pack(anchor="w", pady=(8, 10))
        self.overlay_detail = Label(state, text="", bg=self.COLORS["panel"], fg=self.COLORS["muted"], justify="left", wraplength=380, font=("Segoe UI", 10))
        self.overlay_detail.pack(fill="x", pady=(0, 16))
        self.button(state, "Enable / Disable Overlay", self.toggle_overlay, "primary").pack(fill="x", pady=(0, 8))
        self.button(state, "Enable / Disable Drag Mode", self.toggle_overlay_drag_mode).pack(fill="x")

        settings = self.card(body)
        settings.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.card_title(settings, "Position and Appearance")
        self.position_label = self.setting_row(settings, "Corner")
        top_buttons = Frame(settings, bg=self.COLORS["panel"])
        top_buttons.pack(fill="x", pady=(0, 8))
        self.button(top_buttons, "Top Left", lambda: self.set_overlay_position("top-left")).pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.button(top_buttons, "Top Right", lambda: self.set_overlay_position("top-right")).pack(side="left", fill="x", expand=True, padx=(5, 0))
        bottom_buttons = Frame(settings, bg=self.COLORS["panel"])
        bottom_buttons.pack(fill="x", pady=(0, 12))
        self.button(bottom_buttons, "Bottom Left", lambda: self.set_overlay_position("bottom-left")).pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.button(bottom_buttons, "Bottom Right", lambda: self.set_overlay_position("bottom-right")).pack(side="left", fill="x", expand=True, padx=(5, 0))
        self.size_label = self.scale_row(settings, "Size", "sizePercent", 10, 85, "%")
        self.opacity_label = self.scale_row(settings, "Transparency", "opacity", 10, 100, "%", scale_value=lambda v: float(v) / 100, display_value=lambda v: int(float(v) * 100))
        self.margin_label = self.scale_row(settings, "Screen margin", "margin", 0, 200, "px")

    def card(self, parent):
        frame = Frame(parent, bg=self.COLORS["panel"], highlightthickness=1, highlightbackground=self.COLORS["line"], padx=16, pady=14)
        return frame

    def card_title(self, parent, text):
        Label(parent, text=text, bg=self.COLORS["panel"], fg=self.COLORS["text"], font=("Segoe UI", 12, "bold"), anchor="w").pack(fill="x")

    def button(self, parent, text, command, variant="secondary"):
        bg = self.COLORS["accent"] if variant == "primary" else self.COLORS["danger"] if variant == "danger" else self.COLORS["button"]
        fg = "#07111c" if variant == "primary" else "#ffffff"
        return Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=self.COLORS["button_hover"],
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            padx=14,
            pady=8,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
        )

    def pill(self, parent, text, kind):
        label = Label(parent, text=text, padx=12, pady=5, font=("Segoe UI", 9, "bold"))
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
            save_config(self.cfg)
            value_label.configure(text=f"{int(round(float(value)))}{suffix}")
            self.update_overlay()
            self.render_overlay_state()

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

    def terror_input_row(self, parent, label, key, minimum, maximum, suffix):
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
        entry.insert(0, str(self.cfg["terrorRadius"].get(key, DEFAULT_CONFIG["terrorRadius"].get(key, ""))))
        entry.pack(side="left", fill="x", expand=True, ipady=5)
        Label(input_row, text=suffix, bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 10)).pack(side="left", padx=(8, 0))
        Label(parent, text=f"{minimum}-{maximum} {suffix}", bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 2))
        self.terror_entries[key] = {
            "entry": entry,
            "label": label,
            "minimum": int(minimum),
            "maximum": int(maximum),
            "suffix": suffix,
        }
        entry.bind("<Return>", lambda _event: self.apply_terror_settings())
        return entry

    def terror_box_input_row(self, parent, label, key, minimum, maximum, suffix):
        row = Frame(parent, bg=self.COLORS["panel"])
        row.pack(fill="x", pady=(8, 2))
        Label(row, text=label, bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 10, "bold")).pack(anchor="w")

        input_row = Frame(parent, bg=self.COLORS["panel"])
        input_row.pack(fill="x", pady=(0, 2))
        entry = Entry(
            input_row,
            bg=self.COLORS["panel2"],
            fg=self.COLORS["text"],
            insertbackground=self.COLORS["text"],
            relief="flat",
            font=("Consolas", 10),
        )
        box = self.cfg["terrorRadius"].get("box") or DEFAULT_CONFIG["terrorRadius"]["box"]
        entry.insert(0, str(int(box.get(key, minimum))))
        entry.pack(side="left", fill="x", expand=True, ipady=5)
        Label(input_row, text=suffix, bg=self.COLORS["panel"], fg=self.COLORS["muted"], font=("Segoe UI", 10)).pack(side="left", padx=(8, 0))
        self.terror_box_entries[key] = {
            "entry": entry,
            "label": label,
            "minimum": int(minimum),
            "maximum": int(maximum),
            "suffix": suffix,
        }
        entry.bind("<Return>", lambda _event: self.apply_terror_area_coordinates())
        return entry

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
            elif key == "hitDepthPercent":
                window_end = int(skill.get("hitWindowEndPercent", DEFAULT_CONFIG["skillCheck"]["hitWindowEndPercent"]))
                if window_end < value:
                    skill["hitWindowEndPercent"] = value
            elif key == "hitWindowEndPercent":
                depth = int(skill.get("hitDepthPercent", DEFAULT_CONFIG["skillCheck"]["hitDepthPercent"]))
                if value < depth:
                    value = depth
                    skill[key] = value
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

    def apply_terror_settings(self):
        changed = []
        terror = self.cfg["terrorRadius"]
        for key, meta in self.terror_entries.items():
            entry = meta["entry"]
            raw = entry.get().strip()
            old_value = terror.get(key)
            try:
                value = int(float(raw))
            except ValueError:
                value = int(terror.get(key, DEFAULT_CONFIG["terrorRadius"].get(key, meta["minimum"])))
            value = max(meta["minimum"], min(meta["maximum"], value))
            terror[key] = value
            entry.delete(0, END)
            entry.insert(0, str(value))
            if value != old_value:
                changed.append(f"{meta['label']} = {value}{meta['suffix']}")

        save_config(self.cfg)
        self.terror_box_label.configure(text=self.terror_box_summary())
        if changed:
            self.log("Terror radius settings applied: " + ", ".join(changed))
        else:
            self.log("Terror radius settings applied.")
        return True

    def apply_terror_area_coordinates(self):
        current = self.cfg["terrorRadius"].get("box") or DEFAULT_CONFIG["terrorRadius"]["box"]
        values = {}
        for key, meta in self.terror_box_entries.items():
            entry = meta["entry"]
            raw = entry.get().strip()
            try:
                value = int(float(raw))
            except ValueError:
                value = int(current.get(key, meta["minimum"]))
            value = max(meta["minimum"], min(meta["maximum"], value))
            values[key] = value

        box = clean_box(values)
        if not box:
            self.terror_status.configure(text="Terror radius area is too small.")
            self.log("Terror radius area coordinates rejected: area is too small.")
            return False
        dbd = find_dbd_window_bounds()
        if dbd:
            box["relativeTo"] = "dbd-window"
            box["baseWidth"] = dbd["width"]
            box["baseHeight"] = dbd["height"]

        self.cfg["terrorRadius"]["box"] = box
        save_config(self.cfg)
        self.refresh_area_labels()
        self.sync_terror_box_entries()
        self.terror_status.configure(text="Terror radius area coordinates applied.")
        self.log(f"Terror radius area set from coordinates: {box}")
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
        return f"Skill-check box: {self.format_box(skill.get('box'))}\nInput: {skill.get('pressKey') or 'c'}\nHit window: {skill.get('hitDepthPercent', DEFAULT_CONFIG['skillCheck']['hitDepthPercent'])}-{skill.get('hitWindowEndPercent', DEFAULT_CONFIG['skillCheck']['hitWindowEndPercent'])}%"

    def terror_box_summary(self):
        terror = self.cfg.get("terrorRadius") or {}
        return f"Terror-radius box: {self.format_box(terror.get('box'))}\nRadius size: {terror.get('radiusMeters') or 32}m"

    def refresh_area_labels(self):
        if hasattr(self, "boxes"):
            self.boxes.configure(text=self.box_summary())
        if hasattr(self, "skill_box_label"):
            self.skill_box_label.configure(text=self.skill_box_summary())
        if hasattr(self, "terror_box_label"):
            self.terror_box_label.configure(text=self.terror_box_summary())

    def sync_terror_box_entries(self):
        if not hasattr(self, "terror_box_entries"):
            return
        box = self.cfg["terrorRadius"].get("box") or DEFAULT_CONFIG["terrorRadius"]["box"]
        for key, meta in self.terror_box_entries.items():
            entry = meta["entry"]
            entry.delete(0, END)
            entry.insert(0, str(int(box.get(key, meta["minimum"]))))

    def log(self, message):
        log_to_file(message)
        self.log_box.configure(state="normal")
        self.log_box.insert("1.0", f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.log_box.delete("220.0", END)
        self.log_box.configure(state="disabled")

    def start_detection(self):
        self.apply_timing_settings()
        self.cfg["mapDetectorEnabled"] = True
        save_config(self.cfg)
        self.set_pill(self.run_pill, "Map: watching", "watch")
        self.status.configure(text="Waiting for trigger image.")
        self.detector.start()

    def stop_detection(self):
        self.cfg["mapDetectorEnabled"] = False
        save_config(self.cfg)
        self.detector.stop()
        self.set_pill(self.run_pill, "Map: off", "stop")
        self.status.configure(text="Stopped.")

    def start_skill_checks(self):
        self.apply_skill_settings()
        self.cfg["skillCheck"]["enabled"] = True
        save_config(self.cfg)
        self.set_pill(self.skill_pill, "Watching", "watch")
        self.set_pill(self.skill_global_pill, "Skill: on", "watch")
        self.set_pill(self.skill_white_pill, "White: no", "stop")
        self.set_pill(self.skill_zone_pill, "Zones: 0/0", "stop")
        self.set_pill(self.skill_red_pill, "Red in zone: no", "stop")
        self.set_pill(self.skill_hit_pill, "Hit: no", "stop")
        self.skill_status.configure(text="Watching skill-check area.")
        self.skill_detector.start()

    def stop_skill_checks(self):
        self.cfg["skillCheck"]["enabled"] = False
        save_config(self.cfg)
        self.skill_detector.stop()
        self.skill_debug_overlay.close()
        self.set_pill(self.skill_pill, "Stopped", "stop")
        self.set_pill(self.skill_global_pill, "Skill: off", "stop")
        self.set_pill(self.skill_white_pill, "White: no", "stop")
        self.set_pill(self.skill_zone_pill, "Zones: 0/0", "stop")
        self.set_pill(self.skill_red_pill, "Red in zone: no", "stop")
        self.set_pill(self.skill_hit_pill, "Hit: no", "stop")
        self.skill_preview_photo = None
        self.skill_preview.configure(image="", text="Live preview will appear while watching.")
        self.skill_status.configure(text="Stopped.")

    def start_terror_radius(self):
        self.apply_terror_settings()
        self.cfg["terrorRadius"]["enabled"] = True
        save_config(self.cfg)
        self.set_pill(self.terror_pill, "Watching", "watch")
        self.set_pill(self.terror_global_pill, "Terror: on", "watch")
        self.set_pill(self.terror_detect_pill, "Heart: no", "stop")
        self.set_pill(self.terror_layer_pill, "Layer: --", "stop")
        self.set_pill(self.terror_beat_pill, "Beat: --", "stop")
        self.terror_status.configure(text="Watching visual heartbeat area.")
        self.terror_detector.start()

    def stop_terror_radius(self):
        self.cfg["terrorRadius"]["enabled"] = False
        save_config(self.cfg)
        self.terror_detector.stop()
        self.set_pill(self.terror_pill, "Stopped", "stop")
        self.set_pill(self.terror_global_pill, "Terror: off", "stop")
        self.set_pill(self.terror_detect_pill, "Heart: no", "stop")
        self.set_pill(self.terror_layer_pill, "Layer: --", "stop")
        self.set_pill(self.terror_beat_pill, "Beat: --", "stop")
        self.terror_preview_photo = None
        self.terror_preview.configure(image="", text="Live preview will appear while watching.")
        self.terror_status.configure(text="Stopped.")

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
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
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
                self.set_pill(self.skill_white_pill, f"White: {'seen' if armed else 'no'} ({memory})", "good" if armed else "stop")
                zone_kind = "good" if zones and hit_zones >= zones else "warn" if zones else "stop"
                self.set_pill(self.skill_zone_pill, f"Zones: {hit_zones}/{zones}", zone_kind)
                self.set_pill(self.skill_global_pill, f"Skill: on {hit_zones}/{zones}", "watch" if zones else "watch")
                self.set_pill(self.skill_red_pill, f"Red in zone: {red_in_zone}", "warn" if red_in_zone else "stop")
                hit_text = "Hit: SENT" if hit else "Hit: cooldown" if cooldown else "Hit: no"
                self.set_pill(self.skill_hit_pill, hit_text, "good" if hit else "warn" if cooldown else "stop")
                if hit:
                    self.skill_status.configure(text=f"NOW: sent input; zones {hit_zones}/{zones}; red in white {red_in_zone}.")
                elif cooldown:
                    self.skill_status.configure(text=f"NOW: red in an already-hit white zone ({red_in_zone}); zones {hit_zones}/{zones}.")
                elif armed and red_in_zone:
                    self.skill_status.configure(text=f"NOW: red fully inside a valid white zone ({red_in_zone}); zones {hit_zones}/{zones}.")
                elif armed:
                    self.skill_status.configure(text=f"NOW: found {zones} valid white zone{'s' if zones != 1 else ''}; hit {hit_zones}; red in zone 0; total red {red_total}.")
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
            elif kind == "terror-state":
                self.terror_status.configure(text=payload)
                if "detected" in payload or "Watching" in payload:
                    self.set_pill(self.terror_pill, "Watching", "watch")
                    self.set_pill(self.terror_global_pill, "Terror: on", "watch")
            elif kind == "terror-score":
                self.terror_score.configure(text=payload)
            elif kind == "terror-visual":
                detected = bool(payload.get("detected"))
                strings_seen = bool(payload.get("stringsSeen"))
                beat = bool(payload.get("beat"))
                layer = payload.get("layer") or "--"
                strength = float(payload.get("strength") or 0)
                bpm = int(payload.get("bpm") or 0)
                distance_label = payload.get("distanceLabel") or "--"
                string_count = int(payload.get("stringCount") or 0)
                heart_count = int(payload.get("heartCount") or 0)
                rgb = payload.get("rgb")
                width = int(payload.get("width") or 0)
                height = int(payload.get("height") or 0)
                if rgb and width > 0 and height > 0:
                    try:
                        image = Image.frombytes("RGB", (width, height), rgb)
                        image.thumbnail((360, 260), Image.Resampling.NEAREST)
                        self.terror_preview_photo = ImageTk.PhotoImage(image)
                        self.terror_preview.configure(image=self.terror_preview_photo, text="")
                    except Exception:
                        pass
                self.set_pill(self.terror_detect_pill, f"Heart: {'seen' if detected else 'no'} ({heart_count})", "good" if detected else "stop")
                self.set_pill(self.terror_layer_pill, f"Strings: {string_count}", "warn" if strings_seen else "stop")
                beat_text = f"Beat: {bpm} bpm" if bpm else "Beat: yes" if beat else "Beat: --"
                self.set_pill(self.terror_beat_pill, beat_text, "good" if beat else "stop")
                if detected and strings_seen:
                    self.terror_status.configure(text=f"Terror radius {layer.lower()}: {distance_label} | intensity {strength:.2f}.")
                elif detected:
                    self.terror_status.configure(text=f"Heart tracked; waiting for strings | intensity {strength:.2f}.")
                else:
                    self.terror_status.configure(text=f"No visual heartbeat detected | intensity {strength:.2f}.")
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

    def render_selected_map_image(self):
        if not self.selected_image_paths:
            self.map_photo = None
            self.map_image.configure(image="", text="No local map image loaded yet.")
            if not self.suppress_overlay_updates:
                self.update_overlay()
            return
        image_path = self.selected_image_paths[self.selected_image_index]
        try:
            image = Image.open(image_path).convert("RGB")
            image.thumbnail((420, 420), Image.Resampling.LANCZOS)
            self.map_photo = ImageTk.PhotoImage(image)
            self.map_image.configure(image=self.map_photo, text="")
            if not self.suppress_overlay_updates:
                self.update_overlay()
        except Exception as exc:
            self.map_photo = None
            self.map_image.configure(image="", text=f"Could not load map image: {exc}")

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
        save_config(self.cfg)
        self.update_overlay()
        self.render_overlay_state()

    def toggle_overlay_drag_mode(self):
        self.cfg["overlay"]["dragMode"] = not bool(self.cfg["overlay"].get("dragMode"))
        save_config(self.cfg)
        self.update_overlay()
        self.render_overlay_state()

    def set_overlay_position(self, position):
        allowed = {"top-left", "top-right", "bottom-left", "bottom-right"}
        self.cfg["overlay"]["position"] = position if position in allowed else "top-left"
        self.cfg["overlay"]["side"] = "left" if "left" in self.cfg["overlay"]["position"] else "right"
        self.cfg["overlay"]["customPosition"] = False
        self.cfg["overlay"]["customX"] = None
        self.cfg["overlay"]["customY"] = None
        save_config(self.cfg)
        self.update_overlay(force_recreate=True)
        self.render_overlay_state()

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
        freeze_screen = frozen or kind in {"trigger", "text", "terror"}
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
        self.terror_detector.stop()
        self.skill_debug_overlay.close()
        self.set_pill(self.run_pill, "Map: off", "stop")
        self.set_pill(self.skill_global_pill, "Skill: off", "stop")
        self.set_pill(self.terror_global_pill, "Terror: off", "stop")
        self.set_pill(self.skill_pill, "Stopped", "stop")
        self.set_pill(self.terror_pill, "Stopped", "stop")
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
                "terror": "Drag around the visual heartbeat.",
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
            elif kind == "terror":
                self.cfg["terrorRadius"]["box"] = stored_box
                save_config(self.cfg)
                self.refresh_area_labels()
                self.sync_terror_box_entries()
                self.log(f"Terror radius area applied: {stored_box}")

        def apply_selection():
            box = pending["box"]
            close_selector()
            commit_box(box)

        def cancel_selection():
            close_selector()
            self.log("Area selection canceled.")

        self.button(confirm_buttons, "Apply", apply_selection, "primary").pack(side="left", padx=(0, 8))
        self.button(confirm_buttons, "Cancel", cancel_selection, "danger").pack(side="left")

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
            if pending["box"]:
                pending["box"] = None
                confirm_panel.place_forget()
                rect.place_forget()
            drag["start"] = (event.x_root, event.y_root)
            drag["active"] = True
            draw(drag["start"], drag["start"])
            hint.configure(text="Drag to resize the blue area, then release.")

        def update_drag(event):
            if drag["active"] and drag["start"]:
                draw(drag["start"], (event.x_root, event.y_root))

        def finish_drag(event):
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
        self.terror_detector.stop()
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
