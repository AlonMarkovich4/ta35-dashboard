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

## מנגנון המרווח האופטימלי — ✅ הושלם (שלבים 1–6)
מנוע לבחירת רוחב ה-Short Iron Condor האופטימלי לפקיעה קרובה. מודולים טהורים (אפס UI/DB):
- `src/payoff.py` — פרימיטיב ה-P&L של ה-condor (4 רגליים).
- `src/margin_calculator.py` — עקומת המרווח: לכל מרווח בגריד (1.0–3.0%) בוחר strikes אמיתיים
  מהשרשרת ומחשב פרמיה, max_loss, breakevens ו-P&L (`margin_pnl`).
- `src/move_distribution.py` — התפלגות התנועות ההיסטורית + `hold_probability`, `expected_value_curve`
  (EV עם avg_loss אמיתי דרך `margin_pnl`, לא max_loss), ו-conditioning שעוטף את `find_similar_expiries`.
- `src/margin_selector.py` — בחירת המרווח האופטימלי מתוך העקומה.
- `src/margin_validator.py` + `src/margin_backtest.py` — שכבת ולידציה + backtest היסטורי של המנגנון.
- `src/margin_recorder.py` — רישום ההמלצות ל-`margin_recommendations` (Action יומי, idempotent).

## שכבת "המנוע מול המציאות" (גשרים 1–2) — ✅ הושלם
- `src/decision_recorder.py` (גשר 1) — רושם החלטות מנוע ל-`decision_log`.
- `src/decision_validator.py` (גשר 2) — hit-rate / regret מול ה-P&L האמיתי. **guard:** מצרף רק את
  6 האסטרטגיות המקוריות (`BENCHMARK_STRATEGY_IDS`, strategy_id 1–6) — תיק ההמלצות (102) מוחרג
  מ-best/hit/regret, בצד Python וגם ב-TS (`web/src/lib/validationMath.ts` + השאילתות ב-`data.ts`).

## גשר 3 — מסחר-לפי-המלצות (דמו) — ✅ הושלם וחי ב-main
- `src/recommendation_trader.py` — `open_recommended_condor` פותח Short Iron Condor דמו בתיק
  ההמלצות לפי ההמלצה האחרונה. הגנות: **kill-switch** (`RECO_TRADING_ENABLED`, דלוק), **דדופ**
  (עסקה אחת לפקיעה בתיק), **שער מרחק-לפקיעה** (`min_days_to_expiry=1` — מדלג על פקיעת אותו-יום;
  מחר עדיין נפתח), ו-strategy_id ייעודי **102** (מבודד מ-decision_validator).
- **תיק ההמלצות:** id=8, "המלצות המערכת — Iron Condor" (הון 100k, עמלה 2.5). אל תיגע ב-6 התיקים
  הקיימים (ids 2–7) — benchmark קבוע.
- מחובר ל-Action היומי `auto_record_margins` (`scripts/auto_record_margins.py::_open_reco_trades`).

## סביבה
- repo: ta35-dashboard. נתיב מקומי: ~/Projects/ta35-dashboard/ta35-dashboard/ (הועבר מ-~/Desktop בגלל חסימות TCC של macOS)
- DB דרך pooler: aws-1-ap-southeast-2.pooler.supabase.com:5432
- DATABASE_URL לא מוגדר מקומית כברירת מחדל — הזרק inline להרצת סקריפטים.
- Render deploy מ-main (~3 דק').
