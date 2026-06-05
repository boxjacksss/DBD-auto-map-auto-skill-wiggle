No BAN

# DBD Screen OCR Detector

Python-only screen detector for Dead by Daylight map OCR.

## Project Layout

```text
backend/      detector logic, screen capture, trigger matching, OCR
frontend/     small Tkinter app launcher
assets/       saved trigger image, debug captures, optional map images
run.py        main entrypoint
```

## Run

```powershell
cd C:\Users\000\Music\dbd-screen-ocr-detector-drag-overlay-fixed-slim\dbd-screen-ocr-detector
python -m pip install -r requirements.txt
python run.py
```

Or double-click:

```bat
start-detector.bat
```

## OCR

Trigger detection does not need OCR and only captures the saved trigger rectangle.

The app installs native Tesseract OCR automatically with `winget` if it is missing. Windows may show an installer or permission prompt the first time.

## Timing Settings

Open the `Timing Settings` tab and use the input boxes to adjust:

- Search delay
- Trigger disappearance check delay
- OCR interval
- OCR window length

Click `Apply Timing Settings`, or click `Start Watching`, to apply pending edits.

The OCR interval can be set as low as `50 ms`. If OCR itself takes longer than that, the next pass starts after the current one finishes.

OCR uses several preprocessing passes and a DBD map-name word list before deciding whether text matches a known map.

## Skill Checks

Open the `Skill Checks` tab to enable the optional skill-check watcher.

Use `Set Skill Check Area` to select a tight box around the skill-check circle, then choose the input, scan interval, cooldown, and color thresholds. The watcher captures only that selected box and presses the configured input when the moving red marker overlaps the white success zone.

The input box accepts keyboard keys like `c` or `space`, plus mouse buttons like `left`, `right`, `middle`, `m4`, or `m5`.

`Test hotkey` defaults to `0`. Press it while focused in-game to send the configured input immediately, without waiting for detection. This is useful for confirming that the game receives `m5`.

The Skill Checks tab shows live status pills:

- `White` means the app has learned the current white success zone.
- `Red in zone` is red found inside that learned white zone.
- `Hit` lights up when the configured input is sent.

The tab also shows a live highlighted preview of the current selected skill-check capture while watching. White highlights are the current white zone, cyan is the armed/remembered white zone, orange is the detected red needle, and red is the part of the red needle aligned with the armed zone.

While the watcher is running it writes debug screenshots to:

```text
assets/skill-check-debug
```

`latest-raw.png` is the selected screen crop without drawn guide circles. `latest-mask.png` shows detected white pixels in white, detected red pixels in red, and remembered white-zone pixels in cyan. The live red count is red detected inside the remembered white zone. Timestamped `hit` images are saved when the configured input is pressed.

The detector watches the outer ring by default, so the center prompt text such as `M5` is ignored. The white success zone must remain visible for the `White stable` time before it is armed, then the app sends one input when the red needle angle reaches that remembered white zone. It will not send another input until the ring clears. Use `Ring inner`, `Ring outer`, and `Angle tolerance` if the debug mask is not lining up with the skill-check circle.


```text
assets/maps
```

Supported image types:

```text
.png, .jpg, .jpeg, .webp, .gif
```
