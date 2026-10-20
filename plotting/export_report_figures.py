"""Export report charts as standalone dark and light SVGs, with titles and legends."""

import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = {
    "Kimi baseline": "kimi-baseline",
    "DeepSeek V4 Flash baseline": "deepseek-baseline",
    "DeepSeek V4 Flash manual-only baseline": "deepseek-manual-only",
    "DeepSeek V4 Flash answer lookup penalised": "deepseek-b-caught",
    "DeepSeek V4 Flash answer lookup and computation penalised": "deepseek-ab-caught",
}
LIGHT_COLORS = {
    "#10171f": "#ffffff",
    "#dedbd3": "#27343b",
    "#a1aebc": "#64717b",
    "#303b45": "#e2e7eb",
    "#4b5864": "#d5dbde",
    "#ce9990": "#a34f43",
}


def main():
    report = (ROOT / "reports/results.html").read_text()
    charts = []
    for title, body in re.findall(
        r"<section><h2>(.*?)</h2>(.*?)</section>", report, re.S
    ):
        match = re.search(
            r'<svg viewBox="0 0 ([\d.]+) ([\d.]+)"[^>]*>(.*?)</svg>', body, re.S
        )
        if match:
            charts.append((title, body, match.groups()))
    output = ROOT / "reports/figures"
    output.mkdir(exist_ok=True)
    for title, body, (w, h, content) in charts:
        name = NAMES[html.unescape(title).split(" (n = ")[0]]
        status_match = re.search(r'<p class="trial-status">(.*?)</p>', body)
        status_offset = 26 if status_match else 0
        status = (
            f'<text x="24" y="62" style="font-size:13px">{status_match.group(1)}</text>'
            if status_match
            else ""
        )
        width, height = int(float(w)) + 48, int(float(h)) + 112 + status_offset
        legend = ""
        for i, (color, label) in enumerate(
            re.findall(
                r'<span><i style="background:(#[a-fA-F0-9]+)"></i>(.*?)</span>', body
            )
        ):
            x = 24 + i * 310
            legend += f'<rect x="{x}" y="{61+status_offset}" width="14" height="14" rx="2" fill="{color}"/><text x="{x+22}" y="{73+status_offset}" style="font-size:13px">{label}</text>'
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(html.unescape(title), quote=True)}">
<style>text{{font-family:system-ui,-apple-system,sans-serif;font-size:14px;fill:#dedbd3}}.tick{{fill:#a1aebc}}.value{{font-weight:650}}</style>
<rect width="100%" height="100%" fill="#10171f"/>
<text x="24" y="36" style="font-size:21px;font-weight:650">{title}</text>
{status}
{legend}
<g transform="translate(24 {88+status_offset})">{content}</g>
</svg>"""
        ET.fromstring(svg)
        (output / f"{name}.svg").write_text(svg + "\n")
        for old, new in LIGHT_COLORS.items():
            svg = svg.replace(old, new)
        ET.fromstring(svg)
        (output / f"{name}-light.svg").write_text(svg + "\n")
    print(f"Exported {len(charts)} charts in dark and light mode to {output}")


if __name__ == "__main__":
    main()
