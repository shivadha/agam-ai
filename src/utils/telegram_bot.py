import requests
from src.config.config import get_config

def send_telegram_notification(message):
    config = get_config()
    bot_token = config['telegram']['bot_token']
    chat_id = config['telegram']['chat_id']
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'Markdown'
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error sending Telegram notification: {e}")

def format_notification(article):
    alert_type = "[FREE TOOL DETECTED]" if "free" in article.title.lower() else "[MAJOR MODEL DROP]"
    hook = f"The new {article.title} just dropped..."
    demand_rating = f"{article.score}/10"

    message = (
        f"🚨 {alert_type}\n\n"
        f"*Topic:* {article.title}\n"
        f"*Link:* {article.link}\n\n"
        f"*YouTube Viability Hook:* {hook}\n"
        f"*Demand Rating:* {demand_rating}"
    )
    return message
