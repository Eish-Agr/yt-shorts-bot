"""
thumbnail/generator.py — YouTube Shorts thumbnail generator
Creates eye-catching 1280x720 thumbnails using Pillow.
No external tools required.
"""
import os, re, math, textwrap, urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from loguru import logger
from dotenv import load_dotenv
load_dotenv()

THUMB_W    = int(os.getenv("THUMBNAIL_WIDTH",  "1280"))
THUMB_H    = int(os.getenv("THUMBNAIL_HEIGHT", "720"))
FONT_SIZE  = int(os.getenv("THUMBNAIL_FONT_SIZE", "72"))
FONT_PATH  = os.getenv("FONT_PATH", "./assets/fonts/Montserrat-Bold.ttf")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))
THUMB_DIR  = OUTPUT_DIR / "thumbnails"
THUMB_DIR.mkdir(parents=True, exist_ok=True)

# Font download URLs (fallback if local font missing)
FONT_URLS = {
    "Montserrat-Bold.ttf": (
        "https://github.com/google/fonts/raw/main/ofl/montserrat/static/"
        "Montserrat-Bold.ttf"
    ),
    "Roboto-Black.ttf": (
        "https://github.com/google/fonts/raw/main/ofl/roboto/static/"
        "Roboto-Black.ttf"
    ),
}

# Design themes: (bg_gradient_top, bg_gradient_bottom, text_color, accent_color)
THEMES = {
    "dark_blue":  ("#0a0a2e", "#1a0a4e", "#FFFFFF", "#00d4ff"),
    "dark_red":   ("#1a0505", "#3d0000", "#FFFFFF", "#ff4444"),
    "dark_green": ("#051a05", "#0a3d0a", "#FFFFFF", "#44ff88"),
    "dark_gold":  ("#1a1400", "#3d3200", "#FFFFFF", "#ffd700"),
    "dark_purple":("#0e0520", "#2d1060", "#FFFFFF", "#cc44ff"),
    "dark_teal":  ("#051a1a", "#0a3d3d", "#FFFFFF", "#00ffcc"),
}


# ──────────────────────────────────────────────
# FONT MANAGEMENT
# ──────────────────────────────────────────────

def ensure_font(font_path: str) -> str:
    """Ensure font exists; download if needed."""
    if os.path.exists(font_path):
        return font_path

    font_dir = Path(font_path).parent
    font_dir.mkdir(parents=True, exist_ok=True)
    font_name = Path(font_path).name

    if font_name in FONT_URLS:
        logger.info(f"[thumbnail] Downloading font: {font_name}")
        try:
            urllib.request.urlretrieve(FONT_URLS[font_name], font_path)
            logger.info(f"[thumbnail] Font downloaded: {font_path}")
            return font_path
        except Exception as e:
            logger.warning(f"[thumbnail] Font download failed: {e}")

    # Try system font as last resort
    system_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
    ]
    for sf in system_fonts:
        if os.path.exists(sf):
            logger.info(f"[thumbnail] Using system font: {sf}")
            return sf

    return ""  # Will use PIL default


def get_pil_font(font_path: str, size: int):
    """Get PIL ImageFont, with fallback."""
    from PIL import ImageFont
    fp = ensure_font(font_path)
    if fp:
        try:
            return ImageFont.truetype(fp, size)
        except Exception as e:
            logger.warning(f"[thumbnail] Font load error: {e}")
    return ImageFont.load_default()


# ──────────────────────────────────────────────
# TEXT UTILITIES
# ──────────────────────────────────────────────

def generate_thumbnail_text(topic: str, script_hook: str = "") -> Tuple[str, str]:
    """
    Generate main title text and subtitle for thumbnail.
    Returns (main_text, subtitle)
    """
    # Clean topic for display
    topic_clean = re.sub(r'[^\w\s\-!?]', '', topic)
    # Truncate
    words = topic_clean.split()

    if len(words) <= 5:
        main = topic_clean.upper()
        sub = "MIND-BLOWING FACTS 🤯"
    elif len(words) <= 8:
        main = " ".join(words[:5]).upper()
        sub = " ".join(words[5:]).upper() + " 😱"
    else:
        # Create punchy short title
        key_words = [w for w in words if len(w) > 3][:4]
        main = " ".join(key_words).upper()
        sub = "YOU WON'T BELIEVE THIS"

    # Add emoji punch
    if "?" not in main and "!" not in main:
        main += "!"

    return main, sub


def wrap_text_to_width(text: str, font, max_width: int,
                        draw) -> List[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# ──────────────────────────────────────────────
# THUMBNAIL DRAWING
# ──────────────────────────────────────────────

def create_gradient_bg(draw, width: int, height: int,
                        top_hex: str, bot_hex: str):
    """Draw a vertical gradient background."""
    def hex_rgb(h: str) -> Tuple[int, int, int]:
        h = h.lstrip("#")
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    top = hex_rgb(top_hex)
    bot = hex_rgb(bot_hex)
    for y in range(height):
        t = y / height
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))


def add_image_bg(img, source_image_path: str,
                 alpha: float = 0.35):
    """Blend a scene image into the thumbnail background."""
    from PIL import Image
    try:
        scene = Image.open(source_image_path).convert("RGBA")
        scene = scene.resize((THUMB_W, THUMB_H), Image.LANCZOS)
        # Darken
        overlay = Image.new("RGBA", (THUMB_W, THUMB_H), (0, 0, 0, 180))
        blended = Image.alpha_composite(scene, overlay)
        img.paste(blended.convert("RGB"), (0, 0))
    except Exception as e:
        logger.warning(f"[thumbnail] Background blend failed: {e}")


def draw_text_with_shadow(draw, text: str, x: int, y: int,
                           font, fill: str, shadow_offset: int = 4,
                           shadow_alpha: int = 180):
    """Draw text with drop shadow for readability."""
    # Shadow
    draw.text((x + shadow_offset, y + shadow_offset), text,
              font=font, fill=(0, 0, 0))
    # Main text
    draw.text((x, y), text, font=font, fill=fill)


def draw_outlined_text(draw, text: str, x: int, y: int, font,
                        fill: str, outline_color: str = "black",
                        outline_width: int = 3):
    """Draw text with thick outline for contrast on any background."""
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text,
                          font=font, fill=outline_color)
    draw.text((x, y), text, font=font, fill=fill)


# ──────────────────────────────────────────────
# MAIN THUMBNAIL GENERATOR
# ──────────────────────────────────────────────

class ThumbnailGenerator:
    def __init__(self):
        self.font_path = FONT_PATH

    def generate(
        self,
        topic: str,
        run_id: str,
        script: Optional[Dict] = None,
        scene_image_path: Optional[str] = None,
        theme: str = "auto",
    ) -> Optional[str]:
        """
        Generate a YouTube thumbnail.
        Args:
            topic: Video topic
            run_id: Unique run identifier
            script: Script dict (for hook text)
            scene_image_path: Optional background image from video scenes
            theme: Color theme name or 'auto'
        Returns: Path to thumbnail file
        """
        from PIL import Image, ImageDraw, ImageFilter
        import random

        output_path = str(THUMB_DIR / f"{run_id}_thumb.jpg")

        # Select theme
        if theme == "auto":
            theme_name = random.choice(list(THEMES.keys()))
        else:
            theme_name = theme
        top_c, bot_c, text_c, accent_c = THEMES.get(theme_name,
                                                      THEMES["dark_blue"])

        # Create base image
        img = Image.new("RGB", (THUMB_W, THUMB_H))
        draw = ImageDraw.Draw(img)

        # Background
        if scene_image_path and os.path.exists(scene_image_path):
            add_image_bg(img, scene_image_path, alpha=0.4)
        else:
            create_gradient_bg(draw, THUMB_W, THUMB_H, top_c, bot_c)

        # Add subtle vignette
        self._add_vignette(img)

        # Reload draw after modifications
        draw = ImageDraw.Draw(img)

        # Generate text
        hook = script.get("hook", "") if script else ""
        main_text, sub_text = generate_thumbnail_text(topic, hook)

        # Fonts
        font_big   = get_pil_font(self.font_path, FONT_SIZE)
        font_med   = get_pil_font(self.font_path, int(FONT_SIZE * 0.55))
        font_small = get_pil_font(self.font_path, int(FONT_SIZE * 0.38))

        # Wrap main text
        margin = 80
        max_text_w = THUMB_W - (2 * margin)
        main_lines = wrap_text_to_width(main_text, font_big, max_text_w, draw)

        # Calculate total text height
        line_height = FONT_SIZE + 12
        total_text_h = len(main_lines) * line_height
        start_y = int(THUMB_H * 0.25)

        # Draw accent bar
        accent_h = 8
        draw.rectangle(
            [margin, start_y - 25, margin + 120, start_y - 25 + accent_h],
            fill=accent_c
        )

        # Draw main text lines
        for i, line in enumerate(main_lines):
            bbox = draw.textbbox((0, 0), line, font=font_big)
            text_w = bbox[2] - bbox[0]
            x = (THUMB_W - text_w) // 2
            y = start_y + i * line_height
            draw_outlined_text(draw, line, x, y, font_big,
                                fill=text_c, outline_color="black",
                                outline_width=4)

        # Draw subtitle
        sub_y = start_y + total_text_h + 20
        bbox = draw.textbbox((0, 0), sub_text, font=font_med)
        sub_w = bbox[2] - bbox[0]
        sub_x = (THUMB_W - sub_w) // 2
        draw_outlined_text(draw, sub_text, sub_x, sub_y, font_med,
                            fill=accent_c, outline_color="black",
                            outline_width=3)

        # Bottom label: "#shorts" branding
        shorts_text = "#SHORTS"
        bbox = draw.textbbox((0, 0), shorts_text, font=font_small)
        sw = bbox[2] - bbox[0]
        draw.text(
            (THUMB_W - sw - margin, THUMB_H - 60),
            shorts_text, font=font_small,
            fill=(200, 200, 200)
        )

        # Draw decorative element (emoji-like visual)
        self._add_visual_element(draw, img, topic, accent_c)

        # Save
        img.save(output_path, "JPEG", quality=95)
        logger.info(f"[thumbnail] Saved: {output_path}")
        return output_path

    def _add_vignette(self, img):
        """Add dark vignette border for depth."""
        from PIL import Image, ImageFilter, ImageDraw
        vignette = Image.new("RGB", (THUMB_W, THUMB_H), 0)
        v_draw = ImageDraw.Draw(vignette)
        max_r = math.sqrt((THUMB_W/2)**2 + (THUMB_H/2)**2)
        for r in range(int(max_r), 0, -2):
            alpha = int(220 * (r / max_r) ** 2)
            if alpha > 200:
                color = (0, 0, 0)
                x0 = THUMB_W // 2 - r
                y0 = THUMB_H // 2 - r
                x1 = THUMB_W // 2 + r
                y1 = THUMB_H // 2 + r
                v_draw.ellipse([x0, y0, x1, y1], outline=color)
        img.paste(
            Image.blend(img, vignette, alpha=0.25),
            (0, 0)
        )

    def _add_visual_element(self, draw, img, topic: str, accent_color: str):
        """Add a topic-appropriate visual element."""
        from PIL import Image, ImageDraw
        # Simple attention-grabbing geometric element
        # Top-right corner: angled accent stripe
        pts = [
            (THUMB_W - 200, 0),
            (THUMB_W, 0),
            (THUMB_W, 150),
        ]
        r, g, b = _hex_to_rgb(accent_color)
        draw.polygon(pts, fill=(r, g, b, 180))

    def generate_ab_variants(self, topic: str, run_id: str,
                              script: Optional[Dict] = None,
                              scene_image_path: Optional[str] = None) -> List[str]:
        """Generate A and B thumbnail variants for A/B testing."""
        variants = []
        themes = ["dark_blue", "dark_red"]
        for i, theme in enumerate(themes):
            var_id = f"{run_id}_v{chr(65+i)}"
            path = self.generate(topic, var_id, script,
                                  scene_image_path, theme=theme)
            if path:
                variants.append(path)
        return variants


def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


from typing import Dict, Tuple

if __name__ == "__main__":
    gen = ThumbnailGenerator()
    path = gen.generate(
        "Scientists Discover Ocean Bacteria That Eats Plastic",
        run_id="test_thumb_001",
        script={"hook": "Did you know the ocean is fighting back against plastic?"},
    )
    print(f"Thumbnail: {path}")
