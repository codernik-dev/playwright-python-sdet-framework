# Image assets

Everything here is generated from an HTML source that sits beside it, so a number
that changes in the repository can be changed in one place and re-rendered, rather
than being retouched in an image editor where nobody can diff it.

| File | Size | Where it is used |
|---|---|---|
| `social-preview.png` | 2560x1280 | GitHub **Settings > General > Social preview**. This is the card that LinkedIn, Slack and X show when the repository URL is pasted. Without it, GitHub serves a generic auto-generated fallback |
| `social-preview.html` | - | The source of the above |

The card is laid out at 1280x640, which is the size GitHub asks for, and rendered at
twice that so it stays sharp on a high-density screen. GitHub scales it down.

## Regenerating

Any headless Chrome will do; there is no build step and no dependency to install
beyond the browser you already have.

```bash
chrome --headless --disable-gpu --window-size=1280,640 \
       --screenshot=docs/images/social-preview.png \
       docs/images/social-preview.html
```

That writes the 1x version, which is enough. For the 2x file committed here, drive
the same page through any headless browser with a device scale factor of 2.

On Windows, `chrome` is usually
`C:\Program Files\Google\Chrome\Application\chrome.exe`.

## The numbers on the card

Each is traceable, and each should be re-checked against its source before the card
is regenerated. They are the same figures the README leads with.

| On the card | Source |
|---|---|
| 351 tests, 136 negative | [docs/phase-15-measurement.md](../phase-15-measurement.md) |
| 0 flakes in 3,510 executions | 10 consecutive `-n 4` runs, same document |
| 94 files, mypy strict | [docs/phase-13-quality-pass.md](../phase-13-quality-pass.md) |
| 16.82 s, 4 workers | Median of 3, AMD Ryzen 7 5800H, same document |

If a number here disagrees with `docs/progress.md`, the progress log wins and this
card is out of date.
