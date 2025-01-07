from mail_sender import send_behind_bars_email
from rssence import *
import core
from dateutil.utils import today

log = logging.getLogger(__name__)

feed_url = "https://ristretti.org/index.php?format=feed&type=rss"
articles_list = fetch_feed_content(feed_url, 100)
feed_content = articles_to_json(articles_list)
articles_list = enrich_content(articles_list)
newsletter_content = get_newsletter_content(articles_list)
press_review = get_press_review(articles_list)

today_str = today().strftime('%d.%m.%Y')
subject = f"⚖️⛓️BehindBars - Notizie dal mondo della giustizia e delle carceri italiane - {today_str}"

file_name = today().strftime('%Y%m%d')
with open(f"previous_issues/{file_name}.txt", "w") as issue_file:
    issue_file.write(f"{subject}\n")
    issue_file.write(f"Title: {newsletter_content['title']}\n")
    issue_file.write(f"Subtitle: {newsletter_content['subtitle']}\n")
    issue_file.write(f"Opening Comment: {newsletter_content['opening']}\n")
    issue_file.write(f"Closing Comment: {newsletter_content['closing']}\n")
    issue_file.write(f"\nItems:\n")
    for topic in press_review:
        issue_file.write(f"\nTopic: {topic['category']}\n")
        issue_file.write(f"{topic['comment']}\n")
        i = 0
        for article in topic['articles']:
            i += 1
            issue_file.write(f"\n{i}. {article['title']} - {article['link']}\n")
            issue_file.write(f"{article['author']} - {article['source']}\n")
            issue_file.write(f"{article['summary']}\n")

context = {
    'subject': subject,
    'today_str': today_str,
    'newsletter_title': newsletter_content['title'],
    'newsletter_subtitle': newsletter_content['subtitle'],
    'newsletter_opening': newsletter_content['opening'],
    'newsletter_closing': newsletter_content['closing'],
    'press_review': press_review,
    'notification_address_list': ['maroffo@gmail.com', 'angioletta@gmail.com', 'filippo.aroffo@protonmail.com']
}

send_behind_bars_email(context)
