#!/usr/bin/env python3
"""Build deterministic Froganize repository and social media graphics.

The AI-assisted source illustrations are already checked into ``media/brand``.
This script adds exact typography, product claims, diagrams, and screenshots
with Pillow so generated copy never drifts.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

if __package__:
    from scripts.create_demo import DEMO_ITEMS
else:
    from create_demo import DEMO_ITEMS


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "media"
BRAND = MEDIA / "brand"
SCREENSHOTS = MEDIA / "screenshots"
RAW_SCREENSHOTS = SCREENSHOTS / "raw"
GITHUB = MEDIA / "github"
RED = MEDIA / "xiaohongshu"

CREAM = "#FFF9E8"
PAPER = "#FFFCF4"
BUTTER = "#F7D86A"
COBALT = "#3156A3"
COBALT_DARK = "#203F7C"
CORAL = "#F38B72"
INK = "#173049"
SLATE = "#607086"
PALE_BLUE = "#EAF0FF"
PALE_CORAL = "#FFF0EB"
TEAL = "#2F8F83"
WHITE = "#FFFFFF"

LATIN_REGULAR = (
    Path("/System/Library/Fonts/SFNS.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)
LATIN_ROUNDED = (
    Path("/System/Library/Fonts/SFNSRounded.ttf"),
    Path("/System/Library/Fonts/SFNS.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)
CJK_REGULAR = (
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
)
CJK_BOLD = (
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
)
MONO = (
    Path("/System/Library/Fonts/Monaco.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
)


def _font_from(candidates: Iterable[Path], size: int) -> ImageFont.FreeTypeFont:
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    raise RuntimeError(
        "No suitable font found. Install a system sans-serif font and retry."
    )


def latin(size: int, *, rounded: bool = False) -> ImageFont.FreeTypeFont:
    return _font_from(LATIN_ROUNDED if rounded else LATIN_REGULAR, size)


def cjk(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    return _font_from(CJK_BOLD if bold else CJK_REGULAR, size)


def mono(size: int) -> ImageFont.FreeTypeFont:
    return _font_from(MONO, size)


def cover(
    image: Image.Image,
    size: tuple[int, int],
    *,
    focal: tuple[float, float] = (0.5, 0.5),
) -> Image.Image:
    """Resize and crop an image to cover ``size`` around a normalized focal point."""
    target_w, target_h = size
    scale = max(target_w / image.width, target_h / image.height)
    resized = image.resize(
        (math.ceil(image.width * scale), math.ceil(image.height * scale)),
        Image.Resampling.LANCZOS,
    )
    max_x = max(0, resized.width - target_w)
    max_y = max(0, resized.height - target_h)
    left = round(max_x * min(1, max(0, focal[0])))
    top = round(max_y * min(1, max(0, focal[1])))
    return resized.crop((left, top, left + target_w, top + target_h))


def contain(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    copy = image.copy()
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    return copy


def rounded_image(image: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, image.width, image.height),
        radius=radius,
        fill=255,
    )
    result = image.convert("RGBA")
    result.putalpha(mask)
    return result


def paste_with_shadow(
    canvas: Image.Image,
    image: Image.Image,
    position: tuple[int, int],
    *,
    radius: int = 28,
    blur: int = 28,
    offset: tuple[int, int] = (0, 14),
    opacity: int = 55,
) -> None:
    image = rounded_image(image, radius)
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow.putalpha(image.getchannel("A").point(lambda value: value * opacity // 255))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(
        shadow,
        (position[0] + offset[0], position[1] + offset[1]),
    )
    canvas.alpha_composite(image, position)


def linear_overlay(
    image: Image.Image,
    color: str,
    *,
    start_alpha: int,
    end_alpha: int,
    horizontal: bool = True,
) -> Image.Image:
    base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, color)
    length = base.width if horizontal else base.height
    gradient = Image.new("L", (length, 1))
    gradient.putdata(
        [
            round(start_alpha + (end_alpha - start_alpha) * index / max(1, length - 1))
            for index in range(length)
        ]
    )
    if horizontal:
        alpha = gradient.resize(base.size)
    else:
        alpha = gradient.rotate(90, expand=True).resize(base.size)
    overlay.putalpha(alpha)
    return Image.alpha_composite(base, overlay)


def pill(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    text: str,
    *,
    fill: str,
    text_fill: str,
    font: ImageFont.FreeTypeFont,
) -> None:
    draw.rounded_rectangle(xy, radius=(xy[3] - xy[1]) // 2, fill=fill)
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    draw.text(
        (
            (xy[0] + xy[2] - width) / 2,
            (xy[1] + xy[3] - height) / 2 - bbox[1],
        ),
        text,
        font=font,
        fill=text_fill,
    )


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = image.convert("RGB")
    output.save(path, format="PNG", optimize=True)


def draw_brand_corner(
    canvas: Image.Image,
    *,
    xy: tuple[int, int],
    size: int,
    dark: bool = False,
) -> None:
    mark = Image.open(BRAND / "froganize-mascot-transparent.png").convert("RGBA")
    mark = contain(mark, (size, size))
    canvas.alpha_composite(mark, xy)
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (xy[0] + size + 12, xy[1] + size * 0.25),
        "Froganize",
        font=latin(round(size * 0.34), rounded=True),
        fill=WHITE if dark else INK,
    )


def build_github_hero() -> None:
    source = Image.open(BRAND / "froganize-welcome.png").convert("RGB")
    canvas = cover(source, (1600, 640), focal=(0.5, 0.55))
    canvas = linear_overlay(
        canvas,
        CREAM,
        start_alpha=252,
        end_alpha=5,
        horizontal=True,
    )
    canvas = canvas.convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    pill(
        draw,
        (84, 64, 510, 112),
        "macOS · local-first · developer preview",
        fill=COBALT,
        text_fill=WHITE,
        font=latin(20),
    )
    draw.text(
        (82, 145),
        "Froganize",
        font=latin(104, rounded=True),
        fill=INK,
        stroke_width=1,
    )
    draw.multiline_text(
        (88, 276),
        "Review first.\nMove only what you choose.",
        font=latin(43, rounded=True),
        fill=COBALT_DARK,
        spacing=10,
    )
    draw.text(
        (90, 405),
        "A calm, reversible monthly archive for your Mac Desktop.",
        font=latin(25),
        fill=SLATE,
    )
    steps = ("ASSESS", "SELECT", "CONFIRM", "ARCHIVE", "UNDO")
    x = 88
    for index, label in enumerate(steps):
        width = 110 if label != "CONFIRM" else 124
        pill(
            draw,
            (x, 482, x + width, 526),
            label,
            fill=PALE_BLUE if index % 2 == 0 else PALE_CORAL,
            text_fill=COBALT_DARK,
            font=latin(16),
        )
        x += width + 14
    draw.text(
        (90, 561),
        "No background monitoring · No content reading · No overwrite",
        font=latin(20),
        fill=SLATE,
    )
    save_png(canvas, GITHUB / "hero.png")


def build_social_preview() -> None:
    source = Image.open(BRAND / "froganize-welcome.png").convert("RGB")
    canvas = cover(source, (1280, 640), focal=(0.52, 0.54))
    canvas = linear_overlay(
        canvas,
        CREAM,
        start_alpha=255,
        end_alpha=0,
        horizontal=True,
    ).convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    draw.text((64, 62), "Froganize", font=latin(79, rounded=True), fill=INK)
    draw.multiline_text(
        (69, 174),
        "One click.\nA calmer Desktop.",
        font=latin(44, rounded=True),
        fill=COBALT_DARK,
        spacing=11,
    )
    draw.text(
        (71, 337),
        "A local-first macOS desktop organizer",
        font=latin(25),
        fill=SLATE,
    )
    pill(
        draw,
        (69, 404, 480, 455),
        "ONE CLICK · SAFE · REVERSIBLE",
        fill=COBALT,
        text_fill=WHITE,
        font=latin(17),
    )
    draw.text(
        (72, 505),
        "Open source · Python 3.11+ · MIT",
        font=latin(22),
        fill=INK,
    )
    save_png(canvas, GITHUB / "social-preview.png")


def build_feature_banner() -> None:
    canvas = Image.new("RGBA", (1200, 675), CREAM)
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (70, 55),
        "A gentler way to clear your Desktop",
        font=latin(52, rounded=True),
        fill=INK,
    )
    draw.text(
        (73, 124),
        "Froganize stays deliberately small: see, choose, confirm.",
        font=latin(24),
        fill=SLATE,
    )
    cards = (
        (
            "01",
            "Review",
            "Four time-and-safety groups\nmake every recommendation visible.",
            PALE_BLUE,
        ),
        (
            "02",
            "Choose",
            "Files and whole folders move\nonly after explicit selection.",
            "#FFF7D5",
        ),
        (
            "03",
            "Restore",
            "Undo the latest archive batch\nwithout overwriting conflicts.",
            PALE_CORAL,
        ),
    )
    for index, (number, title, body, fill) in enumerate(cards):
        left = 70 + index * 375
        top = 205
        draw.rounded_rectangle(
            (left, top, left + 340, top + 380),
            radius=36,
            fill=fill,
            outline="#E5E1D8",
            width=2,
        )
        draw.text(
            (left + 30, top + 28),
            number,
            font=latin(60, rounded=True),
            fill=CORAL,
        )
        draw.text(
            (left + 30, top + 119),
            title,
            font=latin(38, rounded=True),
            fill=COBALT_DARK,
        )
        draw.multiline_text(
            (left + 30, top + 184),
            body,
            font=latin(22),
            fill=INK,
            spacing=10,
        )
        draw.rounded_rectangle(
            (left + 30, top + 312, left + 310, top + 324),
            radius=6,
            fill=COBALT if index != 1 else BUTTER,
        )
    save_png(canvas, GITHUB / "features.png")


def _tree_line(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    label: str,
    *,
    kind: str,
    muted: bool = False,
    indent: int = 0,
) -> None:
    x, y = xy
    color = SLATE if muted else INK
    icon_color = COBALT if kind == "folder" else CORAL
    x += indent
    if kind == "folder":
        draw.rounded_rectangle((x, y + 5, x + 25, y + 24), radius=4, fill=icon_color)
        draw.rectangle((x + 3, y + 1, x + 14, y + 8), fill=icon_color)
    else:
        draw.rounded_rectangle((x + 3, y + 1, x + 22, y + 26), radius=3, fill=icon_color)
    draw.text((x + 38, y - 1), label, font=latin(20), fill=color)


def build_before_after() -> None:
    canvas = Image.new("RGBA", (1600, 900), CREAM)
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (80, 55),
        "Before → review → monthly timeline",
        font=latin(56, rounded=True),
        fill=INK,
    )
    draw.text(
        (84, 126),
        "Synthetic demo data · the real Froganize rules",
        font=latin(24),
        fill=SLATE,
    )
    panels = ((75, 205, 715, 820), (885, 205, 1525, 820))
    for panel in panels:
        draw.rounded_rectangle(panel, radius=38, fill=WHITE, outline="#E9E4D8", width=2)
    pill(
        draw,
        (120, 245, 310, 291),
        "BEFORE · DESKTOP",
        fill=PALE_CORAL,
        text_fill=COBALT_DARK,
        font=latin(16),
    )
    pill(
        draw,
        (930, 245, 1130, 291),
        "AFTER · TIMELINE",
        fill=PALE_BLUE,
        text_fill=COBALT_DARK,
        font=latin(16),
    )
    before = tuple(
        (
            item.name,
            "folder" if item.kind == "directory" else "file",
        )
        for item in DEMO_ITEMS
    )
    if len(before) != 12:
        raise RuntimeError("Before / After media requires exactly 12 demo items.")
    archive_names = tuple(
        item.name
        for item in DEMO_ITEMS
        if item.expected_group.value == "archive"
    )
    unsafe_names = tuple(
        item.name
        for item in DEMO_ITEMS
        if item.expected_group.value == "unsafe"
    )
    cleanup_names = tuple(
        item.name
        for item in DEMO_ITEMS
        if item.expected_group.value == "cleanup"
    )
    if archive_names != (
        "Draft Presentation.pptx",
        "Reference Photos",
        "report.pdf",
        "Client Handoff",
        "Meeting Recording.mp4",
        "Downloads 2025.zip",
    ):
        raise RuntimeError("Before / After archive names have drifted from the demo.")
    if len(cleanup_names) != 2 or len(unsafe_names) != 2:
        raise RuntimeError(
            "Before / After media requires two cleanup and two unsafe items."
        )
    y = 315
    for label, kind in before:
        _tree_line(draw, (125, y), label, kind=kind)
        y += 35
    draw.text(
        (125, 754),
        "12 top-level items · the exact safe demo",
        font=latin(18),
        fill=SLATE,
    )
    timeline = (
        ("Timeline", "folder", 0),
        ("2025", "folder", 28),
        ("2025-06", "folder", 56),
        ("Downloads 2025.zip", "file", 84),
        ("2026", "folder", 28),
        ("2026-03", "folder", 56),
        ("Meeting Recording.mp4", "file", 84),
        ("2026-05", "folder", 56),
        ("Client Handoff", "folder", 84),
        ("2026-06", "folder", 56),
        ("report (1).pdf", "file", 84),
    )
    y = 310
    for label, kind, indent in timeline:
        _tree_line(draw, (930, y), label, kind=kind, indent=indent)
        y += 34
    draw.rounded_rectangle((930, 704, 1480, 780), radius=18, fill="#F4F8F7")
    draw.text(
        (950, 718),
        "6 suggested · 4 selected · 4 safe stays · 2 cleanup + 2 reported",
        font=latin(17),
        fill=TEAL,
    )
    draw.line((754, 492, 843, 492), fill=COBALT, width=8)
    draw.polygon(((844, 492), (818, 474), (818, 510)), fill=COBALT)
    pill(
        draw,
        (744, 528, 855, 572),
        "CONFIRM",
        fill=COBALT,
        text_fill=WHITE,
        font=latin(14),
    )
    save_png(canvas, GITHUB / "before-after.png")


def build_workflow() -> None:
    canvas = Image.new("RGBA", (1400, 520), PAPER)
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (64, 46),
        "The whole workflow stays understandable",
        font=latin(48, rounded=True),
        fill=INK,
    )
    nodes = (
        ("Desktop", "top-level only"),
        ("Assess", "metadata only"),
        ("Confirm", "your selection"),
        ("Timeline", "YYYY / YYYY-MM"),
        ("Undo", "latest batch"),
    )
    colors = (PALE_CORAL, PALE_BLUE, "#FFF7D5", PALE_BLUE, "#EDF7F4")
    x = 65
    for index, ((title, subtitle), fill) in enumerate(zip(nodes, colors, strict=True)):
        draw.rounded_rectangle(
            (x, 170, x + 230, 365),
            radius=30,
            fill=fill,
            outline="#E3DED4",
            width=2,
        )
        draw.text(
            (x + 24, 211),
            f"{index + 1:02d}",
            font=latin(25, rounded=True),
            fill=CORAL,
        )
        draw.text(
            (x + 24, 257),
            title,
            font=latin(32, rounded=True),
            fill=COBALT_DARK,
        )
        draw.text(
            (x + 24, 313),
            subtitle,
            font=latin(17),
            fill=SLATE,
        )
        if index < len(nodes) - 1:
            draw.line((x + 240, 268, x + 269, 268), fill=COBALT, width=5)
            draw.polygon(
                ((x + 274, 268), (x + 260, 258), (x + 260, 278)),
                fill=COBALT,
            )
        x += 274
    save_png(canvas, GITHUB / "workflow.png")


def screenshot_or_brand(name: str, size: tuple[int, int]) -> Image.Image:
    path = RAW_SCREENSHOTS / name
    if path.is_file():
        return cover(Image.open(path).convert("RGB"), size, focal=(0.5, 0.08))
    return cover(
        Image.open(BRAND / "froganize-welcome.png").convert("RGB"),
        size,
        focal=(0.5, 0.5),
    )


def frame_screenshot(
    source_name: str,
    target_name: str,
    *,
    title: str,
    caption: str,
) -> None:
    canvas = Image.new("RGBA", (1600, 1000), CREAM)
    draw = ImageDraw.Draw(canvas)
    draw.text((70, 42), title, font=latin(46, rounded=True), fill=INK)
    draw.text((72, 101), caption, font=latin(22), fill=SLATE)
    shot = screenshot_or_brand(source_name, (1440, 810))
    paste_with_shadow(canvas, shot, (80, 165), radius=28, blur=24)
    save_png(canvas, SCREENSHOTS / target_name)


def build_screenshot_frames() -> None:
    frames = (
        (
            "dashboard-overview.png",
            "01-dashboard-overview.png",
            "See the whole Desktop at a glance",
            "Three outcomes keep the main decision clear; cleanup stays inside More tools.",
        ),
        (
            "archive-confirmation.png",
            "02-archive-confirmation.png",
            "Nothing moves without confirmation",
            "The exact top-level files and whole folders are shown one more time.",
        ),
        (
            "archive-completed.png",
            "03-archive-completed.png",
            "Only selected items enter the timeline",
            "A clear batch summary reports moved, skipped, and failed items.",
        ),
        (
            "undo-completed.png",
            "04-undo-completed.png",
            "The latest archive batch is reversible",
            "Restore stops at conflicts instead of overwriting what is already on the Desktop.",
        ),
    )
    for source, target, title, caption in frames:
        frame_screenshot(source, target, title=title, caption=caption)


def build_mobile_showcase() -> None:
    overview_path = RAW_SCREENSHOTS / "mobile-overview.png"
    groups_path = RAW_SCREENSHOTS / "mobile-groups.png"
    if not overview_path.is_file() or not groups_path.is_file():
        return

    canvas = Image.new("RGBA", (1600, 1000), CREAM)
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (70, 48),
        "The same calm review on a smaller screen",
        font=latin(47, rounded=True),
        fill=INK,
    )
    draw.text(
        (72, 107),
        "The local dashboard is responsive, with no horizontal overflow.",
        font=latin(22),
        fill=SLATE,
    )
    for path, x in ((overview_path, 420), (groups_path, 875)):
        phone = Image.open(path).convert("RGB").resize(
            (390, 844),
            Image.Resampling.LANCZOS,
        )
        paste_with_shadow(
            canvas,
            phone,
            (x, 142),
            radius=38,
            blur=28,
            offset=(0, 12),
            opacity=62,
        )
    mascot = contain(
        Image.open(BRAND / "froganize-mascot-transparent.png").convert("RGBA"),
        (330, 330),
    )
    canvas.alpha_composite(mascot, (55, 420))
    pill(
        draw,
        (75, 775, 345, 831),
        "390 × 844",
        fill=COBALT,
        text_fill=WHITE,
        font=latin(20),
    )
    draw.multiline_text(
        (78, 858),
        "Real interface\nSynthetic demo files",
        font=latin(20),
        fill=SLATE,
        spacing=8,
    )
    save_png(canvas, SCREENSHOTS / "05-responsive-mobile.png")


def build_demo_gif() -> None:
    sources = (
        (RAW_SCREENSHOTS / "dashboard-overview.png", 1800),
        (GITHUB / "workflow.png", 1500),
        (GITHUB / "before-after.png", 1800),
        (SCREENSHOTS / "05-responsive-mobile.png", 1500),
        (BRAND / "froganize-welcome.png", 1800),
    )
    if not all(path.is_file() for path, _ in sources):
        return
    frames: list[Image.Image] = []
    durations: list[int] = []
    for path, duration in sources:
        frame = cover(Image.open(path).convert("RGB"), (960, 600))
        frame = frame.quantize(colors=96, method=Image.Quantize.MEDIANCUT)
        frames.append(frame)
        durations.append(duration)
    target = GITHUB / "demo.gif"
    target.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        target,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )


def red_header(
    canvas: Image.Image,
    *,
    page: str,
    kicker: str,
    dark: bool = False,
) -> ImageDraw.ImageDraw:
    draw = ImageDraw.Draw(canvas)
    pill(
        draw,
        (74, 70, 274, 122),
        page,
        fill=CORAL,
        text_fill=INK,
        font=cjk(20, bold=True),
    )
    draw.text(
        (294, 79),
        kicker,
        font=cjk(23),
        fill=WHITE if dark else SLATE,
    )
    return draw


def build_red_covers() -> None:
    # Cover 1: mascot-led launch story.
    canvas = Image.new("RGBA", (1242, 1660), CREAM)
    portrait = cover(
        Image.open(BRAND / "froganize-portrait.png").convert("RGB"),
        (1110, 1020),
        focal=(0.5, 0.42),
    )
    paste_with_shadow(canvas, portrait, (66, 70), radius=54, blur=35)
    draw = ImageDraw.Draw(canvas)
    draw.multiline_text(
        (74, 1160),
        "我做了一只\n会整理桌面的青蛙",
        font=cjk(78, bold=True),
        fill=INK,
        spacing=20,
    )
    pill(
        draw,
        (75, 1480, 702, 1552),
        "Froganize · 开源 macOS 工具",
        fill=COBALT,
        text_fill=WHITE,
        font=cjk(29, bold=True),
    )
    save_png(canvas, RED / "covers" / "cover-01-mascot.png")

    # Cover 2: the pain point.
    scene = cover(
        Image.open(BRAND / "froganize-organizing.png").convert("RGB"),
        (1242, 1660),
        focal=(0.5, 0.5),
    )
    scene = linear_overlay(
        scene,
        COBALT_DARK,
        start_alpha=45,
        end_alpha=190,
        horizontal=False,
    ).convert("RGBA")
    draw = red_header(scene, page="方案 02", kicker="真实开发记录", dark=True)
    draw.multiline_text(
        (72, 1065),
        "桌面乱，\n但又不敢乱删？",
        font=cjk(84, bold=True),
        fill=WHITE,
        spacing=18,
        stroke_width=1,
    )
    draw.text(
        (78, 1352),
        "先看清，再决定要不要归档。",
        font=cjk(34),
        fill=CREAM,
    )
    pill(
        draw,
        (77, 1460, 531, 1531),
        "本地 · 可选 · 可撤销",
        fill=BUTTER,
        text_fill=INK,
        font=cjk(27, bold=True),
    )
    save_png(scene, RED / "covers" / "cover-02-pain-point.png")

    # Cover 3: product-first.
    canvas = Image.new("RGBA", (1242, 1660), PALE_BLUE)
    draw = red_header(canvas, page="方案 03", kicker="Froganize")
    draw.multiline_text(
        (72, 165),
        "不是自动清理\n是先看清再选择",
        font=cjk(73, bold=True),
        fill=INK,
        spacing=18,
    )
    shot = screenshot_or_brand("dashboard-overview.png", (1090, 760))
    paste_with_shadow(canvas, shot, (76, 500), radius=38, blur=35)
    mascot = contain(
        Image.open(BRAND / "froganize-mascot-transparent.png").convert("RGBA"),
        (440, 440),
    )
    canvas.alpha_composite(mascot, (760, 1160))
    draw = ImageDraw.Draw(canvas)
    pill(
        draw,
        (72, 1365, 670, 1438),
        "桌面 → 评估 → 月度时间线",
        fill=COBALT,
        text_fill=WHITE,
        font=cjk(27, bold=True),
    )
    draw.text(
        (76, 1494),
        "开源 macOS Developer Preview",
        font=cjk(27),
        fill=SLATE,
    )
    save_png(canvas, RED / "covers" / "cover-03-product.png")


def slide_base(page: str, kicker: str, *, fill: str = CREAM) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    canvas = Image.new("RGBA", (1242, 1660), fill)
    draw = red_header(
        canvas,
        page=page,
        kicker=kicker,
        dark=fill == COBALT_DARK,
    )
    return canvas, draw


def draw_bullet_card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    number: str,
    title: str,
    body: str,
    fill: str,
) -> None:
    draw.rounded_rectangle(box, radius=36, fill=fill)
    draw.text((box[0] + 34, box[1] + 28), number, font=latin(34), fill=CORAL)
    draw.text(
        (box[0] + 34, box[1] + 90),
        title,
        font=cjk(37, bold=True),
        fill=INK,
    )
    draw.multiline_text(
        (box[0] + 34, box[1] + 157),
        body,
        font=cjk(26),
        fill=SLATE,
        spacing=13,
    )


def build_red_slides() -> None:
    # 01: what it is.
    canvas, draw = slide_base("01 / 07", "软件是什么")
    draw.multiline_text(
        (72, 165),
        "一只帮你\n看清桌面的青蛙",
        font=cjk(72, bold=True),
        fill=INK,
        spacing=17,
    )
    draw.text(
        (77, 390),
        "Froganize 不会自动搬走任何东西。",
        font=cjk(30),
        fill=SLATE,
    )
    scene = cover(
        Image.open(BRAND / "froganize-welcome.png").convert("RGB"),
        (1090, 850),
        focal=(0.5, 0.5),
    )
    paste_with_shadow(canvas, scene, (76, 500), radius=45, blur=32)
    pill(
        draw,
        (77, 1430, 972, 1510),
        "评估修改时间 → 你勾选 → 确认后归档",
        fill=COBALT,
        text_fill=WHITE,
        font=cjk(28, bold=True),
    )
    save_png(canvas, RED / "slides" / "01-what-is-froganize.png")

    # 02: pain and categories.
    canvas, draw = slide_base("02 / 07", "解决什么痛点", fill=PAPER)
    draw.multiline_text(
        (72, 165),
        "乱，是因为每个文件\n都像“可能还会用”",
        font=cjk(64, bold=True),
        fill=INK,
        spacing=18,
    )
    groups = (
        ("最近 7 天修改", "留在桌面 · 默认不选", PALE_BLUE),
        ("超过 7 个完整日", "建议收起 · 等你选择", PALE_CORAL),
        ("无法安全判断", "暂不处理 · 说明原因", "#EDF7F4"),
        ("高置信临时项", "更多工具 · 默认折叠", "#F4EBFF"),
    )
    y = 465
    for index, (title, body, fill) in enumerate(groups):
        draw_bullet_card(
            draw,
            (72, y, 1170, y + 175),
            number=f"0{index + 1}",
            title=title,
            body=body,
            fill=fill,
        )
        y += 190
    save_png(canvas, RED / "slides" / "02-four-groups.png")

    # 03: how to use.
    canvas, draw = slide_base("03 / 07", "怎么使用", fill=PALE_BLUE)
    draw.text(
        (72, 165),
        "一分钟就能学会",
        font=cjk(71, bold=True),
        fill=INK,
    )
    shot = screenshot_or_brand("dashboard-overview.png", (1090, 650))
    paste_with_shadow(canvas, shot, (76, 285), radius=40, blur=30)
    steps = (
        ("1", "打开", "双击本机应用"),
        ("2", "选择", "从三个结果中勾选"),
        ("3", "确认", "确认后才安全收起"),
    )
    x = 72
    for number, title, body in steps:
        draw.rounded_rectangle((x, 1030, x + 342, 1392), radius=34, fill=WHITE)
        draw.text((x + 28, 1062), number, font=latin(48), fill=CORAL)
        draw.text((x + 28, 1148), title, font=cjk(38, bold=True), fill=INK)
        draw.multiline_text(
            (x + 28, 1220),
            body,
            font=cjk(25),
            fill=SLATE,
            spacing=8,
        )
        x += 368
    draw.text(
        (76, 1487),
        "文件夹永远整体移动，不会被拆散。",
        font=cjk(28, bold=True),
        fill=COBALT_DARK,
    )
    save_png(canvas, RED / "slides" / "03-how-to-use.png")

    # 04: before / after.
    canvas, draw = slide_base("04 / 07", "整理效果")
    draw.text(
        (72, 164),
        "桌面保留判断，旧项目进入时间线",
        font=cjk(51, bold=True),
        fill=INK,
    )
    before_after = contain(
        Image.open(GITHUB / "before-after.png").convert("RGB"),
        (1090, 700),
    )
    image_x = (1242 - before_after.width) // 2
    paste_with_shadow(
        canvas,
        before_after,
        (image_x, 315),
        radius=42,
        blur=30,
    )
    metrics = (
        ("12", "桌面顶层项目"),
        ("4", "本次选择收起"),
        ("0", "默认自动选择"),
    )
    x = 72
    for value, label in metrics:
        draw.rounded_rectangle((x, 1010, x + 342, 1240), radius=34, fill=WHITE)
        draw.text((x + 30, 1040), value, font=latin(56, rounded=True), fill=CORAL)
        draw.text((x + 30, 1128), label, font=cjk(25, bold=True), fill=INK)
        x += 368
    draw.text(
        (78, 1310),
        "6 项被建议收起，这次只选择 4 项；其余继续留在桌面。",
        font=cjk(26),
        fill=COBALT_DARK,
    )
    draw.text(
        (80, 1445),
        "同名文件自动避让：report.pdf → report (1).pdf",
        font=cjk(25),
        fill=SLATE,
    )
    save_png(canvas, RED / "slides" / "04-before-after.png")

    # 05: safety.
    canvas, draw = slide_base("05 / 07", "我最在意的功能", fill=PAPER)
    draw.multiline_text(
        (72, 165),
        "整理工具首先要做到：\n别让人害怕",
        font=cjk(68, bold=True),
        fill=INK,
        spacing=18,
    )
    cards = (
        ("LOCAL", "只在本机", "127.0.0.1\n无遥测、无外网请求", PALE_BLUE),
        ("WHOLE", "文件夹整体", "读取名称与元数据\n不读取文件内容", "#FFF7D5"),
        ("SAFE", "永不覆盖", "同名自动改名\n执行前再次确认", PALE_CORAL),
        ("UNDO", "最近批次可撤销", "恢复遇到冲突\n就停下并报告", "#EDF7F4"),
    )
    positions = ((72, 520), (638, 520), (72, 930), (638, 930))
    for (label, title, body, fill), (x, y) in zip(cards, positions, strict=True):
        draw.rounded_rectangle((x, y, x + 532, y + 360), radius=40, fill=fill)
        pill(
            draw,
            (x + 30, y + 30, x + 180, y + 78),
            label,
            fill=COBALT,
            text_fill=WHITE,
            font=latin(16),
        )
        draw.text((x + 30, y + 118), title, font=cjk(37, bold=True), fill=INK)
        draw.multiline_text(
            (x + 30, y + 190),
            body,
            font=cjk(26),
            fill=SLATE,
            spacing=12,
        )
    draw.text(
        (75, 1445),
        "无法完整判断的项目默认留在桌面，并明确说明原因。",
        font=cjk(27, bold=True),
        fill=COBALT_DARK,
    )
    save_png(canvas, RED / "slides" / "05-safety.png")

    # 06: open source.
    canvas, draw = slide_base("06 / 07", "GitHub 开源", fill=COBALT_DARK)
    draw.text(
        (72, 164),
        "代码、测试、路线图\n都可以被看见",
        font=cjk(69, bold=True),
        fill=WHITE,
        spacing=18,
    )
    draw.rounded_rectangle((72, 455, 1170, 1075), radius=44, fill="#132C58")
    commands = (
        "$ python3 -m venv .venv",
        "$ source .venv/bin/activate",
        '$ python -m pip install -e ".[dev]"',
        "$ python -m pytest",
        "",
        "All tests passed",
    )
    y = 520
    for command in commands:
        color = BUTTER if command == "All tests passed" else "#DCE7FF"
        draw.text((118, y), command, font=mono(27), fill=color)
        y += 76
    mascot = contain(
        Image.open(BRAND / "froganize-mascot-transparent.png").convert("RGBA"),
        (440, 440),
    )
    canvas.alpha_composite(mascot, (735, 1000))
    pill(
        draw,
        (72, 1205, 685, 1281),
        "Star · Fork · Issue · Feedback",
        fill=BUTTER,
        text_fill=INK,
        font=latin(26, rounded=True),
    )
    draw.multiline_text(
        (76, 1370),
        "仓库地址将在公开发布后同步。\n不虚构链接，也不伪造 Star History。",
        font=cjk(26),
        fill="#DCE7FF",
        spacing=13,
    )
    save_png(canvas, RED / "slides" / "06-open-source.png")

    # 07: roadmap.
    canvas, draw = slide_base("07 / 07", "下一步", fill="#FFF7D5")
    draw.text(
        (72, 164),
        "让 Froganize\n慢慢长成真正的产品",
        font=cjk(68, bold=True),
        fill=INK,
        spacing=18,
    )
    roadmap = (
        (
            "NOW",
            "macOS Developer Preview",
            "安全源码安装、本地网页、CI 与双语文档",
        ),
        ("NEXT", "偏好与排除规则", "阈值、始终保留、筛选与搜索"),
        (
            "LATER",
            "更原生的 Mac 体验",
            "Developer ID 签名与公证、原生窗口、国际化",
        ),
    )
    y = 520
    for label, title, body in roadmap:
        draw.rounded_rectangle((72, y, 1170, y + 245), radius=38, fill=WHITE)
        pill(
            draw,
            (108, y + 34, 288, y + 88),
            label,
            fill=COBALT,
            text_fill=WHITE,
            font=latin(18),
        )
        draw.text((326, y + 34), title, font=cjk(36, bold=True), fill=INK)
        draw.text((110, y + 130), body, font=cjk(27), fill=SLATE)
        y += 280
    mascot = contain(
        Image.open(BRAND / "froganize-mascot-transparent.png").convert("RGBA"),
        (330, 330),
    )
    canvas.alpha_composite(mascot, (850, 1300))
    draw.text(
        (75, 1445),
        "欢迎一起测试、提 Issue、分享真实使用感受。",
        font=cjk(27, bold=True),
        fill=COBALT_DARK,
    )
    save_png(canvas, RED / "slides" / "07-roadmap.png")


def validate_outputs() -> None:
    github_sizes = {
        GITHUB / "hero.png": (1600, 640),
        GITHUB / "social-preview.png": (1280, 640),
        GITHUB / "native-dashboard.png": (2400, 1600),
        GITHUB / "features.png": (1200, 675),
        GITHUB / "before-after.png": (1600, 900),
        GITHUB / "workflow.png": (1400, 520),
    }
    brand_sizes = {
        BRAND / "froganize-mascot-transparent.png": (1254, 1254),
        BRAND / "froganize-organizing.png": (1536, 1024),
        BRAND / "froganize-portrait.png": (1254, 1254),
        BRAND / "froganize-welcome.png": (1536, 1024),
    }
    framed_sizes = {
        SCREENSHOTS / "01-dashboard-overview.png": (1600, 1000),
        SCREENSHOTS / "02-archive-confirmation.png": (1600, 1000),
        SCREENSHOTS / "03-archive-completed.png": (1600, 1000),
        SCREENSHOTS / "04-undo-completed.png": (1600, 1000),
        SCREENSHOTS / "05-responsive-mobile.png": (1600, 1000),
    }
    raw_sizes = {
        RAW_SCREENSHOTS / "archive-completed.png": (1440, 900),
        RAW_SCREENSHOTS / "archive-confirmation.png": (1440, 900),
        RAW_SCREENSHOTS / "archive-recommendations.png": (1440, 900),
        RAW_SCREENSHOTS / "dashboard-overview.png": (1440, 900),
        RAW_SCREENSHOTS / "four-groups-full.png": (1440, 2606),
        RAW_SCREENSHOTS / "mobile-groups.png": (390, 844),
        RAW_SCREENSHOTS / "mobile-overview.png": (390, 844),
        RAW_SCREENSHOTS / "undo-completed.png": (1440, 900),
        RAW_SCREENSHOTS / "undo-confirmation.png": (1440, 900),
        RAW_SCREENSHOTS / "unsafe-items.png": (1440, 900),
    }
    cover_names = (
        "cover-01-mascot.png",
        "cover-02-pain-point.png",
        "cover-03-product.png",
    )
    slide_names = (
        "01-what-is-froganize.png",
        "02-four-groups.png",
        "03-how-to-use.png",
        "04-before-after.png",
        "05-safety.png",
        "06-open-source.png",
        "07-roadmap.png",
    )
    social_sizes = {
        **{
            RED / "covers" / name: (1242, 1660)
            for name in cover_names
        },
        **{
            RED / "slides" / name: (1242, 1660)
            for name in slide_names
        },
    }

    required_sets = (
        (BRAND, frozenset(path.name for path in brand_sizes)),
        (SCREENSHOTS, frozenset(path.name for path in framed_sizes)),
        (RAW_SCREENSHOTS, frozenset(path.name for path in raw_sizes)),
        (RED / "covers", frozenset(cover_names)),
        (RED / "slides", frozenset(slide_names)),
    )
    for directory, required_names in required_sets:
        existing_names = frozenset(path.name for path in directory.glob("*.png"))
        if existing_names != required_names:
            missing = ", ".join(sorted(required_names - existing_names)) or "none"
            unexpected = ", ".join(sorted(existing_names - required_names)) or "none"
            raise RuntimeError(
                f"Unexpected PNG set in {directory}; "
                f"missing: {missing}; unexpected: {unexpected}"
            )

    expected = {
        **github_sizes,
        **brand_sizes,
        **framed_sizes,
        **raw_sizes,
        **social_sizes,
    }
    for path, size in expected.items():
        if not path.is_file():
            raise RuntimeError(f"Missing generated media: {path}")
        with Image.open(path) as image:
            if image.size != size:
                raise RuntimeError(
                    f"Unexpected size for {path}: {image.size}, wanted {size}"
                )
            image.load()

    mascot = BRAND / "froganize-mascot-transparent.png"
    with Image.open(mascot) as image:
        if "A" not in image.getbands():
            raise RuntimeError(f"Transparent mascot has no alpha channel: {mascot}")
        alpha_minimum, _alpha_maximum = image.getchannel("A").getextrema()
        if alpha_minimum == 255:
            raise RuntimeError(f"Transparent mascot has no transparent pixels: {mascot}")

    social = GITHUB / "social-preview.png"
    if social.stat().st_size >= 1_000_000:
        raise RuntimeError(
            "GitHub social preview must remain below 1 MB: "
            f"{social.stat().st_size} bytes"
        )
    demo = GITHUB / "demo.gif"
    if not demo.is_file():
        raise RuntimeError(f"Missing generated media: {demo}")
    with Image.open(demo) as image:
        if image.size != (960, 600):
            raise RuntimeError(
                f"Unexpected size for {demo}: {image.size}, wanted (960, 600)"
            )
        if image.n_frames != 5:
            raise RuntimeError(
                f"Unexpected frame count for {demo}: {image.n_frames}, wanted 5"
            )
        for frame in range(image.n_frames):
            image.seek(frame)
            image.load()
    if demo.stat().st_size >= 8_000_000:
        raise RuntimeError(
            "README demo GIF must remain below 8 MB: "
            f"{demo.stat().st_size} bytes"
        )


def build_all() -> None:
    build_github_hero()
    build_social_preview()
    build_feature_banner()
    build_before_after()
    build_workflow()
    build_screenshot_frames()
    build_mobile_showcase()
    build_demo_gif()
    build_red_covers()
    build_red_slides()
    validate_outputs()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Froganize repository and social media graphics.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate existing generated media without rebuilding it",
    )
    arguments = parser.parse_args()
    if arguments.validate_only:
        validate_outputs()
    else:
        build_all()
    print("Froganize media ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
