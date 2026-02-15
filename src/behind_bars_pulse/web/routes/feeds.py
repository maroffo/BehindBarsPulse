# ABOUTME: RSS feed routes for bulletins, digests, and newsletters.
# ABOUTME: Provides RSS 2.0 feeds for content syndication.

from datetime import UTC, datetime
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Request
from fastapi.responses import Response

from behind_bars_pulse.web.dependencies import BulletinRepo, NewsletterRepo, WeeklyDigestRepo

router = APIRouter(prefix="/feed")


def _build_rss_feed(
    title: str,
    description: str,
    link: str,
    items: list[dict],
) -> str:
    """Build an RSS 2.0 feed XML string.

    Args:
        title: Feed title.
        description: Feed description.
        link: Feed link (website URL).
        items: List of dicts with keys: title, link, description, pub_date, guid.

    Returns:
        RSS 2.0 XML string.
    """
    rss = Element("rss", version="2.0")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")

    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = title
    SubElement(channel, "description").text = description
    SubElement(channel, "link").text = link
    SubElement(channel, "language").text = "it-IT"
    SubElement(channel, "lastBuildDate").text = datetime.now(UTC).strftime(
        "%a, %d %b %Y %H:%M:%S +0000"
    )

    # Atom self-link for feed validation
    atom_link = SubElement(channel, "atom:link")
    atom_link.set("href", f"{link}/feed")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    for item_data in items:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = item_data["title"]
        SubElement(item, "link").text = item_data["link"]
        SubElement(item, "description").text = item_data["description"]
        SubElement(item, "pubDate").text = item_data["pub_date"]
        guid = SubElement(item, "guid")
        guid.text = item_data["guid"]
        guid.set("isPermaLink", "true")

    xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
    return xml_declaration + tostring(rss, encoding="unicode")


def _get_base_url(request: Request) -> str:
    """Get base URL, forcing https in production."""
    base_url = str(request.base_url).rstrip("/")
    # Force https in production (Cloud Run is behind a load balancer)
    if base_url.startswith("http://") and "localhost" not in base_url:
        base_url = base_url.replace("http://", "https://", 1)
    return base_url


@router.get("/bollettino", response_class=Response)
async def bulletin_feed(
    request: Request,
    bulletin_repo: BulletinRepo,
):
    """RSS feed for daily bulletins (Il Bollettino)."""
    base_url = _get_base_url(request)
    bulletins = await bulletin_repo.list_recent(limit=20)

    items = []
    for b in bulletins:
        pub_date = datetime.combine(b.issue_date, datetime.min.time(), tzinfo=UTC)
        items.append(
            {
                "title": b.title or f"Il Bollettino - {b.issue_date.strftime('%d %B %Y')}",
                "link": f"{base_url}/bollettino/{b.issue_date.isoformat()}",
                "description": b.subtitle
                or "Commento editoriale quotidiano sulle carceri italiane",
                "pub_date": pub_date.strftime("%a, %d %b %Y %H:%M:%S +0000"),
                "guid": f"{base_url}/bollettino/{b.issue_date.isoformat()}",
            }
        )

    xml = _build_rss_feed(
        title="Il Bollettino - BehindBars",
        description="Commento editoriale quotidiano sulle notizie dal sistema penitenziario italiano",
        link=base_url,
        items=items,
    )

    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")


@router.get("/newsletter", response_class=Response)
async def newsletter_feed(
    request: Request,
    newsletter_repo: NewsletterRepo,
):
    """RSS feed for weekly newsletters."""
    base_url = _get_base_url(request)
    newsletters = await newsletter_repo.list_recent(limit=20)

    items = []
    for n in newsletters:
        pub_date = datetime.combine(n.issue_date, datetime.min.time(), tzinfo=UTC)
        items.append(
            {
                "title": n.title or f"Newsletter - {n.issue_date.strftime('%d %B %Y')}",
                "link": f"{base_url}/archive/{n.issue_date.isoformat()}",
                "description": n.subtitle or "Rassegna stampa settimanale sulle carceri italiane",
                "pub_date": pub_date.strftime("%a, %d %b %Y %H:%M:%S +0000"),
                "guid": f"{base_url}/archive/{n.issue_date.isoformat()}",
            }
        )

    xml = _build_rss_feed(
        title="Newsletter - BehindBars",
        description="Rassegna stampa settimanale dal sistema penitenziario italiano",
        link=base_url,
        items=items,
    )

    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")


@router.get("/digest", response_class=Response)
async def digest_feed(
    request: Request,
    digest_repo: WeeklyDigestRepo,
):
    """RSS feed for weekly digests."""
    base_url = _get_base_url(request)
    digests = await digest_repo.list_recent(limit=20)

    items = []
    for d in digests:
        pub_date = datetime.combine(d.week_end, datetime.min.time(), tzinfo=UTC)
        week_str = f"{d.week_start.strftime('%d %B')} - {d.week_end.strftime('%d %B %Y')}"
        items.append(
            {
                "title": d.title or f"Digest Settimanale - {week_str}",
                "link": f"{base_url}/digest/{d.week_end.isoformat()}",
                "description": d.subtitle
                or "Riepilogo settimanale delle notizie dal sistema penitenziario italiano",
                "pub_date": pub_date.strftime("%a, %d %b %Y %H:%M:%S +0000"),
                "guid": f"{base_url}/digest/{d.week_end.isoformat()}",
            }
        )

    xml = _build_rss_feed(
        title="Digest Settimanale - BehindBars",
        description="Riepilogo settimanale delle notizie dal sistema penitenziario italiano",
        link=base_url,
        items=items,
    )

    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")
