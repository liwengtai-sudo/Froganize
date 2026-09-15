# Froganize visual identity

This guide keeps the repository, application, documentation, and social media
materials visually consistent.

## Brand idea

Froganize turns desktop cleanup from an anxious automatic action into a calm
review:

```text
see clearly → choose deliberately → archive safely → undo if needed
```

The mascot should feel reassuring and capable, never hyperactive. Visuals
should suggest order without implying deletion, surveillance, or files moving
without confirmation.

## Color system

| Role | Name | Hex |
| --- | --- | --- |
| Primary character | Butter yellow | `#F7D86A` |
| Primary action | Cobalt blue | `#3156A3` |
| Small accent | Coral | `#F38B72` |
| Main background | Warm cream | `#FFF9E8` |
| Primary text | Deep ink | `#173049` |
| Muted text | Slate | `#607086` |
| Success | Calm teal | `#2F8F83` |

Use warm cream as the dominant canvas. Cobalt carries actions and structure;
coral should stay below roughly 10% of a composition.

## Typography

- Product UI: the native system sans-serif stack.
- Repository graphics: a clean rounded sans serif, using system fallbacks.
- Code and paths: a monospaced system face.
- Avoid decorative display fonts and all-caps paragraphs.

## Mascot invariants

The official Froganize mascot has:

- a butter-yellow, nearly spherical trapezoid body;
- a front-facing, broadly symmetrical silhouette;
- two cobalt circular eye plates;
- flat coral horizontal pupils without reflections;
- tiny blue nostrils and a minimal blue mouth;
- slightly extended little feet;
- a cobalt folder held at the center.

Do not recolor the mascot green, add human clothing, use realistic human limbs,
or turn the expression into a loud cartoon reaction.

## Logo system

- `media/brand/froganize-mark.svg` — compact flat mark for diagrams and small
  placements.
- `media/brand/froganize-lockup.svg` — horizontal wordmark and product line.
- `src/dropnest/web_assets/froganize-{idle,organizing,calendar,success}.svg` —
  transparent native-UI poses rendered at Retina density. Use these for small
  controls and state illustrations instead of shrinking the 3D PNG cutout.
- `media/brand/froganize-mascot-transparent.png` — official high-resolution
  mascot cutout.
- `assets/Froganize.icns` — local macOS application icon.

Keep clear space around the mark equal to at least one pupil height. Do not
place the yellow mascot on bright yellow or high-detail photography.

## Image specifications

| Use | Canvas | Preferred file |
| --- | ---: | --- |
| GitHub README hero | `1600 × 640` | PNG |
| GitHub social preview | `1280 × 640` | PNG |
| README screenshot | `1440 × 900` | PNG |
| README feature graphic | `1200 × 675` | PNG |
| Xiaohongshu cover/slide | `1242 × 1660` | PNG |
| Mascot portrait | `1254 × 1254` or larger | PNG |

Repository screenshots use synthetic demo paths, consistent browser dimensions,
and no personal files.

## Voice

Preferred:

- calm, clear, and specific;
- “review”, “recommend”, “confirm”, “archive”, and “restore”;
- state limitations next to capabilities;
- describe safety properties with testable language.

Avoid:

- “magically cleans everything”;
- “zero risk” or “perfectly safe”;
- broad “AI-powered file organizer” claims (AI is currently limited to the
  explicitly enabled Screenshot Intelligence feature);
- claims of automatic background cleanup;
- unverified cross-platform or distribution claims.

## Campaign assets

The source campaign images live in `media/brand/`:

- `froganize-welcome.png` — welcoming workspace scene;
- `froganize-organizing.png` — file-to-timeline organizing scene;
- `froganize-portrait.png` — mascot-only campaign portrait;
- `froganize-mascot-transparent.png` — transparent character artwork.

Composed repository and social assets are generated from these sources plus
real product screenshots. Text is added deterministically after image
generation so brand names and safety claims remain exact. See
[`media/brand/PROMPTS.md`](../media/brand/PROMPTS.md) for the accepted
reference-guided illustration briefs.

## Website narrative

The local static prototype under `website/` extends the same visual system
without changing the product mascot. Its four-scene narrative is deliberately
small:

1. Froganize feels uncertain beside a restrained set of scattered files.
2. Froganize discovers a wooden wand with a cobalt folder-shaped head.
3. Froganize learns to suggest and organize rather than move everything.
4. Froganize becomes a calm companion beside an ordered monthly archive.

The story may use gentle magic as a metaphor, but adjacent product copy must
always translate it into the real flow: assess, select, confirm, and undo.
Never imply autonomous background movement, perfect safety, content reading,
or deletion. The accepted story prompts and reused source images are recorded
in [`website/assets/PROMPTS.md`](../website/assets/PROMPTS.md).
