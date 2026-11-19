# Project page

A buildless, dark project page with the existing interactive report in a Results tab.
No fonts, analytics, or JavaScript dependencies are downloaded by the site.

Build and preview from the repository root:

```sh
uv run --no-project site/build.py
uv run --no-project python -m http.server 8000 --directory generated/site
```

Open http://localhost:8000. Edit `site/index.html` and `site/style.css` for the
landing page; the root `results.html` remains the source of truth for the report.
The build removes links to unpublished local trajectories while retaining excerpts.
Only the three site files, the generated report, and `.nojekyll` are deployed.

## GitHub Pages

In the repository's **Settings → Pages**, select **GitHub Actions** as the source.
Commit and push `site/` and `.github/workflows/pages.yml` to `main`. The workflow
publishes on changes to the site or report and can also be run manually.
Expected URL: https://sbdzdz.github.io/cheating-escalation/

The workflow publishes a dedicated artifact, never the repository root.
