"""
density_map.py
--------------
Interfaccia guidata da terminale che, a partire da 31 immagini-maschera PNG
con geometrie rosse e da un'immagine originale, genera CINQUE output visivi.

INPUT ATTESI
    progetto/
    ├── density_map.py
    ├── original.png    ← immagine originale (sorgente del compositing)
    ├── livelli/        ← 31 maschere PNG (img. N.png) con porzioni rosse
    └── output/         ← file generati (creata automaticamente)

OUTPUT GENERATI (in ordine, ognuno con il proprio gate interattivo)

  1) COMPOSITO MASCHERE SULL'ORIGINALE  →  composite_{suffix}.png
     Ogni maschera ritaglia l'originale (si tengono i pixel dove la maschera
     è rossa). I 31 ritagli vengono sovrapposti con logica LINEARE identica
     alla normalizzazione "relativa": per ogni pixel
         alpha = min(copertura / effective_max, 1)
         colore = pixel dell'originale (= media dei ritagli che lo coprono)
     Sfondo trasparente.

  2) DENSITY MAP B&N                     →  density_map_{suffix}.png
     La density map in scala di grigi (relativa di default), RGB con sfondo
     nero (copertura 0 → nero).

  3) DENSITY MAP SEMPLIFICATA            →  density_map_{suffix}_simplified.png
     Versione posterizzata e smussata: si parte dallo STESSO campo smussato
     (Gaussian blur sigma 12) dell'output 5 e lo si quantizza in fasce grigie
     piatte (smoothed >= L-0.5 → grigio L/effective_max). I bordi sono morbidi
     e combaciano con le curve dell'SVG, ma non sono identici (l'SVG aggiunge
     la spline Catmull-Rom). Sfondo nero. Controparte "a fasce piene" dell'output 5.

  4) SEMPLIFICATA + STROKE ROSSO         →  density_map_{suffix}_simplified_stroke.png
     L'output 3 con un contorno rosso #ff0000 (STROKE_WIDTH px) tracciato su
     OGNI bordo di fascia/livello.

  5) CURVE DI LIVELLO (SVG)              →  density_map_{suffix}_contour.svg
     Curve di livello bianche su sfondo nero, smussate (Gaussian blur sigma 12
     + spline Catmull-Rom), con etichette "N/totale".

Requisiti: pip install Pillow numpy scipy scikit-image
"""

import os
import sys
import glob
import re
import time
import numpy as np
from PIL import Image, ImageDraw

# ─────────────────────────────────────────────
# COSTANTI
# ─────────────────────────────────────────────

VERSION      = "4.1"
W_LINE       = 60
MIN_PIXEL    = 5000
STROKE_WIDTH = 2
STROKE_COLOR = (255, 0, 0)

# Output 3/4 — semplificazione (fasce posterizzate sul campo smussato, come l'SVG)
SIMPLIFY_TOL_STROKE = 1.5     # tolleranza RDP per lo stroke dei bordi (output 4)

# Output 5 — curve di livello SVG  (smoothing condiviso da output 3/4/5)
CONTOUR_BLUR_SIGMA  = 12.0    # smoothing forte (forma stilizzata)
CONTOUR_LINE_WIDTH  = 1        # spessore linee SVG in pt
CONTOUR_LINE_COLOR  = "white"  # linee bianche (visibili su sfondo nero)
CONTOUR_BG_COLOR    = "black"  # sfondo dell'SVG
LABEL_FONT_SIZE     = 14       # dimensione etichette SVG
LABEL_EVERY         = 1        # etichetta su ogni livello

ORIGINAL_NAME = "original.png"
N_STEPS       = 9             # numero totale di passi nell'interfaccia

# ─────────────────────────────────────────────
# UTILITÀ INTERFACCIA
# ─────────────────────────────────────────────

def clear():
    os.system("cls" if os.name == "nt" else "clear")

def line(char="─"):
    print(char * W_LINE)

def header(title: str, step: str = ""):
    clear()
    line("═")
    print(f"  DENSITY MAP GENERATOR  v{VERSION}")
    line("═")
    if step:
        print(f"  PASSO {step}")
        line("─")
    print(f"\n  {title}\n")

def ok(msg):   print(f"  ✓  {msg}")
def warn(msg): print(f"  ⚠  {msg}")
def err(msg):  print(f"\n  ✗  ERRORE: {msg}")
def info(msg): print(f"     {msg}")

def ask(prompt: str, default: str = "") -> str:
    suff = f" [{default}]" if default else ""
    try:
        val = input(f"\n  → {prompt}{suff}: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n\n  Operazione annullata.")
        sys.exit(0)
    return val if val else default

def ask_yes_no(prompt: str, default: bool = True) -> bool:
    suff = "[S/n]" if default else "[s/N]"
    r = ask(f"{prompt} {suff}", "s" if default else "n").lower()
    return r in ("s", "si", "sì", "y", "yes", "")

def pausa(msg="Premi INVIO per continuare..."):
    try:
        input(f"\n  {msg}")
    except (KeyboardInterrupt, EOFError):
        sys.exit(0)

def progress_bar(current: int, total: int, width: int = 30) -> str:
    filled = int(width * current / total)
    bar = "█" * filled + "░" * (width - filled)
    pct = int(100 * current / total)
    return f"  [{bar}] {pct:3d}%  {current}/{total}"

def get_out_dir() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir    = os.path.join(script_dir, "output")
    os.makedirs(out_dir, exist_ok=True)
    return out_dir

# ─────────────────────────────────────────────
# LOGICA CORE — CONTEGGIO E NORMALIZZAZIONE
# ─────────────────────────────────────────────

def natural_sort_key(path):
    return [int(n) for n in re.findall(r'\d+', os.path.basename(path))]

def load_red_mask(path, h, w, r_min, g_max, b_max):
    arr = np.array(Image.open(path).convert("RGBA"), dtype=np.uint8)
    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    return (r >= r_min) & (g <= g_max) & (b <= b_max) & (a > 10)

def build_count(files, h, w, r_min, g_max, b_max):
    acc = np.zeros((h, w), dtype=np.int32)
    n = len(files)
    for i, f in enumerate(files):
        acc += load_red_mask(f, h, w, r_min, g_max, b_max).astype(np.int32)
        sys.stdout.write(f"\r{progress_bar(i + 1, n)}")
        sys.stdout.flush()
    print()
    return acc

def find_effective_max(count, min_pixel):
    max_val = int(count.max())
    for v in range(max_val, 0, -1):
        c = int((count == v).sum())
        if c >= min_pixel:
            return v, c
    return 1, int((count == 1).sum())

def normalize_absolute(count, n_files):
    return count.astype(np.float32) / n_files

def normalize_relative(count, effective_max):
    norm = count.astype(np.float32) / max(effective_max, 1)
    return norm.clip(0.0, 1.0)

# ─────────────────────────────────────────────
# OUTPUT 1 — COMPOSITO LINEARE SULL'ORIGINALE
# ─────────────────────────────────────────────

def load_original(path, W, H):
    """Carica original.png come RGB e lo allinea alla risoluzione delle maschere."""
    im = Image.open(path).convert("RGB")
    if im.size != (W, H):
        warn(f"original.png è {im.size[0]}×{im.size[1]} px: ridimensiono a {W}×{H}.")
        im = im.resize((W, H), Image.LANCZOS)
    return np.array(im, dtype=np.uint8)

def build_composite_linear(original_rgb, count, ref_max):
    """
    Composito lineare equivalente alla normalizzazione relativa.

    Sovrapporre 31 ritagli dell'originale (ognuno = i pixel dell'originale dove
    la rispettiva maschera è rossa) con contributo lineare significa, per ogni
    pixel coperto da k maschere:
        colore  = media di k copie dello stesso pixel originale = pixel originale
        alpha   = min(k / ref_max, 1)
    Quindi il risultato si ottiene direttamente, senza materializzare i 31 layer.
    """
    alpha = np.clip(count.astype(np.float32) / max(ref_max, 1), 0.0, 1.0)
    a     = (alpha * 255).astype(np.uint8)
    out   = np.dstack([original_rgb, a])           # H×W×4 (RGBA)
    return Image.fromarray(out, "RGBA")

# ─────────────────────────────────────────────
# OUTPUT 2 — DENSITY MAP B&N (RGB, sfondo nero)
# ─────────────────────────────────────────────

def build_density_image(norm):
    grey = (norm * 255).clip(0, 255).astype(np.uint8)
    out  = np.stack([grey, grey, grey], axis=-1)   # H×W×3 (RGB)
    return Image.fromarray(out, "RGB")             # sfondo nero (copertura 0 → grey 0)

# ─────────────────────────────────────────────
# CONTORNI E SEMPLIFICAZIONE (condivisi: output 3, 4, 5)
# ─────────────────────────────────────────────

def smooth_count(count, sigma):
    """Applica Gaussian blur alla matrice count (float32) — usato solo per l'SVG."""
    try:
        from scipy.ndimage import gaussian_filter
        smoothed = gaussian_filter(count.astype(np.float32), sigma=sigma)
    except ImportError:
        warn("scipy non disponibile: curve senza smoothing.")
        smoothed = count.astype(np.float32)
    return smoothed


def find_contour_paths(binary_mask):
    """
    Estrae i contorni da una maschera binaria come lista di array Nx2 (row, col).
    Usa skimage.measure.find_contours se disponibile, altrimenti un fallback.
    """
    try:
        from skimage.measure import find_contours
        return find_contours(binary_mask.astype(np.float32), level=0.5)
    except ImportError:
        pass

    from scipy.ndimage import binary_erosion
    eroded = binary_erosion(binary_mask)
    edge   = binary_mask & ~eroded
    pts    = np.argwhere(edge)
    if len(pts) == 0:
        return []
    return [pts]


def simplify_path(points, tolerance=2.0):
    """Ramer–Douglas–Peucker: riduce i punti di un poligono mantenendone la forma."""
    if len(points) < 3:
        return points

    def rdp(pts, eps):
        if len(pts) < 3:
            return pts
        start, end = pts[0], pts[-1]
        d = end - start
        norm = np.sqrt(d[0]**2 + d[1]**2)
        if norm == 0:
            dists = np.sqrt(((pts - start)**2).sum(axis=1))
        else:
            dists = np.abs((pts[:, 0] - start[0]) * d[1] - (pts[:, 1] - start[1]) * d[0]) / norm
        idx = np.argmax(dists)
        if dists[idx] > eps:
            left  = rdp(pts[:idx+1], eps)
            right = rdp(pts[idx:],   eps)
            return np.vstack([left[:-1], right])
        else:
            return np.array([start, end])

    return rdp(np.array(points, dtype=np.float64), tolerance)


def catmull_rom_to_bezier(points, closed=False, tension=0.5):
    """Converte punti Catmull-Rom in una stringa SVG path con curve Bézier cubiche."""
    pts = np.array(points, dtype=np.float64)
    n   = len(pts)
    if n < 2:
        return ""

    def xy(p):
        return p[1], p[0]  # col→x, row→y

    if closed:
        p_ext = np.vstack([pts[-1:], pts, pts[:1]])
    else:
        p_ext = np.vstack([pts[:1], pts, pts[-1:]])

    d_parts = []
    x0, y0 = xy(p_ext[1])
    d_parts.append(f"M {x0:.2f},{y0:.2f}")

    segments = n if closed else n - 1
    for i in range(segments):
        p0 = p_ext[i]
        p1 = p_ext[i + 1]
        p2 = p_ext[i + 2]
        p3 = p_ext[i + 3] if (i + 3) < len(p_ext) else p_ext[-1]

        x1, y1 = xy(p1)
        x2, y2 = xy(p2)

        cp1x = x1 + tension * (xy(p2)[0] - xy(p0)[0]) / 6
        cp1y = y1 + tension * (xy(p2)[1] - xy(p0)[1]) / 6
        cp2x = x2 - tension * (xy(p3)[0] - xy(p1)[0]) / 6
        cp2y = y2 - tension * (xy(p3)[1] - xy(p1)[1]) / 6

        d_parts.append(
            f"C {cp1x:.2f},{cp1y:.2f} {cp2x:.2f},{cp2y:.2f} {x2:.2f},{y2:.2f}"
        )

    if closed:
        d_parts.append("Z")
    return " ".join(d_parts)


def is_closed_contour(points, tol=3.0):
    if len(points) < 3:
        return False
    d = np.sqrt(((points[0] - points[-1]) ** 2).sum())
    return d <= tol


def place_label_on_contour(points, label, font_size, W, H, margin=40):
    if len(points) < 2:
        return None
    candidates = []
    for i in range(len(points)):
        r, c = points[i]
        if margin < c < W - margin and margin < r < H - margin:
            candidates.append(i)
    if not candidates:
        candidates = [len(points) // 2]
    best = min(candidates, key=lambda i: points[i][0])
    i = best
    i0 = max(0, i - 3)
    i1 = min(len(points) - 1, i + 3)
    dy = points[i1][0] - points[i0][0]
    dx = points[i1][1] - points[i0][1]
    angle = np.degrees(np.arctan2(dy, dx))
    if angle > 90:
        angle -= 180
    elif angle < -90:
        angle += 180
    x = points[i][1]
    y = points[i][0]
    return x, y, angle

# ─────────────────────────────────────────────
# OUTPUT 3 — DENSITY MAP SEMPLIFICATA (fasce posterizzate sul campo smussato)
# ─────────────────────────────────────────────

def build_simplified_image(count, smoothed, ref_max, W, H):
    """
    Semplificazione della density map allineata all'SVG (output 5).

    Parte dalla STESSA matrice smussata (Gaussian blur sigma 12) usata dalle
    curve di livello e la posterizza in fasce grigie piatte: per ogni livello L
    i pixel con  smoothed >= L - 0.5  prendono il grigio  L / ref_max. I livelli
    più alti, scritti dopo, sovrascrivono i più bassi → fasce nidificate dai
    bordi morbidi e arrotondati, che combaciano con le curve dell'SVG (ma non
    sono identiche: l'SVG aggiunge la spline Catmull-Rom). Sfondo nero.
    """
    max_val = int(count.max())
    grey    = np.zeros((H, W), dtype=np.uint8)
    n       = max(max_val, 1)
    for idx, level in enumerate(range(1, max_val + 1)):
        sys.stdout.write(f"\r{progress_bar(idx + 1, n)}  livello {level}/{max_val}")
        sys.stdout.flush()
        mask = smoothed >= (level - 0.5)
        g    = int(round(min(level / max(ref_max, 1), 1.0) * 255))
        grey[mask] = g
    print()
    rgb = np.stack([grey, grey, grey], axis=-1)
    return Image.fromarray(rgb, "RGB")             # sfondo nero (copertura 0 → grey 0)

# ─────────────────────────────────────────────
# OUTPUT 4 — SEMPLIFICATA + STROKE ROSSO SU OGNI BORDO DI FASCIA
# ─────────────────────────────────────────────

def _level_contours_smoothed(count, smoothed, simplify_tol):
    """
    Per ogni livello L (1..max) estrae i contorni di {smoothed >= L-0.5} dal
    campo smussato (lo stesso dell'output 3 e dell'SVG) e li semplifica con RDP.
    Restituisce (L, [poligoni]) con poligoni = liste di tuple (x, y) intere,
    così lo stroke combacia con i bordi delle fasce dell'output 3.
    """
    max_val = int(count.max())
    n = max(max_val, 1)
    for idx, level in enumerate(range(1, max_val + 1)):
        sys.stdout.write(f"\r{progress_bar(idx + 1, n)}  livello {level}/{max_val}")
        sys.stdout.flush()
        binary   = (smoothed >= (level - 0.5))
        contours = find_contour_paths(binary)
        polys    = []
        for contour in contours:
            if len(contour) < 4:
                continue
            pts = simplify_path(contour, tolerance=simplify_tol)
            if len(pts) < 2:
                continue
            polys.append([(int(round(c)), int(round(r))) for r, c in pts])
        yield level, polys
    print()


def add_band_strokes(base_img, count, smoothed, W, H,
                     simplify_tol=SIMPLIFY_TOL_STROKE, stroke_width=STROKE_WIDTH):
    """
    Disegna un contorno rosso su OGNI bordo di fascia (gli stessi bordi morbidi
    dell'output 3), sopra l'immagine semplificata a sfondo nero.
    """
    img   = base_img.convert("RGB").copy()
    draw  = ImageDraw.Draw(img)
    color = STROKE_COLOR
    for level, polys in _level_contours_smoothed(count, smoothed, simplify_tol):
        for poly in polys:
            if len(poly) < 2:
                continue
            draw.line(poly + [poly[0]], fill=color, width=stroke_width, joint="curve")
    return img

# ─────────────────────────────────────────────
# OUTPUT 5 — CURVE DI LIVELLO SVG (invariato)
# ─────────────────────────────────────────────

def build_svg_contours(count, n_files, W, H,
                       blur_sigma=CONTOUR_BLUR_SIGMA,
                       line_width=CONTOUR_LINE_WIDTH,
                       line_color=CONTOUR_LINE_COLOR,
                       bg_color=CONTOUR_BG_COLOR,
                       font_size=LABEL_FONT_SIZE,
                       label_every=LABEL_EVERY,
                       simplify_tol=1.5,
                       tension=0.5,
                       smoothed=None):
    """Genera il contenuto SVG con le curve di livello morbide (Catmull-Rom)."""
    max_val = int(count.max())
    levels  = list(range(1, max_val + 1))

    if smoothed is None:
        print(f"\n  Smoothing della matrice (sigma={blur_sigma})...")
        smoothed = smooth_count(count, blur_sigma)

    svg_lines = []
    svg_lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">'
    )
    svg_lines.append(
        f'  <rect x="0" y="0" width="{W}" height="{H}" fill="{bg_color}" />'
    )
    svg_lines.append(
        f'  <style>'
        f'    .contour-line {{ fill: none; stroke: {line_color}; '
        f'stroke-width: {line_width}pt; stroke-linejoin: round; stroke-linecap: round; }}'
        f'    .contour-label {{ font-family: monospace; font-size: {font_size}px; '
        f'fill: {line_color}; text-anchor: middle; dominant-baseline: middle; }}'
        f'  </style>'
    )

    n = len(levels)
    for idx, level in enumerate(levels):
        sys.stdout.write(f"\r{progress_bar(idx + 1, n)}  livello {level}/{max_val}")
        sys.stdout.flush()

        threshold = level - 0.5
        binary    = (smoothed >= threshold)
        contours  = find_contour_paths(binary)
        if not contours:
            continue

        svg_lines.append(f'  <g id="level-{level}">')
        label_placed = False
        for contour in contours:
            if len(contour) < 4:
                continue
            pts = simplify_path(contour, tolerance=simplify_tol)
            if len(pts) < 2:
                continue
            closed = is_closed_contour(pts)
            d = catmull_rom_to_bezier(pts, closed=closed, tension=tension)
            if not d:
                continue
            svg_lines.append(f'    <path class="contour-line" d="{d}" />')

            if not label_placed and (level % label_every == 0 or level == 1 or level == max_val):
                result = place_label_on_contour(pts, str(level), font_size, W, H)
                if result:
                    lx, ly, angle = result
                    label_text = f"{level}/{n_files}"
                    svg_lines.append(
                        f'    <text class="contour-label" '
                        f'x="{lx:.1f}" y="{ly:.1f}" '
                        f'transform="rotate({angle:.1f},{lx:.1f},{ly:.1f})">'
                        f'{label_text}</text>'
                    )
                    label_placed = True
        svg_lines.append('  </g>')

    print()
    svg_lines.append('</svg>')
    return "\n".join(svg_lines)

# ─────────────────────────────────────────────
# PASSI GUIDATI
# ─────────────────────────────────────────────

def passo_benvenuto():
    header("Benvenuto!")
    print("  Questo strumento usa 31 maschere PNG (geometrie rosse) e")
    print("  un'immagine originale per generare CINQUE output visivi:\n")
    print("    1)  Composito delle maschere sull'originale   (PNG, trasparente)")
    print("    2)  Density map B&N                            (PNG, sfondo nero)")
    print("    3)  Density map semplificata (posterizzata)    (PNG, sfondo nero)")
    print("    4)  Semplificata + stroke rosso su ogni fascia (PNG, sfondo nero)")
    print("    5)  Curve di livello                           (SVG, sfondo nero)\n")
    print("  Ogni output ha il proprio gate: puoi generarlo o saltarlo.\n")
    print("  Struttura cartella attesa:\n")
    print("    progetto/")
    print("    ├── density_map.py")
    print("    ├── original.png   ← immagine originale")
    print("    ├── livelli/       ← 31 maschere PNG")
    print("    └── output/        ← generata automaticamente\n")
    line("─")
    pausa()


def passo_1_cartella():
    header("Verifica input", f"1 di {N_STEPS}")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cartella   = os.path.join(script_dir, "livelli")
    original   = os.path.join(script_dir, ORIGINAL_NAME)

    print("  Lo script cerca, accanto al file .py:\n")
    info(f"Cartella maschere: {cartella}")
    info(f"Originale:         {original}")
    print()

    mancano = []
    if os.path.isdir(cartella):
        ok("Cartella 'livelli' trovata.")
    else:
        err("Cartella 'livelli' non trovata.")
        mancano.append("la cartella 'livelli' con i PNG delle maschere")

    if os.path.isfile(original):
        ok(f"'{ORIGINAL_NAME}' trovato.")
    else:
        err(f"'{ORIGINAL_NAME}' non trovato.")
        mancano.append(f"il file '{ORIGINAL_NAME}' (immagine originale)")

    if mancano:
        print()
        print("  Prima di procedere aggiungi accanto allo script:")
        for m in mancano:
            print(f"    • {m}")
        line("─")
        pausa("Premi INVIO per uscire.")
        sys.exit(1)

    pausa()
    return cartella, original


def passo_2_file(cartella):
    header("Rilevamento maschere", f"2 di {N_STEPS}")
    pattern = os.path.join(cartella, "*.png")
    files   = sorted(glob.glob(pattern), key=natural_sort_key)
    print(f"  Pattern:  N.png  (es. 0.png, 1.png, ...)")
    print(f"  Cartella: {cartella}\n")
    if not files:
        err("Nessun file trovato con questo pattern.")
        print()
        print("  Assicurati che i file in 'livelli' seguano il formato 0.png, 1.png, ...")
        line("─")
        pausa("Premi INVIO per uscire.")
        sys.exit(1)
    print(f"  Maschere trovate: {len(files)}\n")
    for i, f in enumerate(files):
        print(f"    {i+1:02d}.  {os.path.basename(f)}")
    with Image.open(files[0]) as ref:
        W, H = ref.size
        mode = ref.mode
    print()
    info(f"Risoluzione: {W} × {H} px  |  Modalità: {mode}")
    print()
    line("─")
    if ask_yes_no("Procedere con questi file?"):
        pausa()
        return files, W, H
    else:
        pausa("Operazione annullata. Premi INVIO per uscire.")
        sys.exit(0)


def passo_3_config(n_files):
    header("Configurazione parametri", f"3 di {N_STEPS}")

    print("  MODALITÀ DI NORMALIZZAZIONE\n")
    print(f"    1  →  ASSOLUTA  (ogni livello vale {100/n_files:.2f}%)")
    print( "    2  →  RELATIVA  (il massimo valido → bianco puro #ffffff)")
    print()
    while True:
        scelta = ask("Scegli modalità (1 o 2)", "2")
        if scelta in ("1", "2"):
            break
        warn("Inserisci 1 oppure 2.")
    modalita = "assoluta" if scelta == "1" else "relativa"
    print()
    ok(f"Modalità selezionata: {modalita.upper()}")

    print()
    line("─")
    print("  PARAMETRI RILEVAMENTO ROSSO\n")
    info("Valori predefiniti (consigliati per rosso puro #FF0000):")
    info("  R ≥ 180,  G ≤ 80,  B ≤ 80")
    print()
    if ask_yes_no("Usare i valori predefiniti?", default=True):
        r_min, g_max, b_max = 180, 80, 80
    else:
        print()
        r_min = int(ask("Canale R minimo  (0–255)", "180"))
        g_max = int(ask("Canale G massimo (0–255)", "80"))
        b_max = int(ask("Canale B massimo (0–255)", "80"))

    print()
    line("─")
    print("  RIEPILOGO CONFIGURAZIONE\n")
    info(f"Numero maschere:  {n_files}")
    info(f"Modalità:         {modalita.upper()}")
    if modalita == "assoluta":
        info(f"Peso per livello: {100/n_files:.2f}%")
    else:
        info(f"Riferimento:      massimo valido (≥ {MIN_PIXEL:,} pixel) → #ffffff")
    info(f"Soglia rosso:     R ≥ {r_min},  G ≤ {g_max},  B ≤ {b_max}")
    info(f"Output previsti:  5 (composito, density, semplificata, +stroke, SVG)")
    print()
    line("─")

    if not ask_yes_no("Confermare e avviare l'analisi?"):
        pausa("Configurazione annullata. Premi INVIO per ripetere il passo.")
        return passo_3_config(n_files)

    pausa()
    return modalita, r_min, g_max, b_max


def passo_4_analisi(files, W, H, modalita, r_min, g_max, b_max):
    header("Analisi e normalizzazione", f"4 di {N_STEPS}")
    n = len(files)
    print(f"  Analisi di {n} maschere PNG...\n")
    t0      = time.time()
    count   = build_count(files, H, W, r_min, g_max, b_max)
    elapsed = time.time() - t0
    print()
    ok(f"Maschere analizzate in {elapsed:.1f}s")

    max_raw = int(count.max())
    covered = int((count > 0).sum())
    total   = H * W

    print()
    info(f"Pixel totali:               {total:>12,}")
    info(f"Pixel con copertura > 0:    {covered:>12,}  ({covered/total*100:.2f}%)")
    info(f"Massimo grezzo rilevato:    {max_raw:>12} / {n}")

    print()
    line("─")
    print("  DISTRIBUZIONE PIXEL PER NUMERO DI SELEZIONI\n")
    for v in range(1, max_raw + 1):
        c = int((count == v).sum())
        if c > 0:
            flag = "  ✗ sotto soglia" if (c < MIN_PIXEL) else ""
            bar  = "▪" * min(int(c / total * 400), 30)
            print(f"  {v:>3}/{n}   {c:>8,}px  {bar}{flag}")

    if modalita == "relativa":
        effective_max, effective_px = find_effective_max(count, MIN_PIXEL)
        print()
        line("─")
        print("  SELEZIONE MASSIMO DI RIFERIMENTO\n")
        if effective_max < max_raw:
            warn(f"I livelli {effective_max+1}/{n} – {max_raw}/{n} hanno meno di "
                 f"{MIN_PIXEL:,} pixel e sono stati scartati.")
            print()
        info(f"Massimo scelto come riferimento:  {effective_max}/{n}  "
             f"({effective_px:,} pixel)")
        info(f"Questo livello verrà mappato a bianco puro #ffffff.")
        print()
        line("─")
        if not ask_yes_no("Confermare e procedere con questo massimo?"):
            print()
            while True:
                try:
                    val = int(ask(f"Inserisci manualmente il massimo (1–{max_raw})",
                                  str(effective_max)))
                    if 1 <= val <= max_raw:
                        effective_max = val
                        effective_px  = int((count == val).sum())
                        break
                    warn(f"Inserisci un valore tra 1 e {max_raw}.")
                except ValueError:
                    warn("Inserisci un numero intero.")
            ok(f"Massimo impostato manualmente: {effective_max}/{n}  "
               f"({effective_px:,} pixel)")
        ref_max = effective_max
        norm    = normalize_relative(count, effective_max)
    else:
        ref_max = n
        norm    = normalize_absolute(count, n)

    print()
    print(f"  Smoothing condiviso per output 3/4/5 (sigma={CONTOUR_BLUR_SIGMA})...")
    smoothed = smooth_count(count, CONTOUR_BLUR_SIGMA)
    ok("Normalizzazione completata.")
    pausa()
    return count, norm, ref_max, n, smoothed


def passo_5_composito(original_path, count, ref_max, W, H, suffix):
    header("Output 1 — Composito maschere sull'originale", f"5 di {N_STEPS}")
    info("Ogni maschera ritaglia l'originale (tiene i pixel dove è rossa).")
    info("I 31 ritagli si sommano con logica lineare = normalizzazione relativa:")
    info("  alpha = min(copertura / riferimento, 1)   colore = pixel originale")
    info("Sfondo trasparente.")
    print()
    line("─")
    if not ask_yes_no("Generare il composito?"):
        pausa("Output 1 saltato. Premi INVIO per continuare.")
        return

    print()
    print("  Caricamento originale e composizione...\n")
    original_rgb = load_original(original_path, W, H)
    img = build_composite_linear(original_rgb, count, ref_max)

    out_dir  = get_out_dir()
    filename = f"composite_{suffix}.png"
    img.save(os.path.join(out_dir, filename), "PNG")
    print()
    ok(f"{filename}  salvato")
    pausa()


def passo_6_density(norm, suffix):
    header("Output 2 — Density map B&N", f"6 di {N_STEPS}")
    info("Density map in scala di grigi, sfondo nero (copertura 0 → nero).")
    print()
    line("─")
    if not ask_yes_no("Generare la density map?"):
        pausa("Output 2 saltato. Premi INVIO per continuare.")
        return

    print()
    print("  Generazione density map...\n")
    img = build_density_image(norm)

    out_dir  = get_out_dir()
    filename = f"density_map_{suffix}.png"
    img.save(os.path.join(out_dir, filename), "PNG")
    ok(f"{filename}  salvato")
    pausa()


def passo_7_semplificata(count, smoothed, ref_max, W, H, suffix):
    header("Output 3 — Density map semplificata", f"7 di {N_STEPS}")
    info("Posterizzazione del campo smussato (sigma 12): fasce piatte e fuse,")
    info("bordi morbidi allineati alle curve dell'SVG. Sfondo nero.")
    print()
    line("─")
    if not ask_yes_no("Generare la versione semplificata?"):
        pausa("Output 3 saltato. Premi INVIO per continuare.")
        return None

    print()
    print("  Posterizzazione del campo smussato...\n")
    img = build_simplified_image(count, smoothed, ref_max, W, H)

    out_dir  = get_out_dir()
    filename = f"density_map_{suffix}_simplified.png"
    img.save(os.path.join(out_dir, filename), "PNG")
    print()
    ok(f"{filename}  salvato")
    pausa()
    return img


def passo_8_stroke(simplified_img, count, smoothed, ref_max, W, H, suffix):
    header("Output 4 — Semplificata + stroke rosso", f"8 di {N_STEPS}")
    info(f"Contorno rosso #ff0000 ({STROKE_WIDTH}px) su OGNI bordo di fascia,")
    info("sopra l'immagine semplificata. Sfondo nero.")
    print()
    line("─")
    if not ask_yes_no("Generare la versione con stroke rosso?"):
        pausa("Output 4 saltato. Premi INVIO per continuare.")
        return

    # Se l'output 3 è stato saltato, ricostruisco la base internamente.
    if simplified_img is None:
        print()
        print("  (Output 3 saltato: ricostruisco la base semplificata...)\n")
        simplified_img = build_simplified_image(count, smoothed, ref_max, W, H)

    print()
    print("  Tracciamento stroke sui bordi di fascia...\n")
    img = add_band_strokes(simplified_img, count, smoothed, W, H)

    out_dir  = get_out_dir()
    filename = f"density_map_{suffix}_simplified_stroke.png"
    img.save(os.path.join(out_dir, filename), "PNG")
    print()
    ok(f"{filename}  salvato")
    pausa()


def passo_9_contour_svg(count, smoothed, n_files, W, H, suffix):
    header("Output 5 — Curve di livello SVG", f"9 di {N_STEPS}")
    max_val = int(count.max())
    info(f"Dimensioni:      {W} × {H} px")
    info(f"Livelli totali:  {max_val}")
    info(f"Smoothing sigma: {CONTOUR_BLUR_SIGMA}")
    info(f"Spessore linee:  {CONTOUR_LINE_WIDTH}pt")
    info(f"Stile curve:     Catmull-Rom spline (morbide)")
    info(f"Etichette:       ogni livello  (formato N/{n_files})")
    info(f"Sfondo / linee:  nero / bianco")
    print()
    line("─")
    if not ask_yes_no("Generare l'SVG?"):
        pausa("Output 5 saltato. Premi INVIO per terminare.")
        return

    print()
    t0  = time.time()
    svg = build_svg_contours(
        count=count, n_files=n_files, W=W, H=H,
        blur_sigma=CONTOUR_BLUR_SIGMA,
        line_width=CONTOUR_LINE_WIDTH,
        line_color=CONTOUR_LINE_COLOR,
        bg_color=CONTOUR_BG_COLOR,
        font_size=LABEL_FONT_SIZE,
        label_every=LABEL_EVERY,
        simplify_tol=1.5,
        tension=0.5,
        smoothed=smoothed,
    )
    elapsed = time.time() - t0

    out_dir      = get_out_dir()
    filename_svg = f"density_map_{suffix}_contour.svg"
    with open(os.path.join(out_dir, filename_svg), "w", encoding="utf-8") as f:
        f.write(svg)

    print()
    ok(f"SVG generato in {elapsed:.1f}s")
    ok(f"{filename_svg}  salvato")
    pausa()


def riepilogo_finale():
    header("Elaborazione completata")
    out_dir = get_out_dir()
    line("═")
    print("  ELABORAZIONE COMPLETATA  ✓")
    line("═")
    print()
    info(f"File generati in: {out_dir}")
    print()
    line("═")
    pausa("Premi INVIO per uscire.")

# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def main():
    try:
        passo_benvenuto()
        cartella, original_path        = passo_1_cartella()
        files, W, H                    = passo_2_file(cartella)
        modalita, r_min, g_max, b_max  = passo_3_config(len(files))
        count, norm, ref_max, n, smoothed = passo_4_analisi(
                                                 files, W, H,
                                                 modalita, r_min, g_max, b_max)
        suffix = modalita

        passo_5_composito(original_path, count, ref_max, W, H, suffix)
        passo_6_density(norm, suffix)
        simplified = passo_7_semplificata(count, smoothed, ref_max, W, H, suffix)
        passo_8_stroke(simplified, count, smoothed, ref_max, W, H, suffix)
        passo_9_contour_svg(count, smoothed, n, W, H, suffix)

        riepilogo_finale()

    except KeyboardInterrupt:
        print("\n\n  Operazione interrotta. Arrivederci.")
        sys.exit(0)


if __name__ == "__main__":
    main()
