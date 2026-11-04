#!/usr/bin/env python3
"""Pre-publication static check for any HTML page or article.

Catches the mechanical failures that are invisible on a desktop dev machine and
obvious on a phone. Written after a published brief shipped without a viewport
meta tag: every mobile media query silently never fired, and iOS rendered the
whole page at ~40% scale. The bug survived a "mobile check" because that check
wrote the page into an iframe sized to 375px, which forces the very viewport the
page was missing.

    python C:/dev/scripts/check_page.py path/to/page.html          # a hosted web page
    python C:/dev/scripts/check_page.py --artifact path/to/page.html
    python C:/dev/scripts/check_page.py --selftest                 # verify the checks

Exit code 0 = clean, 1 = at least one FAIL. WARN does not fail the run.

The type floor is checked in three places, because a page can pass one and fail
the phone: CSS `font-size:` declarations in px, rem and em (check 3), chart-library
font configs and SVG `font-size` attributes (3b), and sub/sup inheriting the UA
default (3c). 3b and 3c were added 2026-08-13 after this script certified a
dashboard "no declared font-size below 11.0px" while it rendered 9px Plotly tick
labels and 10px subscripts. rem and em resolution was added 2026-09-13 after the
same certification went to a page whose `.66rem` labels rendered at 10.56px, and
check 3 became a FAIL the same day; 3b and 3c remain WARN.

Pass --artifact for anything published through the Claude Artifact tool: a strict CSP
blocks every external host there, so a CDN font or stylesheet is a hard failure. For a
GitHub Pages dashboard the same link is correct and mandated by C:/dev/design.md, so it
is only reported as a note.

This is the static half. It cannot tell you whether the page *reads* well —
line length at each breakpoint, whether a chart is legible, whether a table
scrolls inside itself. For that, serve the file and drive a real viewport
(preview_start -> resize_window -> measure). See MOBILE_CHECK.md.
"""
import re
import sys
import html.parser

# Void / self-closing elements, including the SVG shapes that appear inline.
VOID = {"br", "hr", "img", "input", "meta", "link", "source", "col", "area", "base",
        "embed", "param", "track", "wbr",
        "path", "line", "rect", "circle", "ellipse", "polygon", "polyline",
        "use", "stop", "marker", "image"}

# iOS legibility floor. Below this, uppercase labels and captions turn to mush.
MIN_FONT_PX = 11.0

# UA default root font-size. rem and em declarations are resolved against the
# page's declared html / :root size when it has one, and against this otherwise.
ROOT_DEFAULT_PX = 16.0


class Balance(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append((tag, self.getpos()))

    def handle_startendtag(self, tag, attrs):
        pass  # explicitly self-closed, always fine

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append(f"stray </{tag}> at {self.getpos()}")
            return
        if self.stack[-1][0] != tag:
            self.errors.append(
                f"mismatched </{tag}> at {self.getpos()}: "
                f"innermost open is <{self.stack[-1][0]}> from {self.stack[-1][1]}")
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    return
        else:
            self.stack.pop()


def root_font_px(src):
    """Root font-size, in px, for resolving rem and em in check 3.

    Reads every rule in the page's <style> blocks whose selector is `html` or
    `:root` -- bare, or carrying a class, attribute or pseudo-class, so
    `html.dark` and `:root:not([data-theme="light"])` count while `html body`
    does not -- and takes the smallest px or % value declared on it. Smallest,
    because the phone is the viewport that matters and a narrow-screen
    media-query override is the one that applies there. Anything else (an em
    or clamp() root, a custom property, an external stylesheet, a style
    attribute on <html>) cannot be resolved statically and falls through to
    the UA default. Returns (px, declared).
    """
    found = []
    for css in re.findall(r'<style\b[^>]*>(.*?)</style>', src, re.S | re.I):
        css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
        for chunk in css.split("}"):
            head, brace, body = chunk.rpartition("{")
            if not brace or "font-size" not in body:
                continue
            # Inside an @media block the rule's own selector sits after the last `{`.
            selectors = head.rpartition("{")[2]
            if not any(re.fullmatch(r'(?:html|:root)(?![\w-])[^\s>+~]*', s.strip())
                       for s in selectors.split(",")):
                continue
            # The lookbehind stops a `--font-size` custom property posing as the root.
            for v, unit in re.findall(r'(?<![\w-])font-size\s*:\s*([0-9.]+)(px|%)', body):
                px = float(v) if unit == "px" else ROOT_DEFAULT_PX * float(v) / 100
                if px > 0:
                    found.append(px)
    return (min(found), True) if found else (ROOT_DEFAULT_PX, False)


def check(path, artifact=False):
    src = open(path, encoding="utf-8").read()
    fails, warns, oks = [], [], []

    def fail(m): fails.append(m)
    def warn(m): warns.append(m)
    def ok(m): oks.append(m)

    # 1. Viewport meta. The one that actually bit.
    vp = re.search(r'<meta[^>]+name=["\']viewport["\'][^>]*>', src, re.I)
    if not vp:
        fail("No <meta name=\"viewport\"> — mobile browsers will use a ~980px layout "
             "viewport, every max-width media query will fail to fire, and iOS will "
             "shrink the page to roughly 40%. Add: "
             "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">")
    elif "width=device-width" not in vp.group(0):
        fail(f"Viewport meta lacks width=device-width: {vp.group(0)}")
    else:
        ok("viewport meta present with width=device-width")
        if re.search(r'user-scalable\s*=\s*no|maximum-scale\s*=\s*1', vp.group(0), re.I):
            fail("Viewport blocks zoom (user-scalable=no / maximum-scale=1). "
                 "Breaks pinch-zoom accessibility on iOS.")

    # 2. iOS landscape text inflation.
    if not re.search(r'text-size-adjust\s*:\s*100%', src, re.I):
        warn("No -webkit-text-size-adjust:100% — iOS Safari may inflate body text "
             "when the phone is rotated to landscape.")
    else:
        ok("text-size-adjust pinned to 100%")

    # 3. Font sizes below the legibility floor.
    #
    # px is read as declared. rem and em are resolved at the page's root
    # font-size (root_font_px above): on 2026-09-12 the px-only regex certified
    # "no declared font-size below 11.0px" on a page whose
    # `.tool-paths dt { font-size: .66rem }` labels rendered at 10.56px in an
    # emulated 390px viewport. em strictly resolves against the parent, which a
    # static read cannot know, so it is taken at the root as well; a parent
    # below the root makes the true size smaller still, never larger.
    root_px, root_declared = root_font_px(src)
    small = sorted({float(m) for m in re.findall(r'font-size:\s*([0-9.]+)px', src)
                    if float(m) < MIN_FONT_PX})
    small_rel = set()
    for v, unit in re.findall(r'font-size:\s*([0-9.]+)(r?em)\b', src):
        # Rounded so that 1.1rem at a 10px root compares as 11, not 10.999...
        px = round(float(v) * root_px, 4)
        if px < MIN_FONT_PX:
            small_rel.add((px, float(v), unit))
    root_note = f"the {'declared' if root_declared else 'default'} {root_px:g}px root"
    if small or small_rel:
        found = [str(s) + 'px' for s in small] + [
            f"{v:g}{unit} ({px:g}px)" for px, v, unit in sorted(small_rel)]
        basis = (f" rem and em resolved at {root_note}, em as if its parent sat at "
                 f"the root." if small_rel else "")
        # A FAIL since 2026-09-13 (owner decision); 3b and 3c below still WARN.
        # The regex reads declarations without context, so a size that only
        # applies above a desktop breakpoint or inside a scrolling SVG fails
        # here as well. That is stated rather than guessed around.
        fail(f"Font sizes below {MIN_FONT_PX}px found: {', '.join(found)}.{basis} "
             f"Every declaration counts, whatever its media query or container; "
             f"raise each to the floor.")
    else:
        ok(f"no declared font-size below {MIN_FONT_PX}px "
           f"(rem and em resolved at {root_note})")

    # 3b. The same floor in the two places a `font-size:` regex cannot see.
    #
    # Check 3 reads CSS declarations only. On 2026-08-13 it therefore reported
    # "no declared font-size below 11.0px", 0 fail, on a page carrying 9px
    # Plotly tickfont/textfont and a 10px legend font — a guard certifying
    # clean on the exact defect it exists to catch. Sub-11px type was the one
    # defect the cross-dashboard audit that day found on ALL FIVE live pages,
    # so this half matters as much as the CSS half.
    #
    # Two forms, both invisible above:
    #   chart config   font: { size: 9 }   tickfont: { size: 10 }
    #   SVG attribute  <text font-size="9">
    chart_small, svg_small = set(), set()
    for m in re.finditer(
            r'["\']?(font|tickfont|textfont|titlefont|insidetextfont|outsidetextfont)'
            r'["\']?\s*:\s*\{[^}]*?["\']?size["\']?\s*:\s*([0-9.]+)', src):
        if float(m.group(2)) < MIN_FONT_PX:
            chart_small.add((m.group(1), float(m.group(2))))
    # Attribute form. A templated value (font-size="${upx(12)}") is not a
    # literal and is skipped rather than guessed at.
    for m in re.finditer(r'font-size\s*=\s*["\']?([0-9.]+)["\']?', src):
        if float(m.group(1)) < MIN_FONT_PX:
            svg_small.add(float(m.group(1)))
    if chart_small or svg_small:
        bits = []
        if chart_small:
            bits.append("chart config " + ", ".join(
                f"{k}:{v:g}" for k, v in sorted(chart_small, key=lambda t: (t[1], t[0]))))
        if svg_small:
            bits.append("SVG font-size attribute " + ", ".join(
                f"{v:g}" for v in sorted(svg_small)))
        warn(f"Chart / SVG label sizes below {MIN_FONT_PX}px: {'; '.join(bits)}. "
             f"These do not appear as `font-size:` declarations, so check 3 above "
             f"cannot see them. Plotly renders them at the declared size — a 9px "
             f"tick label is 9px on the phone, not 9px scaled up.")
    else:
        ok(f"no chart / SVG label size below {MIN_FONT_PX}px")

    # 3c. sub/sup inherit the UA default (~0.83em) and drop under the floor on
    # any parent at 13px or below, while every declared size stays compliant.
    if re.search(r'<su[bp][\s>]', src, re.I):
        floored = re.search(r'(?<![.#\w-])(?:sub|sup)\b[^{}]{0,120}\{[^}]*font-size',
                            src, re.I)
        if floored:
            ok("sub/sup carry an explicit font-size floor")
        else:
            warn(f"<sub>/<sup> present with no explicit font-size rule. The UA "
                 f"default is `smaller` (~0.83em), so they compute under "
                 f"{MIN_FONT_PX}px on any parent at 13px or below — with every "
                 f"declared size still passing check 3. Add e.g. "
                 f"`sub, sup {{ font-size: max({MIN_FONT_PX:g}px, 0.85em); }}`")

    # 4. Wide fixed content must scroll inside its own container, not the body.
    minw = re.findall(r'min-width:\s*(\d+)px', src)
    wide = [w for w in minw if int(w) > 380]
    if wide:
        if re.search(r'overflow-x:\s*auto', src, re.I):
            ok(f"wide min-width ({', '.join(w + 'px' for w in wide)}) paired with an "
               f"overflow-x:auto container")
        else:
            fail(f"min-width up to {max(wide)}px with no overflow-x:auto container — "
                 f"the page body will scroll sideways on a phone.")

    # 5. A responsive page needs at least one breakpoint.
    mq = re.findall(r'@media[^{]*max-width:\s*(\d+)px', src)
    if not mq:
        warn("No max-width media query — confirm the layout is fluid by construction.")
    else:
        ok(f"{len(mq)} mobile breakpoint(s): {', '.join(sorted(set(mq))) } px")

    # 6. Both colour schemes.
    # A page may instead declare itself light-only (design.md: light by default,
    # dark only when requested). The meta must say exactly "light" -- "light dark"
    # opts in to both schemes and still needs the handling above. Added 2026-10-11.
    has_dark = re.search(r'prefers-color-scheme:\s*dark', src, re.I)
    has_toggle = re.search(r'data-theme=["\']?dark', src, re.I)
    light_only = re.search(
        r'<meta\b(?=[^>]*\bname=["\']color-scheme["\'])(?=[^>]*\bcontent=["\']\s*(?:only\s+)?light\s*["\'])[^>]*>',
        src, re.I)
    if light_only and not has_dark:
        ok("light-only by declaration (<meta name=\"color-scheme\" content=\"light\">)")
    elif has_dark and has_toggle:
        ok("dark theme via prefers-color-scheme and an explicit data-theme override")
    elif has_dark:
        warn("prefers-color-scheme:dark present but no [data-theme] override — a host "
             "theme toggle will not be able to force light/dark.")
    else:
        warn("No dark-theme handling found.")

    # 7. External references — blocked by the artifact CSP, and they break offline.
    ext = re.findall(r'(?:src|href)\s*=\s*["\'](https?://[^"\']+)', src)
    assets = [u for u in ext if re.search(r'\.(css|js|woff2?|ttf|otf|png|jpe?g|svg|gif|webp)(\?|$)', u, re.I)
              or "fonts.googleapis" in u or "cdn" in u.lower()]
    if assets:
        if artifact:
            fail("External asset references will be blocked by the artifact CSP and will "
                 "fail offline: " + ", ".join(assets[:4]))
        else:
            ok(f"{len(assets)} external asset reference(s) — fine for a hosted page "
               f"(design.md mandates the font link); would FAIL as an artifact")
    else:
        ok(f"self-contained ({len(ext)} outbound links, no external assets)")

    # 8. Tag balance.
    b = Balance()
    b.feed(src)
    if b.errors or b.stack:
        for e in b.errors[:5]:
            fail("markup: " + e)
        for tag, pos in b.stack[:5]:
            fail(f"markup: <{tag}> opened at line {pos[0]} never closed")
    else:
        ok("tag balance clean")

    # 9. Title.
    if not re.search(r'<title>\s*\S', src, re.I):
        warn("No <title> — the artifact will fall back to the filename.")
    else:
        ok("title present")

    return fails, warns, oks


_SELFTEST_CASES = [
    # (name, html, substring the check must report as FAIL or WARN, or None
    #  if it must report no type finding at all)
    ("plotly tickfont 9",
     '<style>p{font-size:14px}</style><script>x={tickfont:{size:9}}</script>',
     "Chart / SVG label"),
    ("plotly legend font 10, size not first",
     '<script>x={legend:{font:{color:"red",size:10}}}</script>',
     "Chart / SVG label"),
    ("plotly quoted JSON form",
     '<script>x={"textfont":{"size":9}}</script>',
     "Chart / SVG label"),
    ("plotly sizes all >= floor",
     '<script>x={tickfont:{size:11},font:{size:12}}</script>',
     None),
    # `size:` belonging to something that is not a font must not trip it.
    ("non-font size key ignored",
     '<script>const order={entry:0,resize:1};const m={marker:{size:4}}</script>',
     None),
    ("svg font-size attribute 9",
     '<svg><text font-size="9">x</text></svg>',
     "Chart / SVG label"),
    ("svg templated size is skipped, not guessed",
     '<svg><text font-size="${upx(12)}">x</text></svg>',
     None),
    ("sub with no floor rule",
     '<style>p{font-size:13px}</style><p>w<sub>i</sub></p>',
     "sub>/<sup> present"),
    ("sub with an explicit floor rule",
     '<style>sub, sup { font-size: max(11px, 0.85em); }</style><p>w<sub>i</sub></p>',
     None),
    # A `.sub` class must not be mistaken for a floor on the sub element.
    ("class .sub does not satisfy the sub floor",
     '<style>table .sub { font-size: 11px; }</style><p>w<sub>i</sub></p>',
     "sub>/<sup> present"),
    ("no sub/sup on the page at all",
     '<p>plain</p>',
     None),
    # Check 3 read px only until 2026-09-13. A page declaring
    # `.tool-paths dt { font-size: .66rem }` (10.56px at the 16px root) was
    # certified "no declared font-size below 11.0px" on 2026-09-12 while the
    # labels rendered at 10.56px in an emulated 390px viewport.
    ("rem below the floor at the default root",
     '<style>.tool-paths dt { font-size: .66rem }</style>',
     "0.66rem (10.56px)"),
    ("rem above the floor at the default root",
     '<style>.tool-paths dt { font-size: .7rem }</style>',
     None),
    ("px and rem hits share one line, px first",
     '<style>.a { font-size: 10px } .b { font-size: .66rem }</style>',
     "10.0px, 0.66rem (10.56px)"),
    ("em resolved at the root",
     '<style>.b { font-size: .6em }</style>',
     "0.6em (9.6px)"),
    ("declared 62.5% root makes 1rem 10px",
     '<style>html { font-size: 62.5% } p { font-size: 1rem }</style>',
     "1rem (10px)"),
    ("declared 62.5% root makes 1.1rem 11px",
     '<style>html { font-size: 62.5% } p { font-size: 1.1rem }</style>',
     None),
    ("smallest declared root wins",
     '<style>html { font-size: 16px } @media (max-width: 600px) { html { font-size: 14px } }'
     ' p { font-size: .75rem }</style>',
     "0.75rem (10.5px)"),
    # `html body` is a body rule and `--font-size` is a custom property; taking
    # either as the root would turn 1rem into 10px and raise a false warning.
    ("html descendant rule is not the root",
     '<style>html body { font-size: 62.5% } p { font-size: 1rem }</style>',
     None),
    ("custom property on :root is not the root",
     '<style>:root { --font-size: 62.5% } p { font-size: 1rem }</style>',
     None),
]


def selftest():
    import tempfile
    import os
    failures = []
    for name, body, expect in _SELFTEST_CASES:
        page = ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                '<title>t</title></head><body>' + body + '</body></html>')
        fd, p = tempfile.mkstemp(suffix=".html")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(page)
            fails, warns, _ = check(p)
        finally:
            os.unlink(p)
        # Check 3 reports as FAIL, 3b and 3c as WARN; a case asserts on either,
        # and the split itself is pinned so a regression to WARN fails here.
        found = fails + warns
        blob = " || ".join(found)
        misfiled = ([m for m in warns if "Font sizes below" in m]
                    + [m for m in fails
                       if "Chart / SVG label" in m or "sub>/<sup> present" in m])
        if misfiled:
            failures.append(f"{name}: wrong severity: {misfiled[0][:70]}")
        if expect is None:
            hit = [m for m in found
                   if "Font sizes below" in m or "Chart / SVG label" in m
                   or "sub>/<sup> present" in m]
            if hit:
                failures.append(f"{name}: expected no type finding, got: {hit[0][:70]}")
        elif expect not in blob:
            failures.append(f"{name}: expected a finding containing {expect!r}, "
                            f"got: {blob[:70] or '(none)'}")
    # Colour-scheme cases (check 6): (name, <head> extra, must the warning fire?)
    scheme_cases = [
        ("no scheme handling warns", '', True),
        ("meta content=light is a declared light-only page",
         '<meta name="color-scheme" content="light">', False),
        ("meta content='only light', attributes reversed",
         "<meta content='only light' name='color-scheme'>", False),
        ("meta content='light dark' still needs dark handling",
         '<meta name="color-scheme" content="light dark">', True),
        ("theme-color meta is not a scheme declaration",
         '<meta name="theme-color" content="light">', True),
    ]
    for name, head, must_warn in scheme_cases:
        page = ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                + head + '<title>t</title></head><body><p>x</p></body></html>')
        fd, p = tempfile.mkstemp(suffix=".html")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(page)
            _, warns, _ = check(p)
        finally:
            os.unlink(p)
        warned = any("dark-theme" in w or "prefers-color-scheme" in w for w in warns)
        if warned != must_warn:
            failures.append(f"{name}: scheme warning {'missing' if must_warn else 'raised'}")
    total = len(_SELFTEST_CASES) + len(scheme_cases)
    for f in failures:
        print(f"  FAIL  selftest {f}")
    print(f"  --> selftest: {total - len(failures)}/{total} cases pass")
    return 1 if failures else 0


def main():
    if "--selftest" in sys.argv[1:]:
        return selftest()
    args = [a for a in sys.argv[1:] if a != "--artifact"]
    artifact = "--artifact" in sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    rc = 0
    for path in args:
        fails, warns, oks = check(path, artifact=artifact)
        print(f"\n=== {path} ===")
        for m in oks:
            print(f"  ok    {m}")
        for m in warns:
            print(f"  WARN  {m}")
        for m in fails:
            print(f"  FAIL  {m}")
        print(f"  --> {len(fails)} fail, {len(warns)} warn, {len(oks)} ok")
        if fails:
            rc = 1
    if rc == 0:
        print("\nStatic checks passed. This does NOT cover whether the page READS well "
              "-- serve it and measure a real viewport (see MOBILE_CHECK.md).")
    return rc


if __name__ == "__main__":
    sys.exit(main())
