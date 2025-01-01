from mail_sender import send_behind_bars_email
from rssence import *

feed_url = "https://ristretti.org/index.php?format=feed&type=rss"
articles_list = fetch_feed_content(feed_url, 9)
articles_list = enrich_content(articles_list)
newsletter_body = get_feed_summary(articles_list)

context = {
    'newsletter_body': newsletter_body,
    'articles_list': articles_list,
}

send_behind_bars_email(context)

