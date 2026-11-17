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
    jobname = Path(OUTPUT).stem
    subprocess.run(
        [
            "latexmk",
            "-pdf",
            f"-jobname={jobname}",
            "-interaction=nonstopmode",
            "-halt-on-error",
            SOURCE,
        ],
        cwd=PAPER,
        check=True,
    )
    subprocess.run(
        ["latexmk", "-c", f"-jobname={jobname}", SOURCE], cwd=PAPER, check=True
    )
    (PAPER / f"{jobname}.bbl").unlink(missing_ok=True)
    print(f"PDF: {PAPER / OUTPUT}")


if __name__ == "__main__":
    main()
