"""
visual/generator.py — Visual scene generation for YouTube Shorts

Fixes from v1:
  - Word-boundary keyword matching  ->  "ai" no longer matches inside "claim"
  - Per-scene query extraction      ->  each scene gets a unique, relevant query
  - Scene-type awareness            ->  hook / body / CTA get different visuals
  - Empty scene fallback            ->  scenes with no text reuse topic visuals
"""

import os, re, random
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
import requests
from loguru import logger
from dotenv import load_dotenv
load_dotenv()

OUTPUT_DIR    = Path(os.getenv("OUTPUT_DIR", "./output"))
IMAGES_DIR    = OUTPUT_DIR / "images"
VISUAL_ENGINE = os.getenv("VISUAL_ENGINE", "mixed")
PIXABAY_KEY   = os.getenv("PIXABAY_API_KEY", "")
PEXELS_KEY    = os.getenv("PEXELS_API_KEY", "")
UNSPLASH_KEY  = os.getenv("UNSPLASH_ACCESS_KEY", "")
SD_HOST       = os.getenv("SD_HOST", "http://localhost:7860")
SD_ENABLED    = os.getenv("SD_ENABLED", "false").lower() == "true"

IMAGES_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────
# DATA CLASSES
# ──────────────────────────────────────────────

@dataclass
class VisualScene:
    index: int
    description: str
    prompt: str
    image_path: str = ""
    source: str = ""
    duration: float = 4.0


@dataclass
class VisualPlan:
    topic: str
    scenes: List[VisualScene] = field(default_factory=list)

    def all_ready(self) -> bool:
        return all(bool(s.image_path) for s in self.scenes)


# ──────────────────────────────────────────────
# KEYWORD MATCHING
# Uses word boundaries so "ai" never matches
# inside "claim", "rain", "paid", etc.
# ──────────────────────────────────────────────

def _has_word(text: str, *words: str) -> bool:
    for w in words:
        if re.search(r'\b' + re.escape(w) + r'\b', text, re.IGNORECASE):
            return True
    return False


# ──────────────────────────────────────────────
# TOPIC CATEGORY DETECTION
# ──────────────────────────────────────────────

def detect_category(topic: str) -> str:
    t = topic.lower()

    if _has_word(t, "trump", "biden", "harris", "election", "democrat",
                  "republican", "congress", "senate", "president", "parliament",
                  "politician", "political", "vote", "protest", "rally", "nbc",
                  "interview", "rigged", "campaign"):
        return "politics"

    if _has_word(t, "shark", "whale", "dolphin", "ocean", "sea", "marine",
                  "coral", "underwater", "fish", "reef", "deep sea"):
        return "ocean"

    if _has_word(t, "space", "nasa", "planet", "asteroid", "galaxy",
                  "telescope", "moon", "mars", "rocket", "astronaut"):
        return "space"

    if _has_word(t, "chatgpt", "openai", "anthropic", "llm", "machine learning",
                  "neural network", "deep learning", "automation"):
        return "ai_tech"

    # "ai" checked as whole word ONLY after the compound checks above
    if _has_word(t, "ai") and not _has_word(t, "rain", "claim", "train", "pair"):
        return "ai_tech"

    if _has_word(t, "python", "javascript", "software", "developer", "code",
                  "programming", "app", "startup", "tech", "computer",
                  "smartphone", "iphone", "android"):
        return "technology"

    if _has_word(t, "health", "medical", "doctor", "cancer", "brain",
                  "heart", "disease", "vaccine", "hospital", "surgery",
                  "fitness", "diet"):
        return "health"

    if _has_word(t, "science", "scientist", "research", "study", "discovery",
                  "experiment", "biology", "chemistry", "physics", "dna"):
        return "science"

    if _has_word(t, "money", "stock", "market", "bitcoin", "crypto",
                  "economy", "invest", "billionaire", "million", "bank",
                  "finance", "wealth"):
        return "finance"

    if _has_word(t, "climate", "environment", "flood", "earthquake",
                  "wildfire", "hurricane", "disaster", "pollution"):
        return "environment"

    if _has_word(t, "movie", "film", "actor", "actress", "hollywood",
                  "netflix", "series", "show", "celebrity", "music",
                  "singer", "album", "concert"):
        return "entertainment"

    if _has_word(t, "food", "recipe", "cook", "restaurant", "chef",
                  "nutrition", "meal"):
        return "food"

    if _has_word(t, "sport", "football", "soccer", "basketball", "nba",
                  "cricket", "tennis", "athlete", "champion", "olympic",
                  "match", "tournament"):
        return "sports"

    if _has_word(t, "history", "ancient", "war", "empire", "king", "queen",
                  "civilization", "century", "battle", "egypt", "rome"):
        return "history"

    if _has_word(t, "animal", "lion", "tiger", "elephant", "nature",
                  "wildlife", "jungle", "forest", "bird"):
        return "nature"

    if _has_word(t, "psychology", "mind", "behavior", "habit",
                  "memory", "emotion", "anxiety", "motivation"):
        return "psychology"

    return "general"


# ──────────────────────────────────────────────
# CATEGORY -> VISUAL QUERY POOLS
# Each category has 8 distinct queries.
# Scenes rotate through so no two scenes are identical.
# ──────────────────────────────────────────────

CATEGORY_QUERIES: Dict[str, List[str]] = {
    "politics": [
        "politician speaking at podium",
        "news broadcast studio breaking news",
        "microphone press conference reporters",
        "television news anchor desk",
        "government building capitol exterior",
        "crowd political rally protest",
        "newspaper headline printing press",
        "debate stage spotlight dramatic",
    ],
    "ocean": [
        "great white shark underwater close",
        "deep ocean dark blue water",
        "coral reef tropical colorful fish",
        "ocean surface waves sunlight",
        "deep sea mysterious dark creature",
        "scuba diver underwater exploring",
        "whale breach ocean spray",
        "underwater cave dark light rays",
    ],
    "space": [
        "galaxy stars milky way dark",
        "rocket launch fire dramatic",
        "astronaut space suit floating",
        "planet earth from space orbit",
        "telescope observatory night sky",
        "mars surface red rocky",
        "asteroid space rocks close",
        "space station orbit earth",
    ],
    "ai_tech": [
        "artificial intelligence neural network glow",
        "robot humanoid technology futuristic",
        "computer brain circuit board close",
        "data visualization glowing screens",
        "future technology hologram blue",
        "code screen programming dark room",
        "machine learning diagram visual",
        "digital brain technology concept",
    ],
    "technology": [
        "laptop computer modern workspace",
        "smartphone close up screen",
        "developer coding multiple screens",
        "circuit board technology close",
        "modern startup office team",
        "server data center blue light",
        "phone app user interface",
        "person working technology focused",
    ],
    "health": [
        "doctor hospital professional white coat",
        "brain scan mri medical",
        "person running fitness exercise",
        "healthy food bowl colorful",
        "laboratory medical research scientist",
        "heart anatomy red medical",
        "meditation calm mindfulness person",
        "pills medicine pharmacy",
    ],
    "science": [
        "scientist laboratory experiment",
        "microscope lab close up",
        "dna helix biology visualization",
        "chemistry laboratory colorful flask",
        "physics experiment electricity",
        "research paper writing scientist",
        "telescope discovery night",
        "breakthrough discovery celebration science",
    ],
    "finance": [
        "stock market trading screens green red",
        "gold coins wealth stacked",
        "business chart growth arrow",
        "bitcoin cryptocurrency digital gold",
        "bank vault finance",
        "businessman investor suit confident",
        "economy financial chart analysis",
        "money bills cash close",
    ],
    "environment": [
        "wildfire forest burning dramatic",
        "flood disaster water street",
        "climate earth globe warming",
        "factory pollution smoke sky",
        "glacier melting arctic ice",
        "hurricane satellite aerial view",
        "solar panels clean energy field",
        "deforestation trees cut stumps",
    ],
    "entertainment": [
        "cinema movie screen audience",
        "concert crowd hands up music",
        "actor stage performance spotlight",
        "film production camera crew",
        "red carpet event bright lights",
        "streaming video laptop couch",
        "music studio recording headphones",
        "director film set clapperboard",
    ],
    "food": [
        "gourmet food plating restaurant",
        "chef cooking professional kitchen",
        "fresh vegetables colorful market",
        "baking bread golden oven",
        "exotic spices cuisine colorful",
        "food photography close macro",
        "street food market crowd",
        "dessert chocolate close up",
    ],
    "sports": [
        "stadium crowd cheering night",
        "athlete sprinting track action",
        "football soccer match aerial",
        "basketball slam dunk court",
        "tennis serve dramatic action",
        "cricket stadium crowd match",
        "trophy champion celebration",
        "sports training gym intense",
    ],
    "history": [
        "ancient ruins columns architecture",
        "old manuscript parchment historical",
        "museum artifact display ancient",
        "battlefield landscape historical",
        "egypt pyramids desert dramatic",
        "roman colosseum ancient stones",
        "medieval castle fortress stone",
        "vintage photograph historical sepia",
    ],
    "nature": [
        "lion roaring savanna dramatic",
        "elephant walking africa sunset",
        "forest sunlight trees rays",
        "waterfall dramatic nature",
        "birds flock sky sunset",
        "tiger stalking jungle",
        "mountain peak dramatic sky",
        "wildlife close up animal eye",
    ],
    "psychology": [
        "human brain illuminated thinking",
        "meditation person calm peaceful",
        "face expression emotion close",
        "crowd behavior people walking",
        "motivation person success arms up",
        "stress person thinking overwhelmed",
        "habit routine morning person",
        "therapy calm peaceful room",
    ],
    "general": [
        "dramatic spotlight concept",
        "abstract idea visualization",
        "person thinking lightbulb",
        "world map global connection",
        "city skyline modern night",
        "light rays dramatic dark",
        "crowd people diverse city",
        "future concept minimal clean",
    ],
}

HOOK_QUERIES: Dict[str, str] = {
    "politics":      "breaking news studio dramatic red",
    "ocean":         "shark ocean dramatic close underwater",
    "space":         "galaxy explosion dramatic colors",
    "ai_tech":       "ai robot futuristic dramatic glow",
    "technology":    "technology future dramatic neon",
    "health":        "doctor dramatic lighting close",
    "science":       "laboratory dramatic science close",
    "finance":       "stock market crash dramatic screens",
    "environment":   "wildfire dramatic orange sky",
    "entertainment": "cinema spotlight dramatic stage",
    "sports":        "stadium crowd night dramatic lights",
    "history":       "ancient ruins dramatic light",
    "nature":        "wildlife dramatic animal close",
    "psychology":    "mind brain dramatic concept glow",
    "general":       "dramatic reveal spotlight person",
}

CTA_QUERIES = [
    "person excited watching phone social media",
    "thumbs up like approval close up",
    "smartphone notification bell alert",
    "people celebrating success crowd happy",
    "person scrolling phone engaged",
    "subscribe button red close up",
]


def get_scene_queries(category: str, num_scenes: int) -> List[str]:
    """
    Return a list of scene-count unique queries, rotated through the pool.
    """
    pool = CATEGORY_QUERIES.get(category, CATEGORY_QUERIES["general"])
    shuffled = pool.copy()
    random.shuffle(shuffled)
    while len(shuffled) < num_scenes:
        extra = pool.copy()
        random.shuffle(extra)
        shuffled.extend(extra)
    return shuffled[:num_scenes]


# ──────────────────────────────────────────────
# SCENE PLAN BUILDER
# Assigns a unique, relevant query to every scene.
# ──────────────────────────────────────────────

def _scene_type(idx: int, total: int, description: str) -> str:
    d = description.lower()
    cta_words = ["follow", "subscribe", "like", "share", "comment",
                 "thumbs", "notification", "bell", "hit that"]
    if idx == 0:
        return "hook"
    if any(w in d for w in cta_words) or idx >= total - 2:
        return "cta"
    return "body"


def generate_scene_plan(topic: str, script: Dict, num_scenes: int = 8) -> List[Dict]:
    """
    Build the full scene plan: one unique search query per scene.
    """
    full_script = script.get("full_script", "")
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', full_script.strip()) if s.strip()]
    actual_scenes = max(4, min(num_scenes, max(len(sentences) + 1, num_scenes)))

    category = detect_category(topic)
    base_queries = get_scene_queries(category, actual_scenes)

    plan = []
    for i in range(actual_scenes):
        desc = sentences[i] if i < len(sentences) else topic
        stype = _scene_type(i, actual_scenes, desc)

        if stype == "hook":
            query = HOOK_QUERIES.get(category, HOOK_QUERIES["general"])
        elif stype == "cta":
            query = CTA_QUERIES[i % len(CTA_QUERIES)]
        else:
            query = base_queries[i]

        plan.append({
            "index": i,
            "description": desc,
            "prompt": _build_sd_prompt(topic, desc, i),
            "search_query": query,
            "scene_type": stype,
            "category": category,
        })

        logger.debug(
            f"[scene_plan] {i:02d} [{stype:5s}] "
            f"query='{query}' | {desc[:55]}"
        )

    return plan


def _build_sd_prompt(topic: str, context: str, scene_index: int) -> str:
    styles = [
        "dramatic lighting, photorealistic, 8k, cinematic, vertical 9:16",
        "professional photography, sharp focus, bokeh, vertical portrait",
        "vibrant colors, high contrast, editorial, vertical",
        "documentary style, natural lighting, authentic, vertical",
    ]
    style = styles[scene_index % len(styles)]
    t = " ".join(topic.split()[:4])
    if scene_index == 0:
        return f"{t}, dramatic hero shot, {style}, ultra-detailed"
    return f"{t}, {context[:40]}, {style}"


# ──────────────────────────────────────────────
# STOCK IMAGE SOURCES
# ──────────────────────────────────────────────

class PixabaySource:
    BASE = "https://pixabay.com/api/"

    def search(self, query: str, count: int = 3) -> List[str]:
        if not PIXABAY_KEY:
            return []
        try:
            r = requests.get(self.BASE, timeout=10, params={
                "key": PIXABAY_KEY, "q": query,
                "image_type": "photo", "orientation": "vertical",
                "min_width": 720, "min_height": 1280,
                "per_page": count, "safesearch": "true", "order": "popular",
            })
            r.raise_for_status()
            return [
                h.get("largeImageURL") or h.get("webformatURL", "")
                for h in r.json().get("hits", [])
                if h.get("largeImageURL") or h.get("webformatURL")
            ]
        except Exception as e:
            logger.warning(f"[pixabay] '{query}': {e}")
            return []


class PexelsSource:
    BASE = "https://api.pexels.com/v1"

    def search(self, query: str, count: int = 3) -> List[str]:
        if not PEXELS_KEY:
            return []
        try:
            r = requests.get(
                f"{self.BASE}/search",
                headers={"Authorization": PEXELS_KEY},
                params={"query": query, "orientation": "portrait",
                        "size": "large", "per_page": count},
                timeout=10,
            )
            r.raise_for_status()
            return [p["src"]["large2x"] for p in r.json().get("photos", []) if p.get("src")]
        except Exception as e:
            logger.warning(f"[pexels] '{query}': {e}")
            return []


class UnsplashSource:
    BASE = "https://api.unsplash.com"

    def search(self, query: str, count: int = 3) -> List[str]:
        if not UNSPLASH_KEY:
            return []
        try:
            r = requests.get(
                f"{self.BASE}/search/photos",
                params={"query": query, "orientation": "portrait",
                        "per_page": count, "client_id": UNSPLASH_KEY},
                timeout=10,
            )
            r.raise_for_status()
            return [
                item.get("urls", {}).get("regular", "")
                for item in r.json().get("results", [])
                if item.get("urls", {}).get("regular")
            ]
        except Exception as e:
            logger.warning(f"[unsplash] '{query}': {e}")
            return []


class StockAggregator:
    def __init__(self):
        self.sources = [UnsplashSource() ,PixabaySource(), PexelsSource() ]

    def search(self, query: str, category: str = "general") -> Optional[str]:
        # Try exact query
        for src in self.sources:
            urls = src.search(query, count=3)
            if urls:
                return random.choice(urls)

        # Broaden: first 2 words only
        short = " ".join(query.split()[:2])
        if short != query:
            for src in self.sources:
                urls = src.search(short, count=3)
                if urls:
                    return random.choice(urls)

        # Category fallback
        fallback = random.choice(CATEGORY_QUERIES.get(category, CATEGORY_QUERIES["general"]))
        for src in self.sources:
            urls = src.search(fallback, count=3)
            if urls:
                return random.choice(urls)

        return None


# ──────────────────────────────────────────────
# STABLE DIFFUSION (LOCAL)
# ──────────────────────────────────────────────

class StableDiffusionSource:
    BASE = f"{SD_HOST}/sdapi/v1"

    def is_available(self) -> bool:
        try:
            return requests.get(f"{SD_HOST}/", timeout=3).status_code == 200
        except Exception:
            return False

    def generate(self, prompt: str, output_path: str,
                 width: int = 576, height: int = 1024) -> bool:
        import base64
        try:
            r = requests.post(f"{self.BASE}/txt2img", timeout=300, json={
                "prompt": prompt,
                "negative_prompt": "blurry, low quality, distorted, text, watermark, nsfw",
                "steps": 20, "width": width, "height": height,
                "cfg_scale": 7.0, "sampler_name": "DPM++ 2M Karras",
            })
            r.raise_for_status()
            imgs = r.json().get("images", [])
            if not imgs:
                return False
            with open(output_path, "wb") as f:
                f.write(base64.b64decode(imgs[0]))
            return True
        except Exception as e:
            logger.error(f"[sd] {e}")
            return False


# ──────────────────────────────────────────────
# GRADIENT FALLBACK
# ──────────────────────────────────────────────

GRADIENTS = [
    ("#0a0a2e", "#1a0a4e"), ("#0f2027", "#2c5364"),
    ("#1a0505", "#3d0000"), ("#051a05", "#0a3d0a"),
    ("#0f0c29", "#24243e"), ("#141e30", "#243b55"),
    ("#1a1400", "#3d3200"), ("#051a1a", "#0a3d3d"),
]

def create_gradient_image(path: str, w: int = 1080, h: int = 1920, idx: int = 0) -> bool:
    try:
        from PIL import Image, ImageDraw
        top_hex, bot_hex = GRADIENTS[idx % len(GRADIENTS)]
        def h2r(s):
            s = s.lstrip("#")
            return tuple(int(s[i:i+2], 16) for i in (0, 2, 4))
        top, bot = h2r(top_hex), h2r(bot_hex)
        img = Image.new("RGB", (w, h))
        draw = ImageDraw.Draw(img)
        for y in range(h):
            t = y / h
            draw.line([(0,y),(w,y)], fill=tuple(int(top[c]+(bot[c]-top[c])*t) for c in range(3)))
        img.save(path, "JPEG", quality=90)
        return True
    except Exception as e:
        logger.error(f"[gradient] {e}")
        return False


# ──────────────────────────────────────────────
# IMAGE DOWNLOADER + RESIZER
# ──────────────────────────────────────────────

def download_and_resize(url: str, out: str, tw: int = 1080, th: int = 1920) -> bool:
    try:
        r = requests.get(url, headers={"User-Agent": "YTShortsBot/1.0"},
                         timeout=30, stream=True)
        r.raise_for_status()
        tmp = out + ".tmp"
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        _crop_vertical(tmp, out, tw, th)
        os.remove(tmp)
        return True
    except Exception as e:
        logger.warning(f"[download] {url[:60]} -> {e}")
        return False


def _crop_vertical(src: str, dst: str, tw: int = 1080, th: int = 1920):
    from PIL import Image
    img = Image.open(src).convert("RGB")
    ow, oh = img.size
    nw, nh = (int(ow*th/oh), th) if ow/oh > tw/th else (tw, int(oh*tw/ow))
    img = img.resize((nw, nh), Image.LANCZOS)
    l, t = (nw-tw)//2, (nh-th)//2
    img.crop((l, t, l+tw, t+th)).save(dst, "JPEG", quality=88)


# ──────────────────────────────────────────────
# MAIN VISUAL GENERATOR
# ──────────────────────────────────────────────

class VisualGenerator:
    def __init__(self):
        self.stock = StockAggregator()
        self.sd    = StableDiffusionSource()
        self.strategy = VISUAL_ENGINE.lower()
        self._last_source = "unknown"

    def generate_for_script(self, topic: str, script: Dict,
                             run_id: str, num_scenes: int = 8) -> VisualPlan:
        plan_data = generate_scene_plan(topic, script, num_scenes)
        plan = VisualPlan(topic=topic)
        scene_dir = IMAGES_DIR / run_id
        scene_dir.mkdir(parents=True, exist_ok=True)

        for sp in plan_data:
            out_path = str(scene_dir / f"scene_{sp['index']:02d}.jpg")
            scene = VisualScene(
                index=sp["index"], description=sp["description"], prompt=sp["prompt"]
            )
            ok = self._fetch(sp["prompt"], sp["search_query"],
                              sp["category"], out_path, sp["index"])
            if ok:
                scene.image_path = out_path
                scene.source = self._last_source
            else:
                if create_gradient_image(out_path, idx=sp["index"]):
                    scene.image_path = out_path
                    scene.source = "gradient"
            plan.scenes.append(scene)

        ready = sum(1 for s in plan.scenes if s.image_path)
        cat = detect_category(topic)
        logger.info(f"[visual] {ready}/{len(plan.scenes)} scenes ready (category: {cat})")
        return plan

    def _fetch(self, sd_prompt: str, query: str, category: str,
                out: str, idx: int) -> bool:
        if idx == 0 and SD_ENABLED and self.sd.is_available():
            if self.sd.generate(sd_prompt, out):
                self._last_source = "stable_diffusion"
                return True
        url = self.stock.search(query, category)
        if url and download_and_resize(url, out):
            self._last_source = "stock"
            return True
        return False


# ──────────────────────────────────────────────
# QUICK TEST
# ──────────────────────────────────────────────

if __name__ == "__main__":
    topics = [
        "Trump abruptly ends NBC interview after clash over rigged election claim",
        "Scientists discover deep sea creature 4000 metres below surface",
        "NASA finds liquid water on Europa moon of Jupiter",
        "New AI model beats humans at every benchmark",
        "Rare great white shark filmed in Mediterranean Sea",
    ]
    print("=== Category Detection ===")
    for t in topics:
        print(f"  {detect_category(t):15s}  {t[:65]}")

    print("\n=== Scene Plan (Trump topic) ===")
    script = {
        "full_script": (
            "Did you know Trump abruptly ended an NBC interview? "
            "He accused NBC of being biased against Republicans. "
            "He stormed out after being questioned about election claims. "
            "This is not the first time he has walked out of an interview. "
            "Experts say this reflects growing media tensions. "
            "Follow for more political updates you won't see elsewhere."
        )
    }
    plan = generate_scene_plan(
        "Trump abruptly ends NBC interview after clash over rigged election",
        script, num_scenes=8
    )
    for p in plan:
        print(f"  {p['index']:02d} [{p['scene_type']:5s}] {p['search_query']:45s} | {p['description'][:50]}")