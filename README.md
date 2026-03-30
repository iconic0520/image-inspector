# 🔍 Image Inspector

Offline Python GUI app for:
1. **Tampering Detection** — is this image authentic or edited?
2. **Folder Sorter** — automatically split a folder into Good / Bad images

---

## ⚙ Setup (one-time)

Make sure Python 3.8+ is installed, then:

```bash
pip install -r requirements.txt
```

---

## ▶ Run

```bash
python main.py
```

---

## Tab 1 — Tampering Detector

Select any image and click **Run Analysis**. The app runs 4 checks:

| Check | What it looks for |
|---|---|
| **ELA** (Error Level Analysis) | Re-compresses the image and maps where pixels changed abnormally — edited regions show up as bright spots |
| **Metadata / EXIF** | Scans for editing software (Photoshop, GIMP, Lightroom…), mismatched timestamps, missing camera info |
| **Noise Map** | Authentic photos have consistent sensor noise. Spliced/composited images have mismatched noise in different regions |
| **Copy-Move Detection** | Detects cloned or copy-pasted regions within the same image using feature matching |

A **suspicion score (0–100)** is given for each check. The overall verdict is:
- ✅ < 25 → Likely Authentic
- 🟡 25–50 → Possibly Edited
- 🔴 > 50 → Likely Tampered

> ⚠ No tool is 100% accurate. Multiple high scores together is the strongest signal.

---

## Tab 2 — Folder Sorter

Pick a source folder, set where to save **Good** and **Bad** images, tick which checks to run, and hit **Start Sorting**.

**What counts as BAD:**
- Blurry (Laplacian sharpness score too low)
- Too noisy (high-frequency residual above threshold)
- Too dark or overexposed (mean brightness out of range)
- Low resolution (under 100,000 pixels)
- Duplicate (exact byte match OR visually near-identical via perceptual hash)
- Copy-move tampering suspected (optional)

You can choose to **copy** (keep originals) or **move** the files.

---

## Requirements

- Python 3.8+
- pillow, numpy, opencv-python, imagehash
- tkinter (built into Python — no install needed)
- 100% offline — no internet connection required
