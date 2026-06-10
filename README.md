# Density Map Generator

A command-line tool that takes a set of **red-marked PNG masks** plus an **original image** and produces five visual outputs: a composite of the original weighted by how densely the masks overlap, a grayscale density map, a simplified banded version of it, the same with its band edges outlined in red, and finally the contour lines as a vector file.

Everything runs through a guided terminal interface: at each step the tool explains what it is about to do and asks for confirmation, so you can generate only the outputs you need.

---

## What it does, in short

Each mask contains **red areas** that mark a region. When many masks are stacked, some zones end up covered more often than others. This **coverage density** — how many masks overlap on each pixel — is the quantity the tool measures and then turns into five different representations.

## The five outputs

| # | File | Format | Background | Description |
|---|------|--------|------------|-------------|
| 1 | `composite_{suffix}.png` | PNG | Transparent | Each mask cuts out the original (the pixels where the mask is red are kept); the cutouts are summed linearly. For every pixel: opacity = `min(coverage / reference, 1)`, color = the original pixel. |
| 2 | `density_map_{suffix}.png` | PNG | Black | The grayscale density map: the more a zone is covered, the brighter it is. |
| 3 | `density_map_{suffix}_simplified.png` | PNG | Black | A simplified version: the field is smoothed and quantized into **flat gray bands**, with soft edges aligned to the contour lines of output 5. |
| 4 | `density_map_{suffix}_simplified_stroke.png` | PNG | Black | Output 3 with a **red outline** drawn on every band edge. |
| 5 | `density_map_{suffix}_contour.svg` | SVG | Black | The **contour lines** (white), smoothed with splines, each labeled with its level `N/total`. |

`{suffix}` is either `relativa` or `assoluta`, depending on the normalization mode you choose (see below).

---

## Requirements

- **Python 3.9 or newer**
- Libraries: `Pillow`, `numpy`, `scipy`, `scikit-image`

```bash
pip3 install Pillow numpy scipy scikit-image
```

> `scipy` and `scikit-image` handle the Gaussian smoothing and the contour extraction, respectively. The script has partial fallbacks if they are missing, but you should install them for correct results.

---

## Folder structure

The script looks for its files **next to itself**. Before you run it, the folder must be organized like this:

```
project/
├── density_map.py        # the script
├── original.png          # the original image (source for the composite)
├── livelli/              # the PNG masks with the red areas
│   ├── 0.png
│   ├── 1.png
│   ├── 2.png
│   └── ...               # one per mask
└── output/               # created automatically on first save
```

Two items must be **prepared by hand**:

- **`original.png`** — the original image, with exactly this name.
- **`livelli/`** — the subfolder containing the masks.

The **`output/`** folder is created automatically; you do not need to make it.

### The masks

- **Format and naming:** numbered PNGs (`0.png`, `1.png`, `2.png`, …). The script sorts them naturally by number, so `2.png` comes before `10.png`.
- **Red:** the regions to be counted must be red. The default detection treats a pixel as "red" when `R ≥ 180`, `G ≤ 80`, `B ≤ 80` (and the alpha channel is not transparent). The thresholds can be adjusted in Step 3.
- **Resolution:** ideally the same as `original.png`. If they differ, the original is resized automatically to the masks' resolution (with an on-screen warning).

---

## Installation

```bash
# 1. Clone or download the repository
git clone <repo-url>
cd <repo-folder>

# 2. Install the dependencies
pip3 install Pillow numpy scipy scikit-image
```

---

## How to use it, step by step

### 1. Prepare the folder

Place `original.png` and the `livelli/` subfolder (with the masks) next to `density_map.py`, following the structure above.

### 2. Open a terminal in the project folder

- **macOS:** in Finder, right-click the folder → *Services* → *New Terminal at Folder* (or use `cd` and drag the folder into the terminal window).
- **Windows:** in the folder, Shift + right-click → *Open PowerShell window here*.

### 3. Run the script

```bash
python3 density_map.py
```

(on Windows, usually `python density_map.py`)

### 4. Follow the guided flow

The interface moves through a series of steps. Press Enter to move between them; when a choice is needed, the script asks for it.

**Welcome screen** — lists the five outputs. Press Enter to start.

**Step 1 — Input check.** Verifies that `livelli/` and `original.png` exist. If something is missing, it says so and stops: add the missing item and run again.

**Step 2 — Mask detection.** Lists the PNGs found in `livelli/`, shows the resolution and the file count, and asks you to confirm before continuing.

**Step 3 — Configuration.** Two choices:
- **Normalization mode** — `1` absolute, `2` relative (default).
- **Red thresholds** — accept the defaults or enter your own.

A summary follows, which you confirm.

**Step 4 — Analysis and normalization.** Counts the red pixels across all masks, shows the **distribution of pixels by number of overlaps**, and — in relative mode — proposes the **reference maximum** (see below), with the option to override it manually. Finally it computes the smoothing shared by outputs 3, 4, and 5.

**Steps 5–9 — Generating the outputs.** For each of the five outputs the script asks `[Y/n]`: answer `y` to generate it, `n` to skip it. Files are saved to `output/`.

When it finishes, a summary shows the path to the `output/` folder.

---

## Normalization modes

The normalization decides how coverage density is mapped onto gray tones (and onto the composite's opacity).

- **Absolute** — each mask is worth a fixed fraction of the total: with _N_ masks, one level equals `1/N`. Pure white corresponds to coverage by **all** masks.
- **Relative** (default) — pure white is anchored to the **reference maximum** (`effective_max`): the highest coverage level that affects a meaningful portion of the image. Higher but sparse levels (below the `MIN_PIXEL` threshold, 5,000 pixels by default) are discarded as noise. The result is more contrast and full use of the gray range.

In relative mode, Step 4 proposes this maximum automatically and lets you confirm it or set it by hand.

> **Technical note.** Outputs 3, 4, and 5 start from the same smoothed field (Gaussian blur), computed only once: the filled bands (3), their red outlines (4), and the vector curves (5) are therefore perfectly consistent with one another. Output 3 and output 5 look very similar but are not identical: the SVG adds a further spline interpolation (Catmull-Rom).

---

## Customization

The main parameters are collected as constants at the top of `density_map.py`:

| Constant | Default | Effect |
|----------|---------|--------|
| `MIN_PIXEL` | `5000` | Minimum pixel count for a level to be considered valid (relative mode). |
| `STROKE_WIDTH` | `2` | Width in pixels of the red outline (output 4). |
| `STROKE_COLOR` | `(255, 0, 0)` | Color of the outline (output 4). |
| `SIMPLIFY_TOL_STROKE` | `1.5` | Edge-simplification tolerance (output 4). |
| `CONTOUR_BLUR_SIGMA` | `12.0` | Strength of the shared smoothing (outputs 3/4/5): higher = softer shapes. |
| `CONTOUR_LINE_WIDTH` | `1` | Curve width in the SVG (in pt). |
| `CONTOUR_LINE_COLOR` | `"white"` | Color of the curves and labels in the SVG. |
| `CONTOUR_BG_COLOR` | `"black"` | Background color of the SVG. |
| `LABEL_FONT_SIZE` | `14` | Size of the level labels in the SVG. |

The red thresholds (`R ≥ 180`, `G ≤ 80`, `B ≤ 80`) are set interactively in Step 3 instead.

---

## Troubleshooting

- **`ModuleNotFoundError: No module named '...'`** — a dependency is missing: run `pip3 install Pillow numpy scipy scikit-image` again.
- **PATH or pip-version warnings during installation** — harmless; they do not stop execution.
- **"livelli folder not found" / "original.png not found"** — make sure both are in the **same folder** as the script, with the exact names.
- **"No file found with this pattern"** — the masks are not named as numbered PNGs (`0.png`, `1.png`, …) inside `livelli/`.
- **The red areas are not detected** — the masks' red falls outside the default thresholds: in Step 3, enter more permissive manual values.
- **The original looks stretched** — `original.png` has a different resolution from the masks and gets resized: export it at the masks' resolution to avoid the stretch.

---

## License

Released under the [MIT License](LICENSE). You are free to use, modify, and
distribute it, as long as the copyright notice and this license are kept.
See the [`LICENSE`](LICENSE) file.
