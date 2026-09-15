# Froganize media kit

This directory contains the public visual kit for Froganize. The screenshots
use synthetic demo files only; no personal Desktop content appears in them.

## Repository media

`github/native-dashboard.png` is the current source-beta screenshot and is
generated from synthetic temporary data with
`scripts/capture_native_preview.py`. The older hero, workflow, browser
screenshots, Before/After, and GIF below document the retired seven-day
selection-era concept; keep them as design history, but do not use them to
describe the current one-click contract.

| Asset | Purpose | Size |
| --- | --- | --- |
| `github/native-dashboard.png` | Current native one-click dashboard | 2400 × 1600 |
| `github/hero.png` | README banner | 1600 × 640 |
| `github/social-preview.png` | GitHub social preview upload | 1280 × 640 |
| `github/features.png` | Feature overview | 1200 × 675 |
| `github/before-after.png` | Before / After story | 1600 × 900 |
| `github/workflow.png` | Product workflow | 1400 × 520 |
| `github/demo.gif` | Short README walkthrough | 960 × 600 |
| `screenshots/01-*.png` through `05-*.png` | Framed screenshots | 1600 × 1000 |

The files in `screenshots/raw/` are the matching browser captures before
framing and use descriptive state names. Keep those raw names and the framed
screenshots' `01`–`05` numeric prefixes stable so documentation links remain
durable.

## Brand media

- `brand/froganize-mascot-transparent.png` — approved transparent mascot;
- `brand/froganize-portrait.png` — standalone character portrait;
- `brand/froganize-welcome.png` — welcome/launch scene;
- `brand/froganize-organizing.png` — file-organizing scene;
- `brand/froganize-mark.svg` — compact vector mark;
- `brand/froganize-lockup.svg` — horizontal logo lockup.

The raster brand scenes are AI-assisted, identity-preserving illustrations.
Exact claims and typography are added separately by the deterministic media
builder so product copy does not drift. The accepted creative briefs and
generation mode are recorded in [`brand/PROMPTS.md`](brand/PROMPTS.md).

## Xiaohongshu / RED kit

`xiaohongshu/covers/` contains three alternate 3:4 covers.
`xiaohongshu/slides/` contains the seven-page story.
`xiaohongshu/copy.zh-CN.md` contains titles, long and short copy, hashtags, and
the release placeholders that must be replaced only after public URLs exist.

See [`docs/social-publishing-kit.zh-CN.md`](../docs/social-publishing-kit.zh-CN.md)
for the publishing sequence and cross-platform checklist.

## Rebuild and validate

Install the optional media dependency, then rebuild:

```bash
python -m pip install -e ".[media]"
python scripts/build_media.py
```

Validate committed output without rewriting it:

```bash
python scripts/build_media.py --validate-only
```

The builder requires the complete four-image brand set, five framed
screenshots, ten raw captures, three RED covers, seven RED slides, and the
five-frame GIF. It checks their dimensions, verifies real mascot transparency,
and enforces practical Social Preview and GIF size limits. It intentionally
does not generate the three AI-assisted source illustrations.
