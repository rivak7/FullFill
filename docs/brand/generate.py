# FullFill brand generator: hand-drawn "f ü l l" where the second letter is a u/i blend
# (dot = i's tittle, arc = a happy eye, u = the smile). Run: python3 docs/brand/generate.py docs/brand
import cairosvg, os, sys
OUT = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(OUT + "/svg", exist_ok=True); os.makedirs(OUT + "/png", exist_ok=True)

INK, FOREST, OLIVE, GREY, PAPER, CARD = "#202a23", "#173e32", "#5c6b3a", "#74776c", "#f4f3ee", "#fffef9"
DARK_BG, DARK_INK, SAGE = "#141813", "#f4f3ee", "#a9b585"
SW = 11  # marker stroke width

def f(x):
    return [f"M{x+28} 152 C{x+27} 126 {x+22} 96 {x+26} 77 C{x+29} 61 {x+42} 55 {x+56} 62",
            f"M{x} 104 C{x+16} 102 {x+36} 101 {x+57} 98"]
def ui(x):  # smile (u) + arc (happy eye); the dot is drawn separately
    return [f"M{x-1} 108 C{x} 132 {x+10} 148 {x+26} 148 C{x+43} 148 {x+53} 133 {x+55} 109",
            f"M{x+35} 90 C{x+39} 80 {x+52} 80 {x+56} 90"]
UI_DOT = (-1, 88)
def l(x, top, bot):
    return [f"M{x} {top} C{x-1} {top+30} {x+1} {bot-26} {x+2} {bot}"]

def strokes(ds, color, sw=SW):
    return "".join(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"/>' for d in ds)
def face(x, color, sw=SW):
    return strokes(ui(x), color, sw) + f'<circle cx="{x+UI_DOT[0]}" cy="{UI_DOT[1]}" r="{sw*0.64}" fill="{color}"/>'

def letters(ink, accent):
    return strokes(f(0) + l(164, 66, 144) + l(202, 60, 147), ink) + face(80, accent)
BBOX = (-SW/2, 55 - SW/2, 204 + SW/2, 152 + SW/2)

def svg(w, h, body, vb=None, title="FullFill"):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb or f"0 0 {w} {h}"}" width="{w}" height="{h}" role="img" aria-label="{title}"><title>{title}</title>{body}</svg>'

def wordmark(ink, accent, pad=20):
    x0, y0, x1, y1 = BBOX[0]-pad, BBOX[1]-pad, BBOX[2]+pad, BBOX[3]+pad
    return svg(round(x1-x0), round(y1-y0), letters(ink, accent), f"{x0} {y0} {x1-x0} {y1-y0}")

def icon(fg, bg, size=512, radius=0.22, k=1.0, w=0.9):  # the u/i face alone
    sc = size / 100 * 0.92 * k
    cx, cy = 80 + 28, 117
    rect = f'<rect width="{size}" height="{size}"' + (f' rx="{size*radius}"' if radius else "") + f' fill="{bg}"/>'
    return svg(size, size, rect + f'<g transform="translate({size/2} {size/2}) scale({sc}) translate({-cx} {-cy})">{face(80, fg, SW*w)}</g>')

def icon_word(fg, accent, bg, size=512, radius=0.22):
    sc = size * 0.72 / (BBOX[2]-BBOX[0])
    g = f'<g transform="translate({size/2} {size/2}) scale({sc}) translate({-102} {-104})">{letters(fg, accent)}</g>'
    return svg(size, size, f'<rect width="{size}" height="{size}" rx="{size*radius}" fill="{bg}"/>' + g)

def og(w=1200, h=630):
    sc = 2.4
    body = f'<rect width="{w}" height="{h}" fill="{PAPER}"/>'
    body += f'<g transform="translate({w/2} 245) scale({sc}) translate(-102 -104)">{letters(INK, OLIVE)}</g>'
    body += f'<text x="{w/2}" y="450" text-anchor="middle" font-family="Inter, sans-serif" font-size="40" font-weight="600" fill="{INK}">Every order checked before it leaves the counter.</text>'
    body += f'<text x="{w/2}" y="505" text-anchor="middle" font-family="Inter, sans-serif" font-size="26" font-weight="500" fill="{GREY}">An extra set of eyes for the pass.</text>'
    body += f'<rect x="0" y="{h-14}" width="{w}" height="14" fill="{FOREST}"/>'
    return svg(w, h, body)

fav = icon(CARD, FOREST, size=64, radius=0.24, w=1.3)
files = {
  "fullfill-wordmark-light.svg": wordmark(INK, OLIVE),
  "fullfill-wordmark-dark.svg": wordmark(DARK_INK, SAGE),
  "fullfill-wordmark-mono-black.svg": wordmark(INK, INK),
  "fullfill-wordmark-mono-white.svg": wordmark("#ffffff", "#ffffff"),
  "fullfill-icon-light.svg": icon(CARD, FOREST),
  "fullfill-icon-dark.svg": icon(SAGE, DARK_BG),
  "fullfill-icon-wordmark.svg": icon_word(PAPER, SAGE, FOREST),
  "favicon.svg": fav,
  "og-image.svg": og(),
}
for n, s in files.items():
    open(f"{OUT}/svg/{n}", "w").write(s)

def png(s, name, w, h=None):
    cairosvg.svg2png(bytestring=s.encode(), write_to=f"{OUT}/png/{name}", output_width=w, output_height=h)
for sz in (16, 32, 48):
    png(fav, f"favicon-{sz}.png", sz, sz)
png(icon(CARD, FOREST, size=180, radius=0), "apple-touch-icon.png", 180, 180)  # iOS rounds the corners
for sz in (192, 512):
    png(icon(CARD, FOREST), f"icon-{sz}.png", sz, sz)
png(icon(CARD, FOREST, radius=0, k=0.78), "icon-maskable-512.png", 512, 512)
png(icon(SAGE, DARK_BG), "icon-dark-512.png", 512, 512)
png(icon_word(PAPER, SAGE, FOREST, size=1024), "app-icon-wordmark-1024.png", 1024, 1024)
png(og(), "og-image-1200x630.png", 1200, 630)
for n in ("light", "dark", "mono-black", "mono-white"):
    png(files[f"fullfill-wordmark-{n}.svg"], f"fullfill-wordmark-{n}-1200w.png", 1200)
