"""
webhook_worker.py — Render Web Service נפרד לקבלת webhooks מ-Telegram.

הרצה מקומית:
    python scripts/webhook_worker.py

בפרודקשן (Render):
    Start Command: python scripts/webhook_worker.py
    Env vars:      DATABASE_URL, WEBHOOK_SECRET (אופציונלי)

הסרוויס כותב ישירות לאותו PostgreSQL שממנו קורא דשבורד ה-Streamlit.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn

# הוסף src ל-path כדי שיהיה אפשר לייבא webhook_server
_ROOT = Path(__file__).parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from webhook_server import app  # noqa: E402

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
