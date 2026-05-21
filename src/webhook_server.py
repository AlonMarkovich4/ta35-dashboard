"""
Webhook Server — FastAPI endpoint לקבלת חדשות מ-Telegram Bot.

POST /webhook/telegram
  קלט JSON: {source, text, source_msg_id, has_media}
  פלט:     {"status": "saved"|"skipped", ...}

אימות אופציונלי: Bearer token דרך משתנה סביבה WEBHOOK_SECRET.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

_SRC = Path(__file__).parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from data_loader import get_engine
from events import add_event, init_events_db, load_all_events
from news_fetcher import classify_event, is_market_relevant

_DB_PATH   = Path(__file__).parent.parent / "database" / "ta35.db"
_DEDUP_LEN = 80
_MAX_NAME  = 120

app = FastAPI(title="TA-35 Telegram Webhook", docs_url=None, redoc_url=None)


class TelegramPayload(BaseModel):
    source:        str
    text:          str
    source_msg_id: Optional[int] = None
    has_media:     bool = False


def _check_auth(request: Request) -> None:
    """בודק Bearer token אם הוגדר WEBHOOK_SECRET בסביבה."""
    secret = os.getenv("WEBHOOK_SECRET", "")
    if not secret:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != secret:
        raise HTTPException(status_code=403, detail="Unauthorized")


@app.post("/webhook/telegram")
async def receive_telegram(payload: TelegramPayload, request: Request) -> dict:
    """
    מקבל הודעת טלגרם, מסווג ושומר לטבלת events אם רלוונטית לשוק.

    שלבי עיבוד:
      1. אימות Bearer token (אם WEBHOOK_SECRET מוגדר)
      2. בדיקת רלוונטיות לשוק עם is_market_relevant
      3. סיווג לקטגוריה עם classify_event
      4. בדיקת כפילות (לפי 80 התווים הראשונים של השם)
      5. שמירת אירוע עם add_event
    """
    _check_auth(request)

    # split long messages: first 200 chars as title, rest as summary
    title   = payload.text[:200]
    summary = payload.text[200:500] if len(payload.text) > 200 else ""

    if not is_market_relevant(title, summary):
        return {"status": "skipped", "reason": "not_market_relevant"}

    category = classify_event(title, summary)
    if category is None:
        return {"status": "skipped", "reason": "unclassified"}

    engine = get_engine(_DB_PATH)
    init_events_db(engine)

    ev_df = load_all_events(engine)
    name  = title[:_MAX_NAME]
    existing: set[str] = (
        set(ev_df["name"].str[:_DEDUP_LEN].tolist()) if not ev_df.empty else set()
    )
    if name[:_DEDUP_LEN] in existing:
        return {"status": "skipped", "reason": "duplicate"}

    desc = f"[טלגרם] {payload.source}"
    if payload.source_msg_id:
        desc += f" msg#{payload.source_msg_id}"
    if payload.has_media:
        desc += " [+מדיה]"

    event_id = add_event(
        engine, date.today(), name, category, desc, source=payload.source
    )

    return {"status": "saved", "event_id": event_id, "category": category}
