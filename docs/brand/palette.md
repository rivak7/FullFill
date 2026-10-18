# FullFill palette

Pulled from the POS/KDS site styles in `apps/web/src/app.css`, plus two olive tones for the logo.

| Role | Name | Hex | Where it comes from |
|---|---|---|---|
| Primary | Forest | `#173e32` | `--forest` on the sites (buttons, selected tabs). Icon background. |
| Logo accent | Olive | `#5c6b3a` | New. The u/i face letter in the wordmark on light backgrounds. |
| Logo accent (dark) | Sage | `#a9b585` | New. The face letter and icon face on dark backgrounds. |
| Text | Ink | `#202a23` | Body text on the sites. The f and l letters of the wordmark. |
| Secondary text | Grey | `#74776c` | `--muted` on the sites. |
| Background | Paper | `#f4f3ee` | Page background on the sites. |
| Surface | Card | `#fffef9` | Header and card backgrounds. Icon face on forest. |
| Border | Line | `#dedfd5` | Dividers and card borders. |
| Dark background | Night | `#141813` | New. Dark-mode backdrop for logo and icon. |
| Attention | Amber | `#b48337` | Pending/loading dot on the sites; pairs with the station screen's amber state. |

## Regenerating

`python3 docs/brand/generate.py docs/brand` rebuilds every SVG and PNG here (needs `pip install cairosvg`). The web app's copies live in `apps/web/public/`.

## Using the files on the web app

Copy `svg/favicon.svg`, `png/favicon.ico`, `png/apple-touch-icon.png`, `png/icon-192.png`, `png/icon-512.png`, `png/icon-maskable-512.png` and `png/og-image-1200x630.png` into `apps/web/public/`, then add to `apps/web/index.html`:

```html
<link rel="icon" href="/favicon.ico" sizes="any" />
<link rel="icon" href="/favicon.svg" type="image/svg+xml" />
<link rel="apple-touch-icon" href="/apple-touch-icon.png" />
<link rel="manifest" href="/manifest.webmanifest" />
<meta name="theme-color" content="#173e32" />
<meta property="og:image" content="/og-image-1200x630.png" />
```

`manifest.webmanifest` is in this folder too.
