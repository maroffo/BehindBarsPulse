from mail_sender import send_behind_bars_email
from rssence import *
import core

log = logging.getLogger(__name__)

feed_url = "https://ristretti.org/index.php?format=feed&type=rss"
articles_list = fetch_feed_content(feed_url, 100)
feed_content = articles_to_json(articles_list)
articles_list = enrich_content(articles_list)
newsletter_content = get_newsletter_content(articles_list)
press_review = get_press_review(articles_list)

context = {
    'newsletter_title': newsletter_content['title'],
    'newsletter_subtitle': newsletter_content['subtitle'],
    'newsletter_opening': newsletter_content['opening'],
    'newsletter_closing': newsletter_content['closing'],
    'press_review': press_review,
    'notification_address_list': ['maroffo@gmail.com']
}

send_behind_bars_email(context)

