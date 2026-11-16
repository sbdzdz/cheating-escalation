"""Compile the paper and remove intermediate files, keeping the PDF.

Run with: uv run paper/compile.py
On failure, keep the build logs for diagnosis.
"""

import subprocess
from pathlib import Path

PAPER = Path(__file__).resolve().parent
SOURCE = "main.tex"
OUTPUT = "cheating_escalation.pdf"


def main():
    subprocess.run(
        ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", SOURCE],
        cwd=PAPER,
        check=True,
    )
    subprocess.run(["latexmk", "-c", SOURCE], cwd=PAPER, check=True)
    (PAPER / Path(SOURCE).with_suffix(".bbl")).unlink(missing_ok=True)
    (PAPER / Path(SOURCE).with_suffix(".pdf")).replace(PAPER / OUTPUT)
    print(f"PDF: {PAPER / OUTPUT}")


if __name__ == "__main__":
    main()
