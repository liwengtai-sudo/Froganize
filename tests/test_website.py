"""Static checks for the local Froganize website."""

from __future__ import annotations

import json
import re
import struct
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEBSITE = PROJECT_ROOT / "website"
REPOSITORY_URL = "https://github.com/liwengtai-sudo/Froganize"


class WebsiteParser(HTMLParser):
    """Collect structural, link, image, and metadata facts from one page."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.references: list[tuple[str, str]] = []
        self.images: list[dict[str, str]] = []
        self.anchors: list[dict[str, str]] = []
        self.download_links: list[dict[str, str]] = []
        self.story_scenes = 0
        self.story_images: list[dict[str, str]] = []
        self.script_types: list[str] = []
        self.json_ld_payloads: list[str] = []
        self.meta: list[dict[str, str]] = []
        self._inside_json_ld = False
        self._json_ld_parts: list[str] = []
        self._inside_story_scene = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = {key: value or "" for key, value in attrs}
        element_id = values.get("id")
        if element_id:
            self.ids.add(element_id)

        classes = set(values.get("class", "").split())
        if tag == "article" and "story-scene" in classes:
            self.story_scenes += 1
            self._inside_story_scene = True
        if tag == "a":
            self.anchors.append(values)
            if "download-cta" in classes:
                self.download_links.append(values)
        if tag == "script":
            script_type = values.get("type", "")
            self.script_types.append(script_type)
            self._inside_json_ld = script_type == "application/ld+json"
            self._json_ld_parts = []
        if tag == "meta":
            self.meta.append(values)
        if tag == "img":
            self.images.append(values)
            if self._inside_story_scene:
                self.story_images.append(values)

        for attribute in ("href", "src"):
            reference = values.get(attribute, "")
            if reference:
                self.references.append((attribute, reference))
        if tag in {"img", "source"} and values.get("srcset"):
            for candidate in values["srcset"].split(","):
                self.references.append(("srcset", candidate.strip().split()[0]))

    def handle_data(self, data: str) -> None:
        if self._inside_json_ld:
            self._json_ld_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "article" and self._inside_story_scene:
            self._inside_story_scene = False
        if tag == "script" and self._inside_json_ld:
            self.json_ld_payloads.append("".join(self._json_ld_parts))
            self._inside_json_ld = False
            self._json_ld_parts = []


def parse_page(name: str = "index.html") -> tuple[str, WebsiteParser]:
    html = (WEBSITE / name).read_text(encoding="utf-8")
    parser = WebsiteParser()
    parser.feed(html)
    return html, parser


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_homepage_leads_with_product_value_before_brand_story() -> None:
    html, parser = parse_page()
    visible_text = re.sub(r"<[^>]+>", " ", html)
    compact_text = re.sub(r"\s+", "", visible_text)

    assert '<html lang="zh-CN">' in html
    assert "Froganize 是一款本地优先的 Mac 桌面整理工具" in html
    assert "给桌面一点整理魔法。" in compact_text
    assert "桌面，留给正在发生的事。" not in compact_text
    assert "桌面乱一点" not in compact_text
    assert "真的没关系" not in compact_text
    assert "青蛙仔" not in html
    assert "蛙仔" in html
    assert "该留的留下" in html
    assert "该收的收好" in html
    assert "Open" in html
    assert "Collect" in html
    assert "Timeline" in html
    assert "Calendar &amp; Undo" in html
    assert "打开只生成安全计划" in html
    assert REPOSITORY_URL in html
    assert "7 天" not in html
    assert "默认不勾选" not in html
    assert parser.story_scenes == 4

    assert re.search(r"听听.{0,24}故事", visible_text, flags=re.DOTALL) is None

    assert len(parser.download_links) >= 2
    assert {link.get("href") for link in parser.download_links} == {
        REPOSITORY_URL
    }
    assert html.index("download-cta") < html.index('id="transformation"')

    section_order = [
        html.index('id="transformation"'),
        html.index('id="workflow"'),
        html.index('id="product"'),
        html.index('id="safety"'),
        html.index('id="story"'),
        html.index('id="release"'),
    ]
    assert section_order == sorted(section_order)


def test_website_uses_wazi_name_consistently() -> None:
    """The retired mascot name must not survive in copy, docs, or SVG text."""

    text_suffixes = {".html", ".md", ".css", ".svg", ".txt"}
    text_files = sorted(
        path
        for path in WEBSITE.rglob("*")
        if path.is_file() and path.suffix.lower() in text_suffixes
    )

    assert text_files
    for path in text_files:
        content = path.read_text(encoding="utf-8")
        assert "青蛙仔" not in content, f"Retired mascot name remains in {path}"


def test_story_is_four_accessible_responsive_blended_scenes() -> None:
    html, parser = parse_page()

    expected_sources = [
        "./assets/story-01-chaos.jpg",
        "./assets/story-02-wand.jpg",
        "./assets/story-03-learning.jpg",
        "./assets/story-04-master.jpg",
    ]
    expected_alt_clues = ("散乱", "魔法杖", "练习", "整齐")

    assert parser.story_scenes == 4
    assert [image.get("src") for image in parser.story_images] == expected_sources
    for image, clue in zip(parser.story_images, expected_alt_clues, strict=True):
        assert image.get("alt")
        assert "青蛙仔" not in image["alt"]
        assert "蛙仔" in image["alt"]
        assert clue in image["alt"]
        assert "srcset" in image
        assert "./assets/responsive/" in image["srcset"]
        assert image.get("loading") == "lazy"
        assert image.get("decoding") == "async"

    assert "文件夹魔法杖" in html


def test_vector_mascot_system_bridges_story_and_product_workflow() -> None:
    html, _ = parse_page()
    expected = (
        "froganize-idle.svg",
        "froganize-organizing.svg",
        "froganize-calendar.svg",
        "froganize-success.svg",
    )

    assert 'class="story-product-bridge"' in html
    assert "故事里的蛙仔变成清晰的矢量伙伴" in html
    for name in expected:
        path = WEBSITE / "assets" / name
        root = ET.parse(path).getroot()
        assert root.tag.endswith("svg")
        assert root.get("viewBox") == "0 0 256 256"
        assert f"./assets/{name}" in html
        assert "<image" not in path.read_text(encoding="utf-8")


def test_site_pages_are_self_contained_and_all_links_resolve() -> None:
    pages = sorted(path.name for path in WEBSITE.glob("*.html"))
    assert pages == ["changelog.html", "index.html", "privacy.html"]
    parsed = {name: parse_page(name)[1] for name in pages}
    css = (WEBSITE / "styles.css").read_text(encoding="utf-8")

    assert "@import" not in css
    for page_name, parser in parsed.items():
        for anchor in parser.anchors:
            href = anchor.get("href", "")
            assert href, f"Empty href in {page_name}"
            assert href != "#", f"Placeholder href in {page_name}"
            assert not href.lower().startswith("javascript:"), (
                f"JavaScript href in {page_name}: {href}"
            )

        for attribute, reference in parser.references:
            if reference.startswith("https://www.froganize.com/"):
                continue
            if reference == REPOSITORY_URL:
                continue
            assert not reference.startswith(("http://", "https://", "//"))

            if reference.startswith("#"):
                assert reference[1:] in parser.ids
                continue
            if not reference.startswith("./"):
                continue

            parts = urlsplit(reference)
            target = WEBSITE / parts.path.removeprefix("./")
            assert target.is_file(), f"Missing local website target: {reference}"
            if parts.fragment:
                target_parser = parsed[target.name]
                assert parts.fragment in target_parser.ids, (
                    f"Missing fragment #{parts.fragment} in {target.name}"
                )


def test_homepage_has_static_seo_metadata_for_public_domain() -> None:
    html, parser = parse_page()
    metadata = {
        item.get("property") or item.get("name"): item.get("content", "")
        for item in parser.meta
        if item.get("property") or item.get("name")
    }

    assert metadata["description"].startswith("Froganize 是一款本地优先")
    assert metadata["og:type"] == "website"
    assert metadata["og:locale"] == "zh_CN"
    assert metadata["og:title"].startswith("Froganize")
    assert metadata["twitter:card"] == "summary_large_image"
    assert '<link rel="canonical" href="https://www.froganize.com/">' in html
    assert metadata["og:url"] == "https://www.froganize.com/"
    assert metadata["og:image"] == (
        "https://www.froganize.com/assets/social-preview.png"
    )
    assert metadata["twitter:image"] == metadata["og:image"]
    assert parser.script_types == ["application/ld+json"]
    assert len(parser.json_ld_payloads) == 1

    structured_data = json.loads(parser.json_ld_payloads[0])
    assert structured_data["@type"] == "SoftwareApplication"
    assert structured_data["name"] == "Froganize"
    assert structured_data["operatingSystem"] == "macOS"
    assert structured_data["url"] == "https://www.froganize.com/"
    assert structured_data["image"] == metadata["og:image"]
    assert (WEBSITE / "robots.txt").read_text(encoding="utf-8").startswith(
        "User-agent: *\nAllow: /"
    )
    assert "https://www.froganize.com/sitemap.xml" in (
        WEBSITE / "robots.txt"
    ).read_text(encoding="utf-8")

    sitemap = ET.parse(WEBSITE / "sitemap.xml").getroot()
    namespace = {"sitemap": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locations = {
        item.text
        for item in sitemap.findall("sitemap:url/sitemap:loc", namespace)
    }
    assert locations == {
        "https://www.froganize.com/",
        "https://www.froganize.com/changelog.html",
        "https://www.froganize.com/privacy.html",
    }


def test_images_are_accessible_responsive_and_right_sized() -> None:
    _, parser = parse_page()

    assert len(parser.images) >= 9
    for image in parser.images:
        assert "alt" in image
        assert image.get("src", "").startswith("./assets/")
        assert image.get("width", "").isdigit()
        assert image.get("height", "").isdigit()

    html = (WEBSITE / "index.html").read_text(encoding="utf-8")
    assert "native-dashboard.png" in html
    assert "dashboard-ui-mobile.png" not in html
    assert html.count("srcset=") >= 6
    assert 'fetchpriority="high"' in html
    assert html.count('decoding="async"') >= 7
    assert html.count('loading="lazy"') >= 6

    story_assets = sorted((WEBSITE / "assets").glob("story-*.jpg"))
    assert [path.name for path in story_assets] == [
        "story-01-chaos.jpg",
        "story-02-wand.jpg",
        "story-03-learning.jpg",
        "story-04-master.jpg",
    ]
    for path in story_assets:
        assert path.stat().st_size > 100_000
        assert path.read_bytes()[:3] == b"\xff\xd8\xff"

    assert png_dimensions(WEBSITE / "assets" / "froganize-mascot-128.png") == (
        128,
        128,
    )
    assert png_dimensions(WEBSITE / "assets" / "apple-touch-icon.png") == (
        180,
        180,
    )
    assert png_dimensions(WEBSITE / "assets" / "dashboard-ui-mobile.png") == (
        390,
        844,
    )
    assert png_dimensions(WEBSITE / "assets" / "native-dashboard.png") == (
        2400,
        1600,
    )
    assert png_dimensions(WEBSITE / "assets" / "social-preview.png") == (
        1280,
        640,
    )


def test_design_system_accessibility_and_responsive_contracts() -> None:
    html, _ = parse_page()
    css = (WEBSITE / "styles.css").read_text(encoding="utf-8")

    for token in (
        "--canvas: #faf7ef",
        "--ink: #19233b",
        "--muted: #646d80",
        "--cobalt: #3156a3",
        "--yellow: #f7d86a",
        "--coral: #f38b72",
        "--coral-ink: #9c4737",
    ):
        assert token in css

    assert '<details class="mobile-nav">' in html
    assert "min-height: 44px" in css
    assert "outline: 3px solid var(--cobalt-dark)" in css
    assert "-webkit-backdrop-filter" in css
    assert "scroll-margin-top" in css
    assert "@media (max-width: 920px)" in css
    assert "@media (max-width: 700px)" in css
    assert "@media (max-width: 390px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "-webkit-mask-image:" in css
    assert re.search(r"(?m)^\s*mask-image\s*:", css)
    assert "overflow-x: hidden" not in css
    assert "overflow-x: clip" not in css
    assert "height: auto" in css
    assert "text-wrap: balance" in css
    assert "text-wrap: pretty" in css
    assert "蛙仔也不是<br>" not in html


def test_release_and_privacy_pages_match_actual_project_state() -> None:
    changelog, _ = parse_page("changelog.html")
    privacy, _ = parse_page("privacy.html")

    assert "Developer ID 签名与 Apple 公证" in changelog
    assert "一个“收好桌面”按钮" in changelog
    assert "froganize.com" in changelog
    assert "源码公开测试版不是已经签名、公证的正式安装包" in changelog
    assert "不读取、索引或上传文件内容" in privacy
    assert "只有你主动点击“收好桌面”" in privacy
    assert "整理日历可以回看每个批次" in privacy
    assert "127.0.0.1" in privacy
    assert "不会永久删除或清空废纸篓" in privacy


def test_github_pages_workflow_deploys_only_static_website() -> None:
    workflow = (
        PROJECT_ROOT / ".github" / "workflows" / "pages.yml"
    ).read_text(encoding="utf-8")

    assert "actions/configure-pages@v5" in workflow
    assert "actions/upload-pages-artifact@v4" in workflow
    assert "actions/deploy-pages@v4" in workflow
    assert "enablement: true" in workflow
    assert "path: website" in workflow
    assert "pages: write" in workflow
    assert "id-token: write" in workflow
    assert "dist/" not in workflow
    assert ".app" not in workflow
