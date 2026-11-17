#!/usr/bin/env python3
"""TEXT-CONTRAST-AA helper (plan docs/superpowers/plans/2026-11-17-text-contrast-aa-plan.md).

  python scripts/text_contrast.py measure   # WCAG 2.x contrast of every text token vs --bg-base / --bg-surface
  python scripts/text_contrast.py usages    # every var(--T)/token('--T') use of the colour tokens, classified

Read-only. Exit 1 from `measure` if any text token is below 4.5:1 in either theme.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")
TOKENS = os.path.join(FRONTEND, "styles", "tokens.css")

# Tokens whose value is used as text colour on --bg-base / --bg-surface.
TEXT_TOKENS = [
    "--text-primary", "--text-secondary", "--text-dim",
    "--text-pass", "--text-caution", "--text-reject", "--text-accent", "--text-neutral",
]
# Tokens whose text usages the plan inventories (base status/accent tokens stay for fills).
USAGE_TOKENS = ["text-secondary", "text-dim", "pass", "caution", "reject", "accent", "neutral"]
SKIP_DIRS = {"node_modules", ".next", "coverage", "__tests__", "__mocks__"}


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_):
    h = hex_.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def theme_blocks(css):
    out = {}
    for name in ("dark", "light"):
        m = re.search(r'\[data-theme="%s"\]\s*\{(.*?)\}' % name, css, re.S)
        out[name] = dict(re.findall(r"(--[\w-]+):\s*(#[0-9A-Fa-f]{6})\b", m.group(1)))
    return out


def measure():
    css = open(TOKENS, encoding="utf-8").read()
    failed = False
    for theme, v in theme_blocks(css).items():
        print(f"== {theme}  --bg-base {v['--bg-base']}  --bg-surface {v['--bg-surface']}")
        print(f"{'token':16} {'value':8} {'base':>6} {'surface':>8}")
        for t in TEXT_TOKENS + ["--pass", "--caution", "--reject", "--accent", "--neutral"]:
            if t not in v:
                print(f"{t:16} (not defined)")
                continue
            a, s = contrast(v[t], v["--bg-base"]), contrast(v[t], v["--bg-surface"])
            ok = min(a, s) >= 4.5
            role = "text" if t in TEXT_TOKENS else "fill/border (info)"
            if t in TEXT_TOKENS and not ok:
                failed = True
            print(f"{t:16} {v[t]:8} {a:6.2f} {s:8.2f}  {'PASS' if ok else 'FAIL'}  {role}")
    return 1 if failed else 0


TEXT_PROPS = {"color"}
TSX_TEXT_KEYS = {"color", "textColor"}


def classify_css(prop):
    prop = prop.strip().lower()
    if prop in TEXT_PROPS:
        return "TEXT"
    return "NON-TEXT"


def usages():
    pat = re.compile(r"var\(--(%s)\)|token\(\s*['\"]--(%s)['\"]\s*\)" % ("|".join(USAGE_TOKENS), "|".join(USAGE_TOKENS)))
    rows = []
    for dp, dns, fns in os.walk(FRONTEND):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            if not fn.endswith((".css", ".tsx", ".ts")) or fn.endswith(".d.ts"):
                continue
            path = os.path.join(dp, fn)
            rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
            if rel == "frontend/styles/tokens.css":
                continue
            for i, line in enumerate(open(path, encoding="utf-8"), 1):
                if line.lstrip().startswith(("*", "//", "/*")):
                    continue
                for m in pat.finditer(line):
                    tok = m.group(1) or m.group(2)
                    pre = line[: m.start()]
                    if fn.endswith(".css"):
                        # property = last "prop:" before the match within this declaration
                        decl = pre.split(";")[-1].split("{")[-1]
                        pm = re.search(r"([-\w]+)\s*:[^:]*$", decl)
                        prop = pm.group(1) if pm else "?"
                        kind = classify_css(prop) if pm else "MANUAL"
                        if kind == "TEXT" and "color-mix" in decl:
                            kind = "MANUAL"  # mixed text colour: decide by hand
                    else:
                        km = re.search(r"([A-Za-z]+)\s*[:=]\s*[^:=,{]*$", pre)
                        prop = km.group(1) if km else "?"
                        if prop in TSX_TEXT_KEYS:
                            kind = "TEXT"
                        elif km and re.match(r"(background|border|fill|stroke|outline|line|up|down|wick|top|bottom|area|base)", prop, re.I):
                            kind = "NON-TEXT"
                        elif prop == "color" or not km:
                            kind = "MANUAL"
                        else:
                            kind = "MANUAL"
                    rows.append((tok, kind, prop, rel, i, line.strip()[:110]))
    rows.sort(key=lambda r: (r[0], r[1], r[3], r[4]))
    from collections import Counter
    c = Counter((r[0], r[1]) for r in rows)
    print("token            TEXT  NON-TEXT  MANUAL")
    for t in USAGE_TOKENS:
        print(f"--{t:15} {c[(t,'TEXT')]:4}  {c[(t,'NON-TEXT')]:8}  {c[(t,'MANUAL')]:6}")
    print()
    for r in rows:
        print(f"--{r[0]:15} {r[1]:8} {r[2]:22} {r[3]}:{r[4]}  | {r[5]}")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "measure"
    sys.exit(measure() if cmd == "measure" else usages())
