#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/dispatch_pipeline.py — יורה את ה-workflows מבחוץ, דרך workflow_dispatch.

**למה הסקריפט הזה קיים**

ה-`schedule` של GitHub הפסיק להיות אמין. הנתונים (נאספו 01/09/2026):

  · מעולם לא הייתה ריצה "בזמן" — בסיס של 25–56 דק' איחור לפחות מ-18/08.
    ב-26/08, יום שנראה תקין, cron `0 7` ירה ב-07:42 ו-cron `0 9` ב-09:42.
  · ב-27/08 שינוי משטר: איחור של 5–12 שעות, **ומשבצות נופלות**.
    `auto_close_expiries` עם 7 crons: 26/08 → 7 מתוך 7; 27/08 → 1 מתוך 7.
  · ב-01/09 — אפס ריצות `schedule`. הפקיעה של אותו בוקר לא נסגרה עד
    שהופעלה ידנית.

**מה נשלל.** הראנרים אינם הבעיה: `created_at == run_started_at` בכל ריצה,
והג'וב נתפס תוך 2–4 שניות. הריצה פשוט **אינה נוצרת**. גם "יותר מדי טריגרים"
נשלל — הקיצוץ מ-32 ל-4 ביום (commit 041c5f8) לא שינה כלום, ולמחרת ירו אפס.
גם פיזור הדקה מ-`:00` נשלל: `archive_intraday_chain` רץ על `0,30` במשך 20 יום
וקיבל בדיוק אותו lag.

**המנוף היחיד שנשאר** הוא לא להיות תלויים במתזמן. אירועי `workflow_dispatch`
אינם עוברים בתור המתוזמן, והראיה החזקה ביותר היא 01/09 עצמו: המתזמן ירה אפס
פעמים, ו-dispatch ידני ב-10:10:51Z רץ מיידית והצליח.

**ה-crons של GitHub נשארים במקומם** — הם חינם, לפעמים עובדים, וריצה כפולה
היא no-op בזכות הדדופ ברמת ה-DB. זו רשת שנייה, לא כפילות.

---

**שלוש החלטות עיצוב שכדאי להבין לפני שינוי**

1. **אין dry-run כברירת מחדל — היפוך מכוון של קונבנציית ה-repo.**
   שאר הסקריפטים כאן מוגנים ב-dry-run כי הם כותבים ל-DB. הסקריפט הזה אינו
   כותב כלום; הוא רק מושך בהדק. טריגר שברירת המחדל שלו היא "לא לעשות כלום"
   הוא **נפילה שקטה** — בדיוק מה שהוא בא למנוע. `--dry-run` קיים לבדיקות.

2. **אין כאן `_trading_day_guard`.** ה-workflows כבר בודקים יום מסחר וטריות
   שרשרת, לכל שלב בנפרד. לשכפל את הלוגיקה כאן ייצור מקור אמת שני שיסחף.
   הסקריפט יורה תמיד; השערים בצד השני מחליטים אם לעשות משהו.

3. **204 או כישלון רועש.** GitHub מחזיר 204 No Content על dispatch מוצלח.
   כל דבר אחר — 401 (PAT פג), 403 (הרשאה חסרה), 404 (workflow לא קיים או
   ה-PAT אינו רואה את ה-repo) — נרשם ויוצא ב-exit≠0. סקריפט שבולע את זה
   ייראה כמו הצלחה בזמן שהצינור מת, וזה מצב הכשל מספר 1 של ההתקנה הזו.

**סדר הירי אינו משנה.** `auto_close` ו-`auto_trade_daily` נורים יחד ואין
ביניהם תלות אמיתית: שער ההון בתיק 10 אינו נוגע בחוזה אחד לפקיעה (תופס
~1,205 ₪ מתוך 20,000; שיא היסטורי 33%), ולכן סגירה שטרם עובדה אינה חוסמת
פתיחה. אם הסייזינג יגדל — זה ישתנה, והסדר יהפוך לחשוב.

---

**הרצה**

    GH_DISPATCH_TOKEN=... python scripts/dispatch_pipeline.py

הסוד נקרא מהסביבה בלבד ולעולם אינו נרשם ללוג. הרשאת ה-PAT הנדרשת:
fine-grained, ה-repo הזה בלבד, **Actions: Read and write** (+ Metadata: read).
ההתקנה המלאה ותאריך התפוגה — HANDOFF סעיף 6ג.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

EXIT_OK, EXIT_ERROR, EXIT_CONFIG = 0, 1, 2

DEFAULT_REPO = "AlonMarkovich4/ta35-dashboard"
DEFAULT_WORKFLOWS = ("auto_close_expiries.yml", "auto_trade_daily.yml")
API = "https://api.github.com/repos/{repo}/actions/workflows/{wf}/dispatches"


def log(msg: str, level: str = "INFO") -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    print(f"[{ts}] {level} | {msg}", flush=True)


def dispatch(repo: str, workflow: str, ref: str, token: str,
             timeout: float = 30.0) -> tuple[bool, str]:
    """יורה workflow אחד. מחזיר (הצליח, תיאור).

    לעולם אינו מחזיר את ה-token או חלק ממנו בתיאור — התיאור נכתב ללוג.
    """
    req = urllib.request.Request(
        API.format(repo=repo, wf=workflow),
        data=json.dumps({"ref": ref}).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "ta35-dispatch-pipeline",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.status
        # 204 הוא ההצלחה היחידה. 200 כאן היה אומר שה-API השתנה תחתינו.
        if code == 204:
            return True, "204 No Content"
        return False, f"קוד לא צפוי {code} (מצופה 204)"
    except urllib.error.HTTPError as e:
        hint = {
            401: "ה-PAT פג או שגוי",
            403: "הרשאה חסרה — נדרש Actions: Read and write",
            404: "ה-workflow לא נמצא, או שה-PAT אינו רואה את ה-repo",
            422: "ה-ref אינו קיים, או שה-workflow חסר workflow_dispatch",
        }.get(e.code, "")
        return False, f"HTTP {e.code}{' — ' + hint if hint else ''}"
    except urllib.error.URLError as e:
        return False, f"כשל רשת: {e.reason}"
    except Exception as e:  # pragma: no cover - הגנה אחרונה
        return False, f"{type(e).__name__}: {e}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="יורה את ה-workflows של הצינור דרך workflow_dispatch.")
    ap.add_argument("--repo", default=os.getenv("GH_REPO", DEFAULT_REPO))
    ap.add_argument("--ref", default=os.getenv("GH_REF", "main"))
    ap.add_argument("--workflow", action="append", dest="workflows",
                    help="שם קובץ workflow. ניתן לחזור. ברירת מחדל: "
                         + ", ".join(DEFAULT_WORKFLOWS))
    ap.add_argument("--dry-run", action="store_true",
                    help="מדפיס מה היה נורה, בלי לפנות ל-API. לבדיקות בלבד — "
                         "אין להשתמש בזה ב-cron.")
    args = ap.parse_args(argv)

    workflows = args.workflows or list(DEFAULT_WORKFLOWS)

    log(f"=== dispatch_pipeline: {args.repo}@{args.ref} · "
        f"{len(workflows)} workflows ===")

    if args.dry_run:
        for wf in workflows:
            log(f"DRY-RUN — היה יורה {wf}")
        log("⚠️  DRY-RUN — לא נורה כלום. להרצה בפועל: בלי --dry-run")
        return EXIT_OK

    token = os.getenv("GH_DISPATCH_TOKEN", "").strip()
    if not token:
        # כשל תצורה מפורש. בלי זה הסקריפט היה מקבל 401 ונראה כמו תקלת רשת.
        log("GH_DISPATCH_TOKEN חסר בסביבה — אי אפשר לירות. "
            "ראה HANDOFF סעיף 6ג.", level="ERROR")
        return EXIT_CONFIG

    failures = 0
    for wf in workflows:
        ok, detail = dispatch(args.repo, wf, args.ref, token)
        if ok:
            log(f"  {wf}: נורה ({detail})")
        else:
            failures += 1
            log(f"  {wf}: ⛔ לא נורה — {detail}", level="ERROR")

    fired = len(workflows) - failures
    log(f"=== סיכום: {fired}/{len(workflows)} נורו · {failures} כשלו ===")
    # כשל חלקי הוא כשל. ריצה שירתה 1 מתוך 2 השאירה חצי צינור מת, ו-exit 0
    # כאן היה מסתיר את זה מכל ניטור שיושב מעל.
    return EXIT_ERROR if failures else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
