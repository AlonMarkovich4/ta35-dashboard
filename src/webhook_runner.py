"""
Webhook Runner — מפעיל את ה-FastAPI webhook server בthread daemon.

מיועד לייבוא מ-app.py. Python מכיל מודולים ב-sys.modules לאחר ייבוא ראשוני,
ולכן קוד ברמת המודול רץ פעם אחת בלבד גם כשStreamlit מריץ מחדש את app.py.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

_SRC = Path(__file__).parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_thread: threading.Thread | None = None


def _run() -> None:
    """מריץ uvicorn עם webhook_server.app על port 8502."""
    try:
        import uvicorn
        from webhook_server import app as _wh_app
        uvicorn.run(_wh_app, host="0.0.0.0", port=8502, log_level="warning")
    except Exception:
        pass  # אל תקרוס את Streamlit אם הsocket תפוס או uvicorn חסר


def ensure_running() -> None:
    """מפעיל את הthread רק אם אינו כבר רץ."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _thread = threading.Thread(target=_run, daemon=True, name="ta35-webhook")
    _thread.start()


# הפעלה אוטומטית בייבוא ראשוני
ensure_running()
