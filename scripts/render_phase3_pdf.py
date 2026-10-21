"""Render reports/phase3 to PDF: with --browse (the Chromium tool used for Phase 2.5) or, without it, via matplotlib.

    .venv/bin/python scripts/render_phase3_pdf.py                      # matplotlib text rendering, no browser needed
    .venv/bin/python scripts/render_phase3_pdf.py --browse <gstack browse>  # same HTML/CSS path as Phase 2.5
"""
import argparse
import json
import re
import subprocess
import textwrap
from pathlib import Path

ROOT = Path("reports/phase3")
OUTPUT = ROOT / "Agenthon_Track2_Phase3_Text_Layer_Results.pdf"


def via_browser(pages, browse):
    import markdown
    sections = ["<section class=\"page\">" + markdown.markdown(p, extensions=["tables", "fenced_code"]) + "</section>" for p in pages]
    css = Path("scripts/render_phase2_5_pdf.py").read_text().split("css = '''")[1].split("'''")[0]
    html = Path(".context/phase3/report.html").resolve()
    html.parent.mkdir(parents=True, exist_ok=True)
    html.write_text("<!doctype html><html><head><meta charset=\"utf-8\"><title>Agenthon Track 2 — Phase 3 text layer</title><style>"
                    + css + "</style></head><body>" + "".join(sections) + "</body></html>")
    subprocess.run([str(browse), "goto", html.as_uri()], check=True)
    subprocess.run([str(browse), "pdf", str(OUTPUT.resolve()), "--format", "letter", "--margins", "1in", "--page-numbers",
                    "--print-background", "--tagged", "--outline", "--prefer-css-page-size"], check=True)


def via_matplotlib(pages):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    def lines_for(page):
        out, para, table = [], [], []

        def flush_para():
            if para:
                for w in textwrap.wrap(" ".join(para), 104):
                    out.append(("p", w))
                out.append(("p", ""))
                para.clear()

        def flush_table():
            if table:
                widths = [min(44, max(len(r[i]) if i < len(r) else 0 for r in table)) for i in range(max(map(len, table)))]
                for r in table:
                    out.append(("mono", "  ".join((r[i] if i < len(r) else "")[:widths[i]].ljust(widths[i]) for i in range(len(widths)))))
                out.append(("p", ""))
                table.clear()

        for raw in page.splitlines():
            if raw.startswith("# "):
                flush_para(); flush_table(); out.append(("h1", raw[2:]))
            elif raw.startswith("## "):
                flush_para(); flush_table(); out.append(("h2", raw[3:]))
            elif raw.startswith("|"):
                flush_para()
                cells = [c.strip().replace("**", "") for c in raw.strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    table.append(cells)
            elif raw.startswith("```"):
                continue
            elif not raw.strip():
                flush_para(); flush_table()
            else:
                flush_table()
                para.append(raw.strip().replace("**", "").replace("`", ""))
        flush_para(); flush_table()
        return out

    with PdfPages(OUTPUT) as pdf:
        for number, page in enumerate(pages, 1):
            items = lines_for(page)
            while items:
                fig = plt.figure(figsize=(8.5, 11))
                y = 0.95
                while items and y > 0.06:
                    kind, text = items.pop(0)
                    size = {"h1": 15, "h2": 11.5, "mono": 6.8, "p": 9}[kind]
                    family = "monospace" if kind == "mono" else "sans-serif"
                    weight = "bold" if kind in ("h1", "h2") else "normal"
                    if kind == "h2":
                        y -= 0.012
                    fig.text(0.08, y, text, fontsize=size, family=family, weight=weight, va="top")
                    y -= {"h1": 0.034, "h2": 0.024, "mono": 0.0145, "p": 0.0175 if text else 0.008}[kind]
                fig.text(0.5, 0.03, f"Agenthon Track 2 — Phase 3/4 text layer — chapter {number}", fontsize=7, ha="center", color="#555555")
                pdf.savefig(fig)
                plt.close(fig)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--browse", type=Path)
    args = ap.parse_args()
    pages = json.loads((ROOT / "pdf-pages.json").read_text())
    assert len(pages) == 5
    (via_browser if args.browse else via_matplotlib)(pages, args.browse) if args.browse else via_matplotlib(pages)
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")
