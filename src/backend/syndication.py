"""
syndication.py — PulseForge Multi-Platform Webhook & Distribution Engine
========================================================================
Features:
  - Telegram Bot Video & Preview Dispatcher
  - Discord Channel Webhook Announcer with Rich Embeds
  - Local Multi-Platform Social Media Package Generator (TikTok, Instagram Reels, YouTube Shorts)
  - Safe error handling: Never throws blocking exceptions if webhooks are unconfigured
"""

import os
import json
import time
import requests
from typing import Dict, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def send_discord_webhook(webhook_url: str, video_path: str, title: str, description: str, tags: list = None, viral_score: float = 90.0) -> Dict[str, Any]:
    """
    Sends an automated notification with rich embed payload to a Discord webhook channel.
    """
    if not webhook_url or not webhook_url.strip():
        return {"status": "skipped", "reason": "No Discord webhook URL configured"}

    tags_str = " ".join([f"#{t.strip('#')}" for t in (tags or ["Shorts", "Viral", "Trending"])])
    file_size_mb = os.path.getsize(video_path) / (1024 * 1024) if os.path.exists(video_path) else 0.0

    embed = {
        "title": f"🎬 New Automated Short Ready: {title}",
        "description": f"{description[:300]}...\n\n**Hashtags:** {tags_str}",
        "color": 0x00FFAA,  # Neon Cyan/Green
        "fields": [
            {"name": "🔥 Viral Index", "value": f"**{viral_score:.1f}/100**", "inline": True},
            {"name": "📁 Output Path", "value": f"`{video_path}`", "inline": True},
            {"name": "💾 File Size", "value": f"{file_size_mb:.2f} MB", "inline": True},
            {"name": "⚡ Platforms", "value": "YouTube Shorts · TikTok · IG Reels", "inline": True}
        ],
        "footer": {
            "text": "PulseForge Neural Autonomous Studio Engine"
        },
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    }

    payload = {
        "username": "PulseForge AI Publisher",
        "avatar_url": "https://img.icons8.com/fluency/96/lightning-bolt.png",
        "content": f"🚀 **New AI Short synthesized and ready for publishing!**\n`{video_path}`",
        "embeds": [embed]
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code in [200, 204]:
            print(f"[syndication] [OK] Discord webhook notification delivered successfully.")
            return {"status": "success", "platform": "discord"}
        else:
            print(f"[syndication] Discord webhook status {resp.status_code}: {resp.text}")
            return {"status": "failed", "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        print(f"[syndication] Discord webhook note: {e}")
        return {"status": "error", "error": str(e)}


def send_telegram_notification(bot_token: str, chat_id: str, video_path: str, title: str, description: str, tags: list = None) -> Dict[str, Any]:
    """
    Sends a Telegram message or video upload to a target Telegram channel/group.
    """
    if not bot_token or not chat_id:
        return {"status": "skipped", "reason": "Telegram credentials not provided"}

    tags_str = " ".join([f"#{t.strip('#')}" for t in (tags or ["Shorts", "AI", "Trending"])])
    caption = f"🎬 <b>{title}</b>\n\n{description[:240]}...\n\n🏷️ {tags_str}\n\n📁 <code>{video_path}</code>"

    # Send video if under Telegram 50MB bot limit
    file_size_mb = os.path.getsize(video_path) / (1024 * 1024) if os.path.exists(video_path) else 0.0

    if os.path.exists(video_path) and file_size_mb < 45.0:
        url = f"https://api.telegram.org/bot{bot_token}/sendVideo"
        try:
            with open(video_path, 'rb') as video_file:
                files = {'video': video_file}
                data = {'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'}
                resp = requests.post(url, data=data, files=files, timeout=60)
                if resp.ok:
                    print(f"[syndication] [OK] Telegram video upload delivered successfully.")
                    return {"status": "success", "platform": "telegram", "type": "video"}
        except Exception as e:
            print(f"[syndication] Telegram sendVideo error: {e}. Falling back to text message...")

    # Fallback to sendMessage
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        data = {'chat_id': chat_id, 'text': caption, 'parse_mode': 'HTML'}
        resp = requests.post(url, json=data, timeout=10)
        if resp.ok:
            print(f"[syndication] [OK] Telegram text alert delivered.")
            return {"status": "success", "platform": "telegram", "type": "message"}
        return {"status": "failed", "error": resp.text}
    except Exception as err:
        print(f"[syndication] Telegram sendMessage error: {err}")
        return {"status": "error", "error": str(err)}


def create_social_distribution_package(video_path: str, title: str, description: str, tags: list = None, script: str = "") -> str:
    """
    Creates a standardized multi-platform distribution package with copy-paste metadata
    for YouTube Shorts, TikTok, Instagram Reels, and Twitter/X.
    """
    tags_list = tags or ["Shorts", "AI", "Trending", "Viral"]
    hashtags_str = " ".join([f"#{t.strip('#')}" for t in tags_list])
    
    pkg_data = {
        "video_file": video_path,
        "filename": os.path.basename(video_path),
        "generated_at": time.strftime('%Y-%m-%d %H:%M:%S'),
        "platforms": {
            "youtube_shorts": {
                "title": f"{title} #Shorts",
                "description": f"{description}\n\n{hashtags_str}\n\nProduced with PulseForge Autonomous Engine.",
                "tags": [t.strip('#') for t in tags_list]
            },
            "tiktok": {
                "caption": f"{title} 🤯 {hashtags_str} #fyp #viral #trending"
            },
            "instagram_reels": {
                "caption": f"✨ {title}\n.\n{description[:150]}\n.\n{hashtags_str} #reels #explore"
            }
        },
        "full_narration_transcript": script
    }

    meta_filename = os.path.basename(video_path).replace('.mp4', '_social_package.json')
    meta_path = os.path.join(OUTPUT_DIR, meta_filename)
    
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(pkg_data, f, indent=2)

    print(f"[syndication] [OK] Multi-platform social package created: {meta_path}")
    return meta_path


def syndicate_video(video_path: str, title: str, description: str, tags: list = None, script: str = "", viral_score: float = 90.0) -> Dict[str, Any]:
    """
    Master syndication runner. Dispatches alerts to all configured channels and generates distribution artifacts.
    """
    results = {}
    
    # 1. Generate local social package
    pkg_path = create_social_distribution_package(video_path, title, description, tags, script)
    results["package_path"] = pkg_path

    # 2. Discord Webhook from environment
    discord_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if discord_url:
        results["discord"] = send_discord_webhook(discord_url, video_path, title, description, tags, viral_score)

    # 3. Telegram from environment
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if tg_token and tg_chat:
        results["telegram"] = send_telegram_notification(tg_token, tg_chat, video_path, title, description, tags)

    return results
