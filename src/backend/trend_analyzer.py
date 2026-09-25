VIRAL_KEYWORDS = {
    "free": 10, "open source": 10, "beta access": 8,
    "waitlist open": 7, "limited time offer": 8,
    "openai": 9, "google": 9, "anthropic": 9, "meta": 9, "nvidia": 8,
    "gpt": 8, "claude": 8, "gemini": 8, "llama": 8,
    "breaking": 10, "exclusive": 8, "just released": 12,
    "new model": 10, "outperforms": 10, "beats": 8,
    "open weights": 9, "multimodal": 7, "reasoning": 7,
}

VIDEO_KEYWORDS = {
    "how to": 15, "tutorial": 15, "explained": 12, "guide": 10,
    "vs": 12, "comparison": 12, "review": 10, "best": 8,
    "top 10": 12, "ranked": 8, "tier list": 10,
    "breaking": 15, "exclusive": 12, "first look": 15,
    "open source": 10, "free": 8, "shocking": 8, "changed": 8,
    "gpt": 10, "claude": 10, "gemini": 10, "llama": 10,
    "model": 5, "benchmark": 10, "beats": 12, "outperforms": 14,
    "released": 8, "launch": 8, "new": 5, "just": 4,
    "model drop": 15, "leaked": 12, "rumor": 8,
    "kills": 10, "destroys": 10, "game changer": 12,
}

TOPIC_VIDEO_BONUS = {
    "AI News":       20,
    "AI & LLMs":     20,
    "Breakthroughs": 18,
    "Open Source":   15,
    "AI Tools":      15,
    "Gaming":        15,
    "Pop Culture":   15,
    "Entertainment": 12,
    "Tech":          10,
    "Science":       8,
    "Space":         10,
    "Finance":       6,
    "Sports":        8,
    "World News":    5,
}


def calculate_viral_score(title: str) -> int:
    score       = 0
    title_lower = title.lower()
    for keyword, value in VIRAL_KEYWORDS.items():
        if keyword in title_lower:
            score += value
    return score


def calculate_video_score(title: str, topic: str = '') -> int:
    """
    0–100 score predicting how well this story would perform as a YouTube video.
    Considers title keywords, topic category, and title length (hook quality).
    """
    score       = 0
    title_lower = title.lower()

    for keyword, value in VIDEO_KEYWORDS.items():
        if keyword in title_lower:
            score += value

    score += TOPIC_VIDEO_BONUS.get(topic, 0)

    # Bonus for medium-length titles (good YouTube hook length)
    words = len(title.split())
    if 8 <= words <= 14:
        score += 5
    elif words < 5:
        score -= 5   # Too short — weak hook

    # Bonus for questions (curiosity gap)
    if '?' in title:
        score += 8

    # Bonus for numbers (list-style content performs well)
    import re
    if re.search(r'\b\d+\b', title):
        score += 6

    return min(100, max(0, score))
