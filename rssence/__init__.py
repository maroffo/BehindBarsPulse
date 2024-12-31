from rssence.ai_helper import generate_comment
from rssence.feeds import fetch_feed

if __name__ == "__main__":
    # feed_url = "https://www.ilpost.it/feed"
    feed_url = "https://ristretti.org/index.php?format=feed&type=rss"
    articles = fetch_feed(feed_url)

    feed_content = ""
    for article in articles:
        print(f"Titolo: {article['title']}")
        print(f"Link: {article['link']}")
        print(f"Autore: {article['author']}")
        print(f"Fonte: {article['source']}")
        print(f"Riassunto:\n{article['summary']}\n")
        feed_content += f"Titolo: {article['title']}\n"
        feed_content += f"Link: {article['link']}\n"
        feed_content += f"Autore: {article['author']}\n"
        feed_content += f"Fonte: {article['source']}\n"
        feed_content += f"\n{article['content']}\n\n"
        feed_content += "---------------------------\n"
    newsletter_content = generate_comment(feed_content)
    print()
    print(newsletter_content)
