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

## לולאת הלמידה — סגירת הפער settlement → expiry_history — ✅ הושלם
המנוע לומד מ-`expiry_history`. הפער שהתגלה בשבוע ההרצה הראשון: הטבלה נעצרה ב-2026-05-07
ופקיעות שנסגרו (`condor_settled_detail`) לא הוזרמו אליה, כך ש-`select_margin` בחר `recent_move`
ממאי — המנוע היה עיוור לשבועות האחרונים.
- `src/history_updater.py` — `update_expiry_history_from_settlements(engine, dry_run=True)`.
  append-only, אידמפוטנטי (קיים→דלג), `dry_run` כברירת מחדל. כותב דרך `data_loader.save_to_db`
  (אותו נתיב-כתיבה היסטורי, ללא שכפול). CLI: `python3 src/history_updater.py [--commit]`.
- ⛔ **ההנחה המקורית הייתה שגויה — תוקן 31/07/2026.** הטענה שהייתה כאן ("`base_price ←
  condor_settled_detail.base_index_value`, זהו *אותו סוג בסיס* כמו `expiry_history.base_price`,
  ולכן 5.04% הוא העקבי") **הופרכה מול הנתונים**:
  - `base_index_value` הוא עוגן של **סדרה חודשית** — אותו ערך חוזר עד 4 פקיעות שבועיות רצופות.
  - `expiry_history.base_price` הוא **סגירת המושב הקודם** (אומת: `base_price[i] == close_price[i-1]`, 12/12).
  - התוצאה: ממוצע |תנועה| 1.68% בשורות שהוזרמו מול 0.49% בקורפוס — פי 3.4. 27 שורות
    (2.7% מהטבלה) הפכו את ה-regime ל-volatile, ריסקו את המדגם המותנה ל-0, והרחיבו את
    המרווח הנבחר מ-1.75% ל-2.25%.
  - השורות נמחקו (גיבוי: `expiry_history_backup_20260731`) ושוחזרו נכון.
- **ההגדרה הנכונה:** `move_pct = (expiry_price − base_price)/base_price·100`, כאשר
  `base_price` = סגירת המושב הקודם ו-`expiry_price` = מחיר הסילוק (פתיחת יום הפקיעה).
- ⚠️ **`actual_index_close` אינו מה ששמו אומר:** הוא **סגירת המושב הקודם** (אומת מול Yahoo,
  27/27 ואז שוב 28/28 ב-06/08). המקור הוא באג ב-`tase-pipeline/_fetch_settlement_price`,
  אבל **הצריכה הייתה שלנו** — `paper_db` קרא ממנו כמחיר סילוק, וכל עסקה נסגרה במחיר מוסט
  ב-0.59% (פער הלילה). ✅ **תוקן 06/08/2026:** `get_settlement_index` ו-
  `get_expiries_ready_to_close` קוראים מ-`expiry_history.expiry_price` (= פתיחת יום הפקיעה),
  עם גיבוי לפתיחת המדד מ-`index_series`. 187 עסקאות תוקנו רטרואקטיבית
  (`scripts/reprice_closed_trades.py`), **43 הפכו סימן**. בדיקות רגרסיה נועלות את השם
  `condor_settled_detail` מחוץ לשני המסלולים. פירוט: HANDOFF סעיף 11.
- ⛔ **`lastrate` אינו מחיר עסקה** (07/08/2026). הוא נופל מחוץ לטווח `[lowrate, highrate]`
  של אותו יום ב-45% מה-CALL ו-40% מה-PUT — ודווקא בסטרייקים שכן נסחרו. בנוסף, 80%
  מהשורות בארכיון הן ימים ללא אף עסקה.
  ✅ **הפתרון: `VWAP = OverallTurnOverValue_Shekel / OverallTurnOverUnits`** — מחיר עסקה
  משוקלל, בתוך הטווח **100.0%** (2,697/2,697 CALL · 2,995/2,995 PUT), נגזר משדות שכבר
  שמורים. **תמחר בו, לא ב-`lastrate`** (הפער 51.5% חציונית).
  ⛔ **`bid`/`ask` אינם קיימים במקור** — נמשך ה-endpoint ישירות: 36 שדות, אפס רלוונטיים,
  ו-`curr_Hour="סוף יום"` ב-14,264/14,264. אל תחזור לשאלה. פירוט: HANDOFF 11.2ב–ד.
  🔴 **המלכוד:** VWAP זמין ב-100%/75% מהרגליים באופק 1–2 ימים, אבל רק **18%** באופק 7 —
  שהוא האופק היחיד עם יתרון אפשרי. אפס מ-27 עסקאותיו ניתנות לתמחור מלא.

## נזילות וביצוע — ✅ נוסף 11/08/2026 (HANDOFF סעיף 13)
- **הגורם לנזילות הוא האופק, לא המרחק מהכסף.** P(סטרייק נסחר): יום לפני הפקיעה
  **100%** בכל טווח עד 4% מהכסף · יומיים 91–99% · 3–4 ימים 25–37% · 5+ 3–20%.
- ⛔ **"נסחר" אינו "אפשר לצאת".** ברגליים 1–2 ימים לפקיעה: חציון 128 יחידות/יום,
  אבל **20% הציגו פחות מ-20 יחידות** — שם פקודה אחת היא עשרות אחוזים מהמחזור.
- `src/intraday_archive.py` + Action `archive-intraday-chain` (כל 30 דק') —
  `tase_putcall_history` שומרת צילום אחד ביום ב-17:15, וההתפתחות התוך-יומית נזרקה.
  **אל תנתח עקומת שעות לפני ~שבועיים של צבירה.**
- **תיק 10** ("סינון נזילות", `strategy_id=104`, `LIQUIDITY_TRADING_ENABLED`):
  הון **20,000 ₪**, סף `min_units=50`. נבדל מתיק 9 ב**מספר אחד** — שניהם רצים על
  `vwap_trader.PortfolioSpec`, בכוונה, כדי שההשוואה תמדוד את הסינון ולא סחיפת מימוש.
- `vwap_trader.available_capital` — שער הון לכל התיקים:
  `הון התחלתי + Σ P&L(סגורות) − Σ |max_loss|(פתוחות)`. כשל DB ⇒ לא נפתחת פוזיציה.
  ⚠️ **בחוזה אחד השער כמעט לא נוגע** (שיא היסטורי ~6,500 ₪ מתוך 20,000) — אל תדווח
  עליו כאילו הוא פעיל. מה שכן בולט: **עמלות 13.7% מקרדיט טיפוסי.**
- **שני שערים ב-`history_updater`:** `find_shared_bases` (base משותף בין פקיעות ⇒ חסימה) ו-
  `is_plausible_move` (|move| > 8% ⇒ חסימה; השיא ההיסטורי 5.92%).
- **חיווט Action:** `scripts/auto_close_expiries.py` מריץ את העדכון *אחרי* סגירת העסקאות,
  **מאחורי `HISTORY_UPDATER_ENABLED` שכבוי כברירת מחדל** עד שהבאג ב-`tase-pipeline` יתוקן.
- **שחזור ידני:** `scripts/backfill_expiry_history.py` (dry-run כברירת מחדל).

## לוח מסחר ושער טריות — ✅ נוסף 31/07/2026 (אירוע תשעה באב)
- `src/trading_calendar.py` — `is_trading_day`, `trading_days_between`, `skip_reason`,
  `is_chain_fresh`. מודול טהור, אפס תלויות.
- **שבוע המסחר השתנה:** TASE עברה מ-ראשון–חמישי ל-**שני–שישי** בתחילת 2026. אומת
  משני מקורות (expiry_history + Yahoo). ה-cron של שלושת ה-Actions תוקן מ-`0-4` ל-`1-5`.
- **`_trading_day_guard`** בשני הרושמים (`auto_record_decisions`, `auto_record_margins`).
  `auto_close_expiries` **בכוונה בלי שער** — הטריגר שלו הוא קיום הסטלמנט, לא הזמן.
  עקיפה ידנית: `FORCE_RUN=true`.
- **`is_chain_fresh` — ברירת מחדל 0 = "נמשכה היום".** זו הרמה לכל מי שכותב ל-DB.
- ⚠️ **רשימת החגים מכוסה עד 31/12/2026 בלבד.** שלושה תאריכים בספטמבר עדיין **לא אומתו**
  מול לוח TASE הרשמי (11/09 ערב ר"ה, 25/09 ערב סוכות — נוהג הבורסה משתנה; 21/09 יום כיפור ודאי).
  `holidays_are_current()` מרעישה כשהרשימה מתיישנת.

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
- ⛔ **`RECO_TRADING_ENABLED` כבוי מ-31/07/2026.** ההגנות לא מנעו פתיחה על שרשרת ישנה.
  נסגר בשער הטריות; ההדלקה מחדש דורשת החלטה. ראה HANDOFF סעיף 0.

## אוטומציית תיקי ה-benchmark — ✅ נוסף 02/08/2026
`open_trades_for_expiry` נקראה **רק** מ-`pages/5_paper_trading.py` (Streamlit, שאינו פרוס),
ולכן תיקים 2–7 לא שוגרו אוטומטית מעולם. 24 עסקאות נפתחו ידנית 15/06 ואז כלום.
- `scripts/auto_open_benchmark_trades.py` — ב'–ו' 09:00 UTC, **כשלב 3 בתוך
  `auto_trade_daily.yml`** (אוחד 31/08/2026; ה-workflow הנפרד נשאר ידני-בלבד).
  לוח הזמנים המלא וה-*למה* — HANDOFF 6ב, שהוא הבעלים היחיד של העובדה הזו.
  דדופ ברמת ה-DB (`UNIQUE (portfolio_id, strategy_id, expiry_date)`).
  kill-switch `BENCHMARK_TRADING_ENABLED`, **דלוק** — אין כאן תלות במנוע.
- `scripts/backfill_benchmark_trades.py` — שחזר 132 עסקאות מהארכיון.
  ⚠️ `_NO_SETTLEMENT` מחריג פקיעות שלא התרחשו (23/07) — פתיחה עליהן = יתומה קבועה.

## אופק זמן ואות תנודתיות — 🔬 מדידה בלבד, לא משפיע על הבחירה
**הממצא:** `hold_probability` נמדד על תנועת **מושב אחד**, אך הפוזיציה חשופה 5–6 מושבים.
על 1,993 מושבים במרווח 2.25%: 97.5% למושב אחד מול 72.2% לחמישה.
⚠️ **`floor=0.97` כויל על האופק הלא נכון** (`margin_backtest:130` משתמש ב-`move_pct`).
- `src/index_series.py` — סדרת TA-35 היומית מ-Yahoo. כשל רשת ⇒ `[]`, לא חריגה.
- `move_distribution.horizon_move_distribution(sessions, k)` — התפלגות לאופק k מושבים.
  `entry=close[i−k]`, `settle=open[i]`. מחזיר אותו מבנה ולכן משתלב עם `hold_probability_at_margin`.
- `move_distribution.daily_volatility(sessions, window)` — σ יומית + **מיקום בהתפלגות**
  (`percentile`/`quintile`). תיעוד בלבד, אינו משפיע על בחירה.
  ⛔ **AUC 0.657 שדווח ב-02/08 הוא ארטיפקט של 2016–2021.** במשטר החי (מ-08/2024,
  n=412) הוא **0.507** — הטלת מטבע. גם EWMA (0.511) ופערי פתיחה (0.447) נכשלים.
  **אין להשתמש בו כמנבא משטר.** פירוט: HANDOFF סעיף 10.
- `margin_recorder._horizon_hold` — שומר `horizon.{hold_at_margin, anchor_date, daily_vol}`
  לצד `hold_blended`. **האופק נספר מ-`trade_date` (T-1)**, לא מהיום — ראה `_anchor_date`.
- ⚠️ **אל תזריק מדד חי כעוגן.** כל השרשרת T-1, כולל המחירים. פירוט: HANDOFF 7.3.

## סביבה
- repo: ta35-dashboard. נתיב מקומי: ~/Projects/ta35-dashboard/ta35-dashboard/ (הועבר מ-~/Desktop בגלל חסימות TCC של macOS)
- DB דרך pooler: aws-1-ap-southeast-2.pooler.supabase.com:5432
- DATABASE_URL לא מוגדר מקומית כברירת מחדל — הזרק inline להרצת סקריפטים.
- Render deploy מ-main (~3 דק').
