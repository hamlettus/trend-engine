"""Prompt construction for on-brand draft generation."""
from __future__ import annotations

from trendengine.analysis.aggregator import TopicScore
from trendengine.config import Config

# Per-platform nudges the model should honour.
PLATFORM_HINTS = {
    "instagram": "Instagram caption. Hook in the first line. 3-6 short lines. "
                 "Up to ~15 relevant hashtags. Emojis welcome if on-brand.",
    "tiktok": "TikTok caption. Very short, punchy, trend-aware. 3-5 hashtags.",
    "x": "X/Twitter post. Under 280 characters including hashtags. 1-3 hashtags.",
    "linkedin": "LinkedIn post. Professional, insight-led. 2-4 short paragraphs. "
                "3-5 hashtags.",
}

SYSTEM_PROMPT = (
    "You are a social-media content strategist who writes concise, on-brand, "
    "non-cringe posts that ride real trends. You never fabricate statistics and "
    "you never make claims the source evidence doesn't support. You output only "
    "valid JSON when asked."
)


def build_system_prompt(config: Config) -> str:
    brand = config.brand
    voice = (brand.get("voice") or "").strip()
    tone = ", ".join(brand.get("tone", []))
    extra = f"\n\nBrand voice: {voice}\nTone: {tone}" if voice or tone else ""
    return SYSTEM_PROMPT + extra


# Caption-style directives — these are bandit arms the engine learns to prefer.
STYLE_DIRECTIVES = {
    "hook_first": "Open with a scroll-stopping hook in the first 5 words.",
    "listicle": "Structure the body as a tight numbered list of 3-5 points.",
    "question": "Open with a provocative question the viewer wants answered.",
    "bold_claim": "Open with a bold, defensible claim, then back it up.",
}


def build_draft_prompt(topic: TopicScore, config: Config,
                       style: str | None = None,
                       hashtag_count: int | None = None,
                       virality_hints: list[str] | None = None) -> str:
    brand = config.brand
    gen = config.generation
    platform = gen.get("platform", "instagram")
    platform_hint = PLATFORM_HINTS.get(platform, PLATFORM_HINTS["instagram"])
    max_chars = int(gen.get("max_caption_chars", 2200))
    base_tags = " ".join(brand.get("hashtags_base", []))
    cta = brand.get("cta", "")
    use_emoji = brand.get("emoji", True)
    style_line = STYLE_DIRECTIVES.get(style or "", "")
    tag_line = (f"Propose exactly {hashtag_count} topical hashtags."
                if hashtag_count else "Propose relevant topical hashtags.")
    hints_block = ""
    if virality_hints:
        bullets = "\n".join(f"- {h}" for h in virality_hints)
        hints_block = ("\nWHAT WORKS IN THIS NICHE (learned from top performers — "
                       f"apply where it fits, don't force it):\n{bullets}\n")

    evidence_lines = []
    for it in topic.top_items(5):
        evidence_lines.append(
            f"- [{it.source}] {it.title} (engagement score {it.score:.0f}) {it.url}")
    evidence = "\n".join(evidence_lines) if evidence_lines else "- (no items)"

    return f"""\
Write ONE {platform} post about this trending topic for the niche "{config.niche.get('name', '')}".

TOPIC: {topic.topic}
WHY IT'S TRENDING (signals):
- appears in {topic.frequency} pieces of content across {', '.join(topic.sources)}
- growth vs recent baseline: {topic.growth:+.0%}
- normalised engagement: {topic.engagement}

SUPPORTING EVIDENCE (do not invent beyond this):
{evidence}

REQUIREMENTS:
- {platform_hint}
- Caption max {max_chars} characters.
- {"Emojis allowed." if use_emoji else "No emojis."}
- Always-include hashtags: {base_tags or "(none)"}
- {tag_line}
- {"End with this call-to-action: " + cta if cta else "No forced CTA."}
- {style_line or "Use your best judgment on structure."}
- Explain the trend's relevance to the audience; be specific, not generic.
{hints_block}
Respond with ONLY a JSON object, no markdown fences, exactly this shape:
{{
  "caption": "the full post caption text",
  "hashtags": ["#tag1", "#tag2"],
  "rationale": "1-2 sentences on why this trend matters and why to post now"
}}
"""
