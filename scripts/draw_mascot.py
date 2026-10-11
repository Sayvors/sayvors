"""Draw the Sayvors mascot as a parametric character.

The mascot is the brand mark: the ring is the head, the signal arcs are its voice.
Every cell comes out of this one function, so both atlases are identical in scale and
registration by construction -- there is nothing to measure, align or correct, and the
key-colour failure that spoiled the previous sheets cannot happen.

    python scripts/draw_mascot.py

Writes characters/sayvors/{directions,reactions}.png as the re-buildable masters, then
composes apps/web/public/mascots/sayvors-{directions,reactions}.webp for the app.
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'characters', 'sayvors')
DEST = os.path.join(ROOT, 'apps', 'web', 'public', 'mascots')

CELL = 480          # source cell edge
TILE = 360          # served tile edge -- unchanged, so nothing on the page resizes
K = 3               # supersample factor

# Sayvors Brand Guidelines, live tokens from apps/web/app/globals.css.
VIOLET = (91, 45, 142, 255)
VIOLET_LIGHT = (139, 92, 246, 255)
MAGENTA = (217, 70, 168, 255)
CORAL = (255, 79, 110, 255)
CORAL_FADE = (255, 79, 110, 140)
BLUSH = (255, 138, 165, 150)
INK = (26, 18, 48, 255)
WHITE = (255, 255, 255, 255)
LIFT = (255, 255, 255, 120)      # top-left light inset
SHADE = (26, 18, 48, 70)         # bottom-right shade inset

# The mark, in fractions of the cell edge.
HX, HY = 0.395, 0.335             # head centre, left of centre to leave the arcs room
R = 0.255                         # ring outer radius
HOLE = 0.132                      # face field radius
BODY_TOP = HY + R - 0.030
BODY_H = 0.300
BODY_W = 0.300
BODY_CORNER = 0.25 * BODY_H       # radius ~25% of element height, per the UI rules

# radius offset, stroke width, colour, half-window in degrees, window tilt
ARCS = (
    (R + 0.032, 0.050, MAGENTA, 50, MAGENTA),
    (R + 0.105, 0.044, CORAL, 44, CORAL),
    (R + 0.170, 0.038, CORAL_FADE, 38, CORAL_FADE),
)

# Matches DIRECTIONS in apps/web/components/Mascot.tsx: clockwise from up-left.
DIRECTIONS = (
    (-0.72, -0.69), (0.0, -1.0), (0.72, -0.69),
    (-1.0, 0.0), (0.0, 0.0), (1.0, 0.0),
    (-0.72, 0.69), (0.0, 1.0), (0.72, 0.69),
)
# Matches REACTIONS in apps/web/components/Mascot.tsx.
REACTIONS = ('blink', 'heart', 'sparkle', 'surprised', 'wink',
            'bashful', 'error', 'dizzy', 'delighted')


def ring(cx, cy, r):
    return [cx - r, cy - r, cx + r, cy + r]


def oval(cx, cy, rx, ry):
    return [cx - rx, cy - ry, cx + rx, cy + ry]


def capsule(draw, x1, y1, x2, y2, width, colour):
    """A line with round caps -- PIL has no round cap, so terminate it by hand."""
    draw.line((x1, y1, x2, y2), fill=colour, width=int(round(width)))
    for x, y in ((x1, y1), (x2, y2)):
        draw.ellipse([x - width / 2, y - width / 2, x + width / 2, y + width / 2], fill=colour)


def arc_stroke(draw, cx, cy, radius, half_deg, width, colour, tilt=0.0):
    a0, a1 = -half_deg + tilt, half_deg + tilt
    draw.arc(ring(cx, cy, radius), a0, a1, fill=colour, width=int(round(width)))
    # PIL strokes an arc inward from the path, so a cap the full stroke width reads as a
    # bead stuck on the end. Slightly under it, and the tip closes flush.
    for a in (a0, a1):
        rad = math.radians(a)
        cap = width * 0.40
        draw.ellipse(
            [cx + radius * math.cos(rad) - cap, cy + radius * math.sin(rad) - cap,
             cx + radius * math.cos(rad) + cap, cy + radius * math.sin(rad) + cap],
            fill=colour)


def star(draw, cx, cy, r, colour, points=4, inner=0.34):
    path = []
    for i in range(points * 2):
        rad = math.radians(i * 180.0 / points - 90)
        length = r if i % 2 == 0 else r * inner
        path.append((cx + length * math.cos(rad), cy + length * math.sin(rad)))
    draw.polygon(path, fill=colour)


def heart(draw, cx, cy, r, colour):
    draw.ellipse([cx - r, cy - r * 0.85, cx, cy + r * 0.15], fill=colour)
    draw.ellipse([cx, cy - r * 0.85, cx + r, cy + r * 0.15], fill=colour)
    draw.polygon([(cx - r * 0.98, cy - r * 0.15), (cx + r * 0.98, cy - r * 0.15),
                  (cx, cy + r)], fill=colour)


def spiral(draw, cx, cy, r, colour, turns=2.4):
    path = []
    for i in range(90):
        t = i / 89.0
        rad = math.radians(t * turns * 360)
        length = r * t
        path.append((cx + length * math.cos(rad), cy + length * math.sin(rad)))
    draw.line(path, fill=colour, width=int(round(r * 0.26)), joint='curve')


def wavy(draw, cx, cy, w, amp, colour, weight, cycles=3):
    path = [(cx - w / 2 + w * (i / 40.0),
             cy + amp * math.sin(i / 40.0 * cycles * 2 * math.pi)) for i in range(41)]
    draw.line(path, fill=colour, width=int(round(weight)), joint='curve')


def draw_face(draw, cx, cy, u, expr, gx, gy, blink_l=False, blink_r=False):
    """The face, in units of the face field radius u. gx/gy are the gaze in [-1, 1]."""
    ex, ey = 0.47 * u, -0.08 * u        # eye centres
    er = 0.24 * u                      # eye radius
    lid = max(0.026 * u, 0.030 * u)    # stroke weight for closed eyes
    mouth_y = 0.47 * u
    if expr == 'wink':
        blink_r = True

    if expr == 'heart':
        heart(draw, cx - ex, cy + ey, er * 1.05, CORAL)
        heart(draw, cx + ex, cy + ey, er * 1.05, CORAL)
    elif expr == 'dizzy':
        spiral(draw, cx - ex, cy + ey, er, INK)
        spiral(draw, cx + ex, cy + ey, er, INK)
    else:
        for side, closed in ((-1, blink_l), (1, blink_r)):
            if expr in ('blink', 'sleepy', 'sparkle', 'delighted') or closed:
                # A relaxed lid curves down; a happy closed eye arches up.
                if expr in ('sparkle', 'delighted'):
                    draw.arc(ring(cx + side * ex, cy + ey, er), 200, 340, fill=INK,
                             width=int(round(lid)))
                elif expr == 'sleepy':
                    draw.arc(ring(cx + side * ex, cy + ey, er * 0.9), 20, 160, fill=INK,
                             width=int(round(lid)))
                else:
                    draw.arc(ring(cx + side * ex, cy + ey, er * 0.85), 200, 340, fill=INK,
                             width=int(round(lid)))
            else:
                px = cx + side * ex + gx * er * 0.46
                py = cy + ey + gy * er * 0.40
                draw.ellipse(ring(px, py, er), fill=INK)
                draw.ellipse(ring(px - er * 0.30, py - er * 0.34, er * 0.34),
                             fill=(255, 255, 255, 190))

    for side in (-1, 1):
        # Blush reads as contentment, so it has no place on the unhappy faces.
        if expr not in ('error', 'dizzy'):
            draw.ellipse(ring(cx + side * 0.70 * u, cy + 0.22 * u, 0.17 * u), fill=BLUSH)

    mw = 0.40 * u
    if expr == 'error':
        # Concerned, not disappointed: a small uncertain mouth and level eyes. A
        # frown or a wide-open alarm face reads as blame, which is wrong here --
        # the user has not done anything wrong, they have not finished yet.
        wavy(draw, cx, cy + mouth_y, mw * 1.5, 0.038 * u, INK, lid * 0.85, cycles=2)
    elif expr == 'surprised':
        draw.ellipse(ring(cx, cy + mouth_y, 0.20 * u), fill=INK)
        draw.ellipse(ring(cx, cy + mouth_y + 0.06 * u, 0.11 * u), fill=(255, 138, 165, 200))
    elif expr in ('calm', 'blink', 'wink'):
        draw.arc(ring(cx, cy + mouth_y - 0.06 * u, mw), 20, 160, fill=INK,
                 width=int(round(lid)))
    elif expr == 'bashful':
        wavy(draw, cx, cy + mouth_y, mw * 2, 0.055 * u, INK, lid * 0.85)
    elif expr == 'sleepy':
        draw.ellipse(ring(cx, cy + mouth_y - 0.02 * u, 0.17 * u), fill=INK)
    elif expr == 'dizzy':
        wavy(draw, cx, cy + mouth_y, mw * 2, 0.055 * u, INK, lid * 0.85)
    else:  # heart, sparkle, delighted
        draw.ellipse(oval(cx, cy + mouth_y - 0.02 * u, mw, 0.26 * u), fill=INK)
        draw.ellipse(oval(cx, cy + mouth_y + 0.13 * u, mw * 0.62, 0.13 * u),
                     fill=(255, 138, 165, 210))


def draw_decor(draw, n, expr, u):
    """Floating marks. Drawn small and clear of the silhouette, per the art rules."""
    if expr == 'heart':
        heart(draw, 0.185 * n, 0.115 * n, 0.052 * n, CORAL)
    elif expr == 'sparkle':
        star(draw, 0.175 * n, 0.100 * n, 0.046 * n, (243, 158, 11, 255))
        star(draw, 0.262 * n, 0.175 * n, 0.030 * n, (243, 158, 11, 235))
        star(draw, 0.146 * n, 0.212 * n, 0.026 * n, (243, 158, 11, 220))
    elif expr == 'delighted':
        star(draw, 0.190 * n, 0.128 * n, 0.040 * n, (243, 158, 11, 255))
        star(draw, 0.268 * n, 0.090 * n, 0.026 * n, (243, 158, 11, 220))
    elif expr == 'sleepy':
        for i, (x, y, s) in enumerate(((0.175, 0.150, 0.046), (0.250, 0.088, 0.036))):
            w = s * n
            z = [(x * n - w / 2, y * n - w / 2), (x * n + w / 2, y * n - w / 2),
                 (x * n - w / 2, y * n + w / 2), (x * n + w / 2, y * n + w / 2)]
            draw.line(z, fill=(139, 92, 246, 235 - i * 60), width=int(round(0.013 * n)))
    elif expr == 'dizzy':
        for x, y, r in ((0.150, 0.110, 0.030), (0.268, 0.140, 0.026)):
            star(draw, x * n, y * n, r * n, VIOLET_LIGHT)
    elif expr == 'surprised':
        for x, y, r in ((0.168, 0.128, 0.034), (0.272, 0.196, 0.026)):
            star(draw, x * n, y * n, r * n, (243, 158, 11, 235))


def draw_cell(yaw=0.0, pitch=0.0, expr='calm'):
    n = CELL * K

    def s(v):
        return v * n

    # The head squashes a little as it turns; the body stays planted.
    rx = R * (1 - 0.14 * abs(yaw))
    ry = R * (1 + 0.05 * abs(yaw))

    art = Image.new('RGBA', (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(art)

    # Signal arcs, behind the head. They swing with the turn and tuck away when the
    # character looks off them, which is what sells the direction at small sizes.
    tilt = yaw * 9.0
    shrink = 1 - 0.14 * max(0.0, -yaw)
    for radius, width, colour, half, solid in ARCS:
        arc_stroke(d, s(HX + (1 - shrink) * 0.05), s(HY + pitch * 0.018),
                   s(radius * shrink), half * (1 - 0.10 * abs(yaw)),
                   s(width), colour, tilt)

    # Body: rounded slab, white belly, stub arms and feet.
    bx0, by0 = s(HX - BODY_W / 2), s(BODY_TOP)
    bx1, by1 = s(HX + BODY_W / 2), s(BODY_TOP + BODY_H)
    rad = s(BODY_CORNER)
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=rad, fill=VIOLET)
    belly_cx, belly_cy = s(HX), s(BODY_TOP + BODY_H * 0.58)
    d.ellipse(oval(belly_cx, belly_cy, s(0.076), s(0.080)), fill=WHITE)
    for side in (-1, 1):
        capsule(d, s(HX + side * BODY_W * 0.46), s(BODY_TOP + BODY_H * 0.42),
                s(HX + side * (BODY_W * 0.46 + 0.052)), s(BODY_TOP + BODY_H * 0.74),
                s(0.038), VIOLET)
        d.ellipse(oval(s(HX + side * 0.084), s(BODY_TOP + BODY_H + 0.006),
                       s(0.046), s(0.040)), fill=VIOLET)

    # The belly's own edge carries the light; a bevel arc across the body reads as a handle.

    # Head: the ring.
    hx, hy = s(HX), s(HY)
    d.ellipse([hx - s(rx), hy - s(ry), hx + s(rx), hy + s(ry)], fill=VIOLET)

    band = R - HOLE
    for radius, a0, a1, colour, weight in (
            (rx - band * 0.30, 186, 302, LIFT, 0.030),
            (rx - band * 0.30, 0, 116, SHADE, 0.030),
            (HOLE + band * 0.30, 0, 116, (26, 18, 48, 45), 0.018)):
        d.arc(ring(hx, hy, s(radius)), a0, a1, fill=colour,
              width=int(round(s(weight))))

    # Face field -- the white centre of the mark.
    fx = hx + yaw * s(HOLE * 0.38)
    fy = hy + pitch * s(HOLE * 0.34)
    d.ellipse(ring(fx, fy, s(HOLE)), fill=WHITE)
    draw_face(d, fx, fy, s(HOLE), expr, yaw, pitch)

    draw_decor(d, n, expr, s(HOLE))

    # Lean, about the base of the body so the feet stay planted.
    lean = -yaw * 6.0 + pitch * 3.0
    if lean:
        art = art.rotate(lean, resample=Image.BICUBIC, center=(hx, s(BODY_TOP + BODY_H)))

    # Soft drop shadow under everything.
    alpha = art.getchannel('A')
    shadow = Image.new('L', (n, n), 0)
    shadow.paste(alpha, (int(s(0.010)), int(s(0.016))))
    shadow = shadow.filter(ImageFilter.GaussianBlur(s(0.014)))
    shade_layer = Image.new('RGBA', (n, n), INK[:3] + (0,))
    shade_layer.putalpha(shadow.point(lambda v: int(v * 0.30)))

    out = Image.alpha_composite(shade_layer, art)
    return out.resize((CELL, CELL), Image.LANCZOS)


def fit(cells, margin=0.035):
    """One uniform scale and offset applied to every cell, so nothing can clip an edge.

    The lean swings the outermost arc towards the cell border on the hard turns. Fitting
    per cell would reintroduce exactly the size drift the character must not have, so the
    union of all eighteen frames is measured once and that single transform goes on every
    one of them.
    """
    boxes = [c.getbbox() for c in cells]
    left = min(b[0] for b in boxes)
    top = min(b[1] for b in boxes)
    right = max(b[2] for b in boxes)
    bottom = max(b[3] for b in boxes)
    usable = CELL * (1 - 2 * margin)
    scale = min(usable / (right - left), usable / (bottom - top))
    out = []
    for cell in cells:
        canvas = Image.new('RGBA', (CELL, CELL), (0, 0, 0, 0))
        scaled = cell.resize((round(CELL * scale), round(CELL * scale)), Image.LANCZOS)
        canvas.alpha_composite(
            scaled, (round((CELL - scaled.size[0]) / 2 - left * scale),
                     round((CELL - scaled.size[1]) / 2 - top * scale)))
        out.append(canvas)
    return out


def sheet(cells):
    img = Image.new('RGBA', (CELL * 3, CELL * 3), (0, 0, 0, 0))
    for i, cell in enumerate(cells):
        img.paste(cell, ((i % 3) * CELL, (i // 3) * CELL))
    return img


def save(sheet_img, name, dest):
    os.makedirs(dest, exist_ok=True)
    sheet_img.resize((TILE * 3, TILE * 3), Image.LANCZOS).save(
        os.path.join(dest, name), quality=92, method=6)
    print(f'  {name}  {os.path.getsize(os.path.join(dest, name)) // 1024} KB  alpha ok '
          f'{sheet_img.getchannel("A").getextrema()[1]}')


directions = [draw_cell(yaw=y, pitch=p, expr='calm') for y, p in DIRECTIONS]
reactions = [draw_cell(yaw=0.0, pitch=0.0, expr=e) for e in REACTIONS]

# Both sheets are fitted together: the same transform has to reach both, or a boop that
# swaps atlases changes the character's size.
all_cells = fit(directions + reactions)
directions, reactions = all_cells[:9], all_cells[9:]

os.makedirs(SRC, exist_ok=True)
for img, name in ((sheet(directions), 'directions.png'), (sheet(reactions), 'reactions.png')):
    img.save(os.path.join(SRC, name))
    print(f'  {os.path.join("characters", "sayvors", name)}')

save(sheet(directions), 'sayvors-directions.webp', DEST)
save(sheet(reactions), 'sayvors-reactions.webp', DEST)