import schedule
import time
import threading
from src import aggregator # Changed from news_aggregator
from src.utils.telegram_bot import send_telegram_notification, format_notification
from src.database import database

def job(send_notifications=True):
    print("Fetching news...")
    # This now calls our new, free-tier pipeline
    new_articles = aggregator.fetch_and_process_news()
    
    # Handle notifications for new articles in a separate thread to avoid blocking
    if send_notifications:
        def notify():
            for article in new_articles:
                if article.get('score', 0) >= 8 and not database.has_been_notified(article.get('link')):
                    message = (f"🚨 ALERT: {article.get('title')}\n"
                               f"Link: {article.get('link')}\n"
                               f"Score: {article.get('score')}")
                    send_telegram_notification(message)
                    database.mark_as_notified(article.get('link'))
        
        threading.Thread(target=notify, daemon=True).start()

def run_scheduler():
    # We've already done the initial fetch in app.py, so we just start the timer
    schedule.every(5).minutes.do(job)
    while True:
        schedule.run_pending()
        time.sleep(1)

def start_scheduler_thread():
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
