# Updating the ClipForge download page

Live page: https://landryschreiner33-coder.github.io/ClipForge-AI./download/

GitHub Pages serves this page from the `download/` folder of the `gh-pages` branch in
`landryschreiner33-coder/ClipForge-AI.`. Anyone with push access to the repository can update it with an ordinary
commit: the owner, Claude Code, or ChatGPT/Codex. GitHub republishes it within a few minutes. No other hosting
account or deploy tool is needed.

## Files

| File | What it is | How to change it |
| --- | --- | --- |
| `releases.json` | The downloads: the current release and older ones, with exact URL, size, SHA-256 and source commit | Edit by hand |
| `index.html` | The page | Edit text outside the `<!-- generated:… -->` markers by hand; `build.py` writes what is inside them |
| `build.py` | Writes the generated parts from `releases.json`, checks them and can download and hash every file | Run it; standard library only |
| `site.css`, `app.js` | Look and the small optional script (puts the visitor's system first, Copy buttons) | Edit by hand; every link must still work without the script |
| `img/` | Screenshots and robot portraits from a throwaway sandbox copy of the app (no owner data) | Replace with new sandbox captures only |
| `fonts/` | Poppins SemiBold (SIL Open Font License, `OFL-Poppins.txt`) and the project's own Foundry Pixel, subset to WOFF2 | Leave as is |

Leave the rest of the branch alone unless the owner asks: `index.html`, `privacy.html`, `terms.html`, `site.css`,
`app-icon.png`, `favicon.ico` and the `tiktok….txt` file at the branch root are the pages that the TikTok and Google
app reviews point to.

## Publish a new version

1. Build the installers from one exact commit and test them. The Windows setup ZIP is built on a delivery branch
   with its readable launcher (see that branch's `README.md`). The Mac DMG is built by the *Native Mac desktop app*
   workflow and published by *Publish tested personal Mac preview* with that run's ID. Write down each file's URL,
   exact size in bytes, SHA-256 and the source commit.
2. Use only URLs that never change: a release asset (`…/releases/download/<tag>/<file>`) or a file at a fixed commit
   (`…/raw/<commit>/<file>`). Never use `latest`, a branch name or a link to a file that might be replaced.
3. In `releases.json`, add the old `current` release to the top of `previous`, then fill in `current`.
4. Run, from the root of the `gh-pages` checkout:

   ```
   python3 download/build.py            # writes the download blocks into index.html
   python3 download/build.py --verify   # downloads every listed file and compares size and SHA-256
   ```

5. Look at the page: `python3 -m http.server 8000` in the checkout, then open http://127.0.0.1:8000/download/.
   Check a desktop and a phone-sized window, in dark and light mode.
6. Commit `releases.json` and `index.html` together on `gh-pages`, with a message that names the version, and push
   normally. Never force-push. If the push is refused because someone else pushed first, fetch, put your change on
   top of the newer `gh-pages`, run `python3 download/build.py --check` again and push.
7. After a few minutes, open the live page and run `python3 download/build.py --verify` once more.

## Rules

- List only files built from a named commit and tested, with honest labels: say "personal preview", "not
  notarized" and what was not tested. Do not claim Windows security or Apple approval that did not happen.
- Plain English for someone who is not a developer. Say what to do next.
- Everything stays on this site: no scripts, fonts, trackers or images from other sites.
- `python3 download/build.py --check` must pass before every push.
