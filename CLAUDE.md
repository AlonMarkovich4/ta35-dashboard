# CLAUDE.md — כללי עבודה לפרויקט TA-35

> נטען אוטומטית ע"י Claude Code. ראה PROJECT_GOAL.md לחזון ולמטרות.

## Workflow (קריטי)
- **לעולם לא `git push` בלי אישור מפורש מהמשתמש.**
- לפני כל push: הצג `git diff` + הרץ `pytest` והצג שהכל עובר.
- עבודה לבד → fast-forward merges, היסטוריה ליניארית.
- אל תקמט קבצים לא רלוונטיים (.DS_Store וכו').

## אבטחת מידע
- **לעולם אל תדפיס, תכתוב, או תקמט DATABASE_URL / סיסמאות / API keys** בקוד,
  בלוגים, בפלט סקריפטים, או בהודעות.
- סקריפטים מקבלים סודות ממשתני סביבה בלבד.
- אם סוד נחשף — הזהר את המשתמש מיד והמלץ rotate.

## שלמות דאטה
- **Append-only sacred:** אל תמחק/תדרוס paper_trades, paper_portfolios.
  הדאטה זהב ל-ML.
- **Dry-run לפני כל כתיבה ל-DB:** סקריפט אבחון (קריאה-בלבד, SELECT) שמאמת
  מול דאטה אמיתי לפני שמחברים ל-UI או כותבים.
- כל עסקה נשמרת עם market_snapshot_json מלא (מסלול C — דאטה לעתיד).

## QA והנדסה
- כתוב **בדיקות לכל לוגיקה לא-טריוויאלית** (helpers טהורים → unit tests).
- **תקן שורש, לא תסמין** — תיקון בפונקציה מגן על כל הקוראים, כולל אוטומציה עתידית.
- **pytest לא בודק רינדור UI** (הלקח של Styler.applymap) — אמת חזות בדפדפן אחרי deploy.
- שגיאות שנבלעות מסוכנות — תמיד logging לפני return None/except.
- העדף מצב נגזר (compute) על מצב מאוחסן (store) — מקור אמת אחד.

## מנגנון המרווח האופטימלי (בבנייה — שלב 3 הבא)
מנוע לבחירת רוחב ה-Short Iron Condor האופטימלי לפקיעה קרובה. מודולים טהורים (אפס UI/DB):
- `src/margin_calculator.py` — עקומת המרווח: לכל מרווח בגריד (1.0–3.0%) בוחר strikes אמיתיים
  מהשרשרת ומחשב פרמיה, max_loss, breakevens ו-P&L (`margin_pnl`). עוטף את `payoff.py`.
- `src/move_distribution.py` — התפלגות התנועות ההיסטורית + `hold_probability` (P להחזקה בטווח),
  `expected_value_curve` (EV עם avg_loss אמיתי דרך `margin_pnl`, לא max_loss), ו-conditioning
  שעוטף את `find_similar_expiries` (סוג+חודש+תנועה קודמת).
- הבא (שלב 3): לוגיקת בחירת המרווח מתוך העקומה, ואז שכבת ולידציה.

## סביבה
- repo: ta35-dashboard. נתיב מקומי: ~/Projects/ta35-dashboard/ta35-dashboard/ (הועבר מ-~/Desktop בגלל חסימות TCC של macOS)
- DB דרך pooler: aws-1-ap-southeast-2.pooler.supabase.com:5432
- DATABASE_URL לא מוגדר מקומית כברירת מחדל — הזרק inline להרצת סקריפטים.
- Render deploy מ-main (~3 דק').
