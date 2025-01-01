from mail_sender import send_behind_bars_email
from rssence import *
import core

log = logging.getLogger(__name__)

feed_url = "https://ristretti.org/index.php?format=feed&type=rss"
articles_list = fetch_feed_content(feed_url, 100)
articles_list = enrich_content(articles_list)
newsletter_opening = get_newsletter_opening(articles_list)
newsletter_closing = get_newsletter_closing(newsletter_opening, articles_list)

context = {
    'newsletter_opening': newsletter_opening,
    'newsletter_closing': newsletter_closing,
    'articles_list': articles_list,
    'notification_address_list': ['maroffo@gmail.com']
}

send_behind_bars_email(context)

