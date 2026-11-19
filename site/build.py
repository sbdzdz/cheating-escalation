# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build an allowlisted, dependency-free GitHub Pages artifact."""

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "generated" / "site"
if DEST.exists():
    shutil.rmtree(DEST)
DEST.mkdir(parents=True)
for name in ("index.html", "results.html", "style.css"):
    shutil.copyfile(ROOT / "site" / name, DEST / name)

report = (ROOT / "results.html").read_text()
# Keep excerpts, but remove links into unpublished local experiment outputs.
report = re.sub(
    r'<a\b[^>]*href=[\"\']outputs/[^\"\']*[\"\'][^>]*>(.*?)</a>',
    r'<span title="Source trajectory retained in the local experiment archive">\1</span>',
    report,
    flags=re.DOTALL,
)
# Match the site chrome; preserve the chart colours and interactions.
report = report.replace("#10171f", "#10151d").replace("#19222c", "#171e28")
report = report.replace(
    "</head>",
    "<style>main{max-width:1160px;padding:36px 32px}"
    "@media(max-width:640px){main{padding:36px 20px}}</style></head>",
)
(DEST / "report.html").write_text(report)
(DEST / ".nojekyll").touch()
print(f"Built {DEST}")
