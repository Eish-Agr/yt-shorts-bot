"""
script/generator.py — YouTube Shorts script generator
Uses local Ollama (Mistral/LLaMA) with template fallback.
Generates 30s, 60s, and 90s script variants.
"""
import os, re, json, textwrap
from typing import Optional, Dict, Tuple, List, Any
from loguru import logger
from dotenv import load_dotenv
load_dotenv()

OLLAMA_HOST  = os.getenv("OLLAMA_HOST",  "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
USE_FALLBACK = os.getenv("USE_TEMPLATE_FALLBACK", "true").lower() == "true"

# Words per second for pacing (natural speech ~140 wpm = 2.33 w/s)
WPS = 2.33


# ──────────────────────────────────────────────
# PROMPT TEMPLATES FOR EACH DURATION
# ──────────────────────────────────────────────

SYSTEM_PROMPT = """You are a world-class YouTube Shorts scriptwriter.
You write punchy, engaging scripts that go viral.
Rules:
- NEVER use filler words (um, uh, so, basically)
- Start with a jaw-dropping hook (first 3 seconds must HOOK)
- Use short punchy sentences (max 12 words each)
- Build curiosity with open loops ("Here's why this changes everything...")
- End with a strong CTA that creates urgency
- Write ONLY the voiceover text — no stage directions, no [music], no [cut]
- Use conversational language as if talking to a friend
- Include surprising/counterintuitive facts for retention
"""

def _make_prompt(topic: str, duration: int, hook_style: str = "question") -> str:
    word_target = int(duration * WPS)
    hook_examples = {
        "question":    f"Did you know that [shocking fact about {topic}]?",
        "statement":   f"[Bold claim about {topic}] — and scientists just proved it.",
        "number":      f"[Number] things about {topic} that will blow your mind.",
        "challenge":   f"Most people get this wrong about {topic}. Do you?",
        "story":       f"I had no idea [relatable situation involving {topic}] until I found this.",
    }

    return f"""Write a {duration}-second YouTube Shorts script about: "{topic}"

Target: exactly {word_target} words (±10 words)
Hook style: {hook_examples.get(hook_style, hook_examples["question"])}

Structure:
1. HOOK (first 5-7 seconds, ~15 words): Shocking opening question or bold claim
2. SETUP (next 10-12s, ~25 words): Brief context - why this matters RIGHT NOW
3. BODY (middle {duration-20}s, ~{word_target - 60} words): 2-3 fascinating facts or steps, each more surprising than the last
4. TWIST/PAYOFF (~8s, ~18 words): The surprising conclusion or mind-blowing fact
5. CTA (last 5s, ~12 words): Strong call to action (follow for more, like if surprised, etc.)

Output the script in this EXACT JSON format:
{{
  "hook": "...",
  "body": "...",
  "cta": "...",
  "full_script": "... (complete voiceover, hook + body + cta combined)",
  "word_count": 0,
  "estimated_duration": 0.0
}}"""


# ──────────────────────────────────────────────
# OLLAMA GENERATOR
# ──────────────────────────────────────────────

class OllamaScriptGenerator:
    def __init__(self):
        import ollama
        self.client = ollama
        self.model = OLLAMA_MODEL

    def _is_available(self) -> bool:
        try:
            import requests
            r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def generate(self, topic: str, duration: int = 60,
                 hook_style: str = "question") -> Optional[Dict]:
        if not self._is_available():
            logger.warning("[ollama] Server not available")
            return None

        prompt = _make_prompt(topic, duration, hook_style)
        try:
            response = self.client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                options={"temperature": 0.8, "num_predict": 800},
            )
            raw = response["message"]["content"]
            return self._parse_response(raw, topic, duration)
        except Exception as e:
            logger.error(f"[ollama] Generation error: {e}")
            return None

    def _parse_response(self, raw: str, topic: str, duration: int) -> Dict:
        # Try to extract JSON block
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            try:
                data = json.loads(json_match.group())
                full = data.get("full_script", "")
                wc = len(full.split())
                data["word_count"] = wc
                data["estimated_duration"] = round(wc / WPS, 1)
                return data
            except json.JSONDecodeError:
                pass
        # Fallback: treat entire response as full script
        full = raw.strip()
        wc = len(full.split())
        return {
            "hook": full[:100],
            "body": full[100:-80],
            "cta": full[-80:],
            "full_script": full,
            "word_count": wc,
            "estimated_duration": round(wc / WPS, 1),
        }


# ──────────────────────────────────────────────
# TEMPLATE FALLBACK GENERATOR
# No LLM required — uses smart fill-in-the-blank templates
# ──────────────────────────────────────────────

TEMPLATES = {
    30: {
        "hooks": [
            "Most people have NO idea this is happening with {topic}.",
            "Scientists just discovered something WILD about {topic}.",
            "This one fact about {topic} will change how you see everything.",
            "You won't believe what just happened with {topic}.",
        ],
        "bodies": [
            "Here's what's going on. {topic_sentence}. "
            "Experts are shocked because this breaks everything we thought we knew. "
            "And the most surprising part? This affects every single one of us.",
            "New research shows {topic_sentence}. "
            "For years, scientists assumed the opposite was true. "
            "But this discovery flips the script completely.",
        ],
        "ctas": [
            "Follow for daily mind-blowing facts like this one.",
            "Like if this surprised you — and follow for more.",
            "Drop a comment if you knew this already. Most people don't.",
        ],
    },
    60: {
        "hooks": [
            "Here's a fact about {topic} that almost nobody knows.",
            "Stop scrolling — this will blow your mind. {topic}.",
            "I spent 3 hours researching {topic} so you don't have to.",
            "The truth about {topic} is way more interesting than you think.",
        ],
        "bodies": [
            "Let me explain. {topic_sentence}. "
            "First, the background. This started back when experts noticed something strange. "
            "Specifically, {topic_sentence}. "
            "But here's where it gets really interesting. "
            "Unlike anything we've seen before, this has major implications. "
            "Think about it this way — if {topic_sentence}, then everything changes. "
            "The data backs this up completely. Researchers found the results were 3x stronger than expected.",
            "{topic_sentence}. "
            "Here are three things you need to know. "
            "Number one: this is already happening around you. "
            "Number two: {topic_sentence}, which means the stakes couldn't be higher. "
            "Number three: experts are divided — some say it's the best thing ever, others aren't so sure. "
            "The bottom line? This is going to affect your life whether you're ready or not.",
        ],
        "ctas": [
            "Follow for more facts that actually matter. New video every day.",
            "If this surprised you, smash that like button. And follow so you never miss one.",
            "Comment 'more' if you want a deep dive. We might do a full video on this.",
        ],
    },
    90: {
        "hooks": [
            "What if everything you knew about {topic} was completely wrong?",
            "This single discovery about {topic} is rewriting textbooks right now.",
            "Nobody's talking about this {topic} story — but they should be.",
        ],
        "bodies": [
            "{topic_sentence}. And the story behind it is unbelievable. "
            "It starts with a question nobody thought to ask: why? "
            "{topic_sentence}. Researchers spent years trying to figure this out. "
            "The breakthrough came when they noticed something hiding in plain sight. "
            "Here's what that means in plain English. "
            "Imagine you're {topic_sentence}. Now imagine finding out the opposite is true. "
            "That's exactly what happened. And the consequences are still unfolding. "
            "Experts say this is just the beginning. In the next five years, "
            "we'll see this change {topic} completely. "
            "The most important part? You can actually use this knowledge today.",
        ],
        "ctas": [
            "Follow for the stories the mainstream media won't tell you. Every single day.",
            "Part two is coming. Follow so you don't miss it. And like if your mind is blown.",
            "Share this with someone who needs to hear it. And follow for daily facts like this.",
        ],
    },
}

import random

class TemplateScriptGenerator:
    def generate(self, topic: str, duration: int = 60) -> Dict:
        dur_key = min([30, 60, 90], key=lambda d: abs(d - duration))
        tmpl = TEMPLATES[dur_key]
        ts = self._topic_sentence(topic)

        def fill(text):
            return text.replace("{topic}", topic).replace("{topic_sentence}", ts)

        hook = fill(random.choice(tmpl["hooks"]))
        body = fill(random.choice(tmpl["bodies"]))
        cta  = random.choice(tmpl["ctas"])
        full = f"{hook} {body} {cta}"

        # Trim / pad to target word count
        wc   = len(full.split())
        return {
            "hook": hook,
            "body": body,
            "cta":  cta,
            "full_script": full,
            "word_count": wc,
            "estimated_duration": round(wc / WPS, 1),
        }

    def _topic_sentence(self, topic: str) -> str:
        """Create a natural sentence from a topic string."""
        topic = topic.strip().rstrip(".")
        if topic[0].isupper() and " " in topic:
            # Looks like "Scientists discover X"
            return topic
        return f"researchers are uncovering surprising truths about {topic.lower()}"


# ──────────────────────────────────────────────
# UNIFIED SCRIPT GENERATOR (tries Ollama, falls back to template)
# ──────────────────────────────────────────────

class ScriptGenerator:
    def __init__(self):
        self.ollama = OllamaScriptGenerator()
        self.template = TemplateScriptGenerator()

    def generate(self, topic: str, duration: int = 60,
                 hook_style: str = "question") -> Dict:
        """
        Try Ollama first, fall back to template.
        Returns dict with: hook, body, cta, full_script, word_count,
                           estimated_duration, model_used.
        """
        result = None

        # Try Ollama
        try:
            result = self.ollama.generate(topic, duration, hook_style)
            if result:
                result["model_used"] = OLLAMA_MODEL
                logger.info(f"[script] Generated via Ollama ({result['word_count']} words)")
        except Exception as e:
            logger.warning(f"[script] Ollama failed: {e}")

        # Fallback to template
        if not result and USE_FALLBACK:
            result = self.template.generate(topic, duration)
            result["model_used"] = "template"
            logger.info(f"[script] Generated via template ({result['word_count']} words)")

        if not result:
            raise RuntimeError("Script generation failed — no Ollama and fallback disabled")

        # Ensure all required keys
        result.setdefault("hook", "")
        result.setdefault("body", "")
        result.setdefault("cta", "")
        result.setdefault("model_used", "unknown")
        return result

    def generate_title_variants(self, topic: str, script: Dict,
                                 num_variants: int = 2) -> List[str]:
        """Generate A/B test title variants."""
        hook = script.get("hook", topic)
        keyword = topic[:50]
        variants = [
            f"{keyword} — This Will Shock You 😱",
            f"The Truth About {keyword} Nobody Tells You",
            f"{keyword}: Mind-Blowing Facts #shorts",
            f"Did You Know This About {keyword}? #facts",
            f"This Changes EVERYTHING About {keyword}",
        ]
        random.shuffle(variants)
        return variants[:num_variants]

    def generate_description(self, topic: str, script: Dict) -> str:
        hook = script.get("hook", "")
        return textwrap.dedent(f"""
            {hook}

            🔥 In this Short, we explore: {topic}

            📲 Follow for daily mind-blowing facts and viral stories!
            👍 Like if this surprised you
            💬 Comment what you want to learn next!

            #shorts #facts #viral #trending #didyouknow #learnontiktok #{topic.split()[0].lower()}
        """).strip()

    def generate_hashtags(self, topic: str, category: str = "general") -> str:
        base = ["#shorts", "#viral", "#facts", "#trending", "#didyouknow"]
        cat_tags = {
            "tech":    ["#tech", "#technology", "#ai", "#future", "#science"],
            "science": ["#science", "#sciencefacts", "#nature", "#space", "#biology"],
            "health":  ["#health", "#wellness", "#medical", "#fitness", "#body"],
            "finance": ["#money", "#finance", "#investing", "#economy", "#rich"],
            "culture": ["#culture", "#art", "#music", "#movies", "#lifestyle"],
            "general": ["#interesting", "#mindblown", "#wow", "#amazingfacts"],
        }
        topic_tag = f"#{re.sub(r'[^a-z0-9]', '', topic.lower().split()[0])}"
        tags = base + cat_tags.get(category, cat_tags["general"]) + [topic_tag]
        return " ".join(tags[:15])


if __name__ == "__main__":
    gen = ScriptGenerator()
    for dur in [30, 60, 90]:
        result = gen.generate("Scientists discover ocean bacteria that eats plastic", dur)
        print(f"\n{'='*60}")
        print(f"Duration: {dur}s | Words: {result['word_count']} | Model: {result['model_used']}")
        print(f"Hook: {result['hook']}")
        print(f"Estimated: {result['estimated_duration']}s")
