"""
איסוף חדשות אוטומטי מ-RSS — TA-35 Expiry Intelligence.

מייצא:
  fetch_all_feeds()    — מחזיר רשימת כתבות מ-RSS
  classify_event()     — מסווג כתבה לקטגוריה
  is_market_relevant() — בודק רלוונטיות לשוק ההון
  save_new_events()    — שומר אירועים חדשים חדשים לטבלת events
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

import feedparser

from events import add_event, init_events_db, load_all_events

# ─── RSS sources ─────────────────────────────────────────────────────────
_FEEDS: dict[str, str] = {
    "גלובס":     "https://www.globes.co.il/webservice/rss/rssfeeds.aspx?rid=3",
    "TheMarker": "https://www.themarker.com/srv/rss",
    "רויטרס":    "https://feeds.reuters.com/reuters/businessNews",
}

# ─── Classification keywords (Hebrew) ────────────────────────────────────
_KEYWORDS: dict[str, list[str]] = {
    "מלחמה":  ["מלחמה", "תקיפה", "טיל", "חמאס", "חיזבאללה", "איראן", "ביטחון"],
    "ריבית":  ["ריבית", "פד", "בנק מרכזי", "העלאה", "הורדה"],
    "משבר":   ["קריסה", "משבר", "נפילה", "פשיטת רגל", "מיתון"],
    "פוליטי": ["ממשלה", "כנסת", "בחירות", "קואליציה"],
    "מגפה":   ["קורונה", "נגיף", "מגפה"],
}

# broader market-relevance terms (beyond category keywords)
_MARKET_TERMS: list[str] = [
    "כלכלה", "שוק", "מניות", "אג\"ח", "מדד", "בורסה",
    "דולר", "שקל", "אינפלציה", "תוצר", "צמיחה",
    "השקעות", "קרן", "מחזור", "רווחים", "הפסד",
]

_TAG_RE = re.compile(r"<[^>]+>")
_MAX_NAME_LEN  = 120
_MAX_DESC_LEN  = 250
_DEDUP_KEY_LEN = 80


def _strip_html(text: str) -> str:
    """מסיר תגיות HTML מטקסט."""
    return _TAG_RE.sub("", text).strip()


def _text_contains(text: str, keywords: list[str]) -> bool:
    """בודק אם הטקסט מכיל לפחות אחת ממילות המפתח."""
    for kw in keywords:
        if kw in text:
            return True
    return False


def fetch_all_feeds(
    feeds: Optional[dict[str, str]] = None,
    timeout: int = 10,
) -> list[dict]:
    """
    מושך כתבות מכל מקורות ה-RSS המוגדרים.

    מחזיר רשימת dict עם המפתחות:
      published (date), title (str), summary (str), source (str)
    מדלג על מקורות שנכשלה גישה אליהם (ללא raise).
    """
    if feeds is None:
        feeds = _FEEDS

    articles: list[dict] = []
    for source, url in feeds.items():
        try:
            feed = feedparser.parse(
                url,
                request_headers={"User-Agent": "TA35-Dashboard/1.0"},
            )
            for entry in feed.entries:
                title   = _strip_html(entry.get("title",   ""))
                summary = _strip_html(entry.get("summary", entry.get("description", "")))
                if not title:
                    continue

                pub_parsed = entry.get("published_parsed")
                if pub_parsed:
                    try:
                        pub_date: date = datetime(*pub_parsed[:6]).date()
                    except Exception:
                        pub_date = date.today()
                else:
                    pub_date = date.today()

                articles.append({
                    "published": pub_date,
                    "title":     title,
                    "summary":   summary,
                    "source":    source,
                })
        except Exception:
            pass  # network/parse failure — continue to next feed

    return articles


def classify_event(title: str, summary: str) -> Optional[str]:
    """
    מסווג כתבה לקטגוריה לפי מילות מפתח בכותרת ובתקציר.

    בוחן קטגוריות לפי סדר: מלחמה, ריבית, משבר, פוליטי, מגפה.
    מחזיר שם קטגוריה או None אם הכתבה אינה רלוונטית.
    """
    text = title + " " + summary
    for category, keywords in _KEYWORDS.items():
        if _text_contains(text, keywords):
            return category
    return None


def is_market_relevant(title: str, summary: str) -> bool:
    """
    בודק אם כתבה רלוונטית לשוק ההון.

    מחזיר True אם הכותרת/תקציר מכילים מילות מפתח כלכליות,
    פיננסיות, ביטחוניות, או פוליטיות.
    """
    text = title + " " + summary
    all_kw = _MARKET_TERMS + [kw for kws in _KEYWORDS.values() for kw in kws]
    return _text_contains(text, all_kw)


def save_new_events(engine) -> int:
    """
    מושך חדשות מ-RSS, מסנן ומסווג, ושומר אירועים חדשים לטבלת events.

    מדלג על:
      - כתבות שאינן רלוונטיות לשוק
      - כתבות שלא מסווגות לקטגוריה מוכרת
      - כתבות שכבר קיימות בטבלה (השוואה לפי 80 התווים הראשונים של השם)

    מחזיר מספר האירועים שנשמרו בפועל.
    """
    init_events_db(engine)
    ev_df = load_all_events(engine)
    existing: set[str] = (
        set(ev_df["name"].str[:_DEDUP_KEY_LEN].tolist())
        if not ev_df.empty
        else set()
    )

    articles = fetch_all_feeds()
    saved = 0
    for art in articles:
        if not is_market_relevant(art["title"], art["summary"]):
            continue
        category = classify_event(art["title"], art["summary"])
        if category is None:
            continue
        name = art["title"][:_MAX_NAME_LEN]
        if name[:_DEDUP_KEY_LEN] in existing:
            continue

        desc = (
            f"{art['source']}: {art['summary'][:_MAX_DESC_LEN]}"
            if art["summary"]
            else art["source"]
        )
        add_event(engine, art["published"], name, category, desc)
        existing.add(name[:_DEDUP_KEY_LEN])
        saved += 1

    return saved
