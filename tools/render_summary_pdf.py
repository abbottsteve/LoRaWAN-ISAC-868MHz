#!/usr/bin/env python3
"""
Deterministic WeasyPrint PDF Renderer for `ISAC_868MHz_System_Design_and_Operation_Summary.md`
==============================================================================================
Converts `docs/ISAC_868MHz_System_Design_and_Operation_Summary.md` into a publication-grade
A4 engineering datasheet PDF (`docs/ISAC_868MHz_System_Design_and_Operation_Summary.pdf`)
via `weasyprint`, rendering Mermaid diagrams and LaTeX math into clean typographic HTML/CSS.
"""

import html
import os
import re
import sys

import markdown
import weasyprint

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS_DIR = os.path.join(ROOT, "docs")

MD_PATH = os.path.join(DOCS_DIR, "ISAC_868MHz_System_Design_and_Operation_Summary.md")
PDF_PATH = os.path.join(DOCS_DIR, "ISAC_868MHz_System_Design_and_Operation_Summary.pdf")


def _render_mermaid_block(code_str):
    lines = [ln.strip() for ln in code_str.strip().splitlines() if ln.strip()]
    if not lines:
        return ""

    if lines[0].startswith("flowchart"):
        # Parse node labels ID["Label"] in appearance order
        nodes = []
        seen = set()
        for m in re.finditer(r'([A-Z0-9_]+)\["([^"]+)"\]', code_str):
            nid, lbl = m.group(1), m.group(2)
            if nid not in seen:
                seen.add(nid)
                parts = [html.escape(p) for p in lbl.split("\\n")]
                title = f"<strong>{parts[0]}</strong>"
                sub = "<br/>".join(parts[1:])
                body = f"{title}<br/><span>{sub}</span>" if sub else title
                nodes.append(f'<div class="flow-step">{body}</div>')
        inner = '<div class="flow-arrow">&rarr;</div>'.join(nodes)
        return f'<div class="diagram-box"><div class="flow-row">{inner}</div></div>'

    if lines[0].startswith("sequenceDiagram"):
        participants = {}
        events = []
        for ln in lines[1:]:
            mp = re.match(r"participant\s+([A-Za-z0-9_]+)\s+as\s+(.+)$", ln)
            if mp:
                participants[mp.group(1)] = mp.group(2).strip()
                continue
            me = re.match(r"([A-Za-z0-9_]+)\s*(->>|-->>)\s*([A-Za-z0-9_]+)\s*:\s*(.+)$", ln)
            if me:
                src, arrow, dst, msg = me.groups()
                s_lbl = html.escape(participants.get(src, src))
                d_lbl = html.escape(participants.get(dst, dst))
                sym = "&rArr;" if arrow == "-->>" else "&rarr;"
                events.append(
                    f"<tr>"
                    f"<td class='seq-actor'>{s_lbl} {sym} {d_lbl}</td>"
                    f"<td class='seq-msg'>{html.escape(msg.strip())}</td>"
                    f"</tr>"
                )
        rows_html = "\n".join(events)
        return (
            f'<div class="diagram-box">'
            f'<table class="seq-table"><tbody>{rows_html}</tbody></table>'
            f"</div>"
        )

    return f"<pre>{html.escape(code_str)}</pre>"


def _latex_to_html(expr, display=False):
    s = expr.strip()
    # Known exact display equations for crisp fraction layout
    if "V_{\\text{DDA,true}}" in s:
        inner = (
            "<i>V</i><sub>DDA,true</sub> = 3000&nbsp;mV &times; "
            "<span class='frac'><span class='num'>16 &times; VREFINT_CAL</span>"
            "<span class='den'>ADC16<sub>VREFINT</sub></span></span>"
        )
        return f'<div class="math-display">{inner}</div>'
    if "\\Delta L_{13} =" in s and "\\frac{V(f_1)" in s:
        inner = (
            "&Delta;<i>L</i><sub>13</sub> = "
            "<span class='frac'><span class='num'><i>V</i>(<i>f</i><sub>1</sub>) &minus; <i>V</i>(<i>f</i><sub>3</sub>)</span>"
            "<span class='den'>19.0&nbsp;mV/dB</span></span>"
        )
        return f'<div class="math-display">{inner}</div>'
    if "\\Delta N_2 =" in s:
        inner = (
            "&Delta;<i>N</i><sub>2</sub> = "
            "<span class='frac'><span class='num'>&frac12;[<i>V</i>(<i>f</i><sub>1</sub>) + <i>V</i>(<i>f</i><sub>3</sub>)] &minus; <i>V</i>(<i>f</i><sub>2</sub>)</span>"
            "<span class='den'>19.0&nbsp;mV/dB</span></span>"
        )
        return f'<div class="math-display">{inner}</div>'
    if "\\bar{L} =" in s:
        inner = (
            "<span style='text-decoration:overline;'><i>L</i></span> = "
            "<span class='frac'><span class='num'><i>P</i><sub>refl</sub>(<i>f</i><sub>1</sub>) + "
            "<i>P</i><sub>refl</sub>(<i>f</i><sub>2</sub>) + <i>P</i><sub>refl</sub>(<i>f</i><sub>3</sub>)</span>"
            "<span class='den'>3</span></span>"
        )
        return f'<div class="math-display">{inner}</div>'

    # Inline math substitutions
    replacements = [
        (r"\\hat\{\\varepsilon\}_r'", "ε̂<sub>r</sub>&prime;"),
        (r"\\varepsilon_r\^\*", "ε<sub>r</sub><sup>*</sup>"),
        (r"\\varepsilon_r'", "ε<sub>r</sub>&prime;"),
        (r"\\varepsilon_r''", "ε<sub>r</sub>&Prime;"),
        (r"\\varepsilon_r", "ε<sub>r</sub>"),
        (r"\\Delta L_\{13\}", "&Delta;<i>L</i><sub>13</sub>"),
        (r"\\Delta N_2", "&Delta;<i>N</i><sub>2</sub>"),
        (r"\\bar\{L\}", "<span style='text-decoration:overline;'><i>L</i></span>"),
        (r"\\delta_E", "&delta;<sub>E</sub>"),
        (r"\\Gamma", "&Gamma;"),
        (r"\\pi", "&pi;"),
        (r"\\to", "&rarr;"),
        (r"\\approx", "&approx;"),
        (r"\\Omega", "&Omega;"),
        (r"\\cdot", "&middot;"),
        (r"\\frac\{1\}\{2\}", "&frac12;"),
        (r"\\text\{([^}]*)\}", r"\1"),
        (r"_\{([^}]*)\}", r"<sub>\1</sub>"),
        (r"_([A-Za-z0-9])", r"<sub>\1</sub>"),
        (r"\^\{([^}]*)\}", r"<sup>\1</sup>"),
    ]
    out = s
    for pat, rep in replacements:
        out = re.sub(pat, rep, out)
    out = out.replace("\\", "")
    if display:
        return f'<div class="math-display">{out}</div>'
    return f'<span class="math-inline">{out}</span>'


CSS_STYLES = """
@page {
    size: A4 portrait;
    margin: 18mm 14mm 18mm 14mm;
    @top-left {
        content: "868 MHz Dual-Function LoRaWAN ISAC Node (Rev E.5) • System Summary";
        font-family: "DejaVu Sans", "Liberation Sans", sans-serif;
        font-size: 7.5pt;
        color: #546e7a;
    }
    @bottom-right {
        content: "Hardware Revision E.5 | 0.80 mm Self-Draining UV-Stabilized ASA/PETG Window — Page " counter(page) " of " counter(pages);
        font-family: "DejaVu Sans", "Liberation Sans", sans-serif;
        font-size: 7.5pt;
        color: #546e7a;
    }
}
body {
    font-family: "DejaVu Sans", "Liberation Sans", Arial, sans-serif;
    font-size: 8.8pt;
    line-height: 1.42;
    color: #1c2833;
}
h1 {
    font-size: 15.5pt;
    color: #0d3b66;
    margin: 0 0 3pt 0;
    line-height: 1.2;
}
h2 {
    font-size: 11.2pt;
    color: #0d3b66;
    border-bottom: 1.2pt solid #1976d2;
    padding-bottom: 2.5pt;
    margin-top: 11pt;
    margin-bottom: 5pt;
}
h1 + h2 {
    font-size: 9.6pt;
    font-weight: 600;
    color: #455a64;
    border-bottom: none;
    margin-top: 0;
    margin-bottom: 6pt;
}
h3 {
    font-size: 9.6pt;
    color: #1b4f72;
    margin-top: 8pt;
    margin-bottom: 4pt;
}
hr {
    border: none;
    border-top: 0.75pt solid #cfd8dc;
    margin: 8pt 0;
}
p, li {
    margin-top: 3pt;
    margin-bottom: 3pt;
}
ul, ol {
    padding-left: 15pt;
    margin-top: 3pt;
    margin-bottom: 5pt;
}
code {
    font-family: "DejaVu Sans Mono", "Liberation Mono", monospace;
    font-size: 7.9pt;
    background-color: #f1f5f9;
    padding: 0.8pt 2.5pt;
    border-radius: 2pt;
    color: #0f172a;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin: 6pt 0 8pt 0;
    font-size: 7.9pt;
}
th {
    background-color: #0d3b66;
    color: #ffffff;
    font-weight: 700;
    text-align: left;
    padding: 4pt 5pt;
    border: 0.6pt solid #0d3b66;
}
td {
    padding: 3.5pt 5pt;
    border: 0.6pt solid #cbd5e1;
    vertical-align: top;
}
tr:nth-child(even) td {
    background-color: #f8fafc;
}
blockquote {
    margin: 6pt 0;
    padding: 5pt 8pt;
    background-color: #eef6ff;
    border-left: 3pt solid #1976d2;
    font-size: 8.3pt;
}
.diagram-box {
    margin: 6pt 0;
    padding: 6pt;
    background-color: #f8fafc;
    border: 0.75pt solid #cbd5e1;
    border-radius: 3pt;
    page-break-inside: avoid;
}
.flow-row {
    display: flex;
    flex-direction: row;
    align-items: stretch;
    justify-content: space-between;
    gap: 3pt;
}
.flow-step {
    flex: 1;
    background: #ffffff;
    border: 0.75pt solid #1976d2;
    border-radius: 3pt;
    padding: 3.5pt 4pt;
    font-size: 6.9pt;
    line-height: 1.25;
    text-align: center;
}
.flow-step span {
    color: #334155;
}
.flow-arrow {
    align-self: center;
    font-weight: bold;
    color: #1976d2;
    font-size: 9pt;
}
.seq-table {
    margin: 0;
    font-size: 7.6pt;
}
.seq-table td {
    padding: 2.5pt 5pt;
}
.seq-actor {
    width: 38%;
    font-weight: 700;
    color: #0d3b66;
    white-space: nowrap;
}
.math-display {
    text-align: center;
    margin: 5pt 0;
    padding: 3pt 0;
    font-size: 9.0pt;
}
.frac {
    display: inline-block;
    vertical-align: middle;
    text-align: center;
    margin: 0 2pt;
}
.frac > .num {
    display: block;
    border-bottom: 0.7pt solid #1c2833;
    padding: 0 3pt 1pt 3pt;
}
.frac > .den {
    display: block;
    padding: 1pt 3pt 0 3pt;
}
"""


def render_summary_pdf(md_path=MD_PATH, pdf_path=PDF_PATH):
    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    # 1. Replace ```mermaid ... ``` blocks with styled HTML diagrams
    md_text = re.sub(
        r"```mermaid\s*\n(.*?)```",
        lambda m: _render_mermaid_block(m.group(1)),
        md_text,
        flags=re.DOTALL,
    )

    # 2. Protect `code` spans before substituting $$...$$ and $...$ math
    code_stash = []

    def _stash_code(m):
        idx = len(code_stash)
        code_stash.append(m.group(0))
        return f"@@CODESPAN_{idx}@@"

    md_text = re.sub(r"`[^`\n]+`", _stash_code, md_text)
    md_text = re.sub(
        r"\$\$(.*?)\$\$",
        lambda m: _latex_to_html(m.group(1), display=True),
        md_text,
        flags=re.DOTALL,
    )
    md_text = re.sub(
        r"\$([^$\n]+)\$",
        lambda m: _latex_to_html(m.group(1), display=False),
        md_text,
    )
    for idx, tok in enumerate(code_stash):
        md_text = md_text.replace(f"@@CODESPAN_{idx}@@", tok)

    body_html = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    full_html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'/>"
        f"<style>{CSS_STYLES}</style></head><body>{body_html}</body></html>"
    )
    weasyprint.HTML(string=full_html, base_url=DOCS_DIR).write_pdf(pdf_path)
    print(f"[PDF] Rendered {pdf_path} ({os.path.getsize(pdf_path) / 1024.0:.1f} KiB)")


if __name__ == "__main__":
    render_summary_pdf()
