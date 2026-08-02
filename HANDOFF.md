# HANDOFF — מה שלא נמצא ב-repo

> **עודכן 01/08/2026.** גרסה קודמת נכתבה 27/07 ותיארה מצב שכבר לא קיים.
>
> המסמך מכיל שני סוגי מידע:
> 1. **פנימיות המערכת השנייה, סכמות DB, והחלטות מצ'אט** — נאספו בסשן של 27/07
>    מול מקורות חיים. עדיין תקפים; מסומן היכן השתנה.
> 2. **אירוע תשעה באב וכל מה שתוקן בעקבותיו** — 31/07–01/08.
>
> איפה שלא הצלחנו לאמת כתוב **לא ידוע** במפורש. אל תמלא את החורים בניחוש.

---

## 0. מצב נוכחי — 02/08/2026 (ראשון)

### הנתונים

| | |
|---|---|
| `expiry_history` | **993** שורות · 25/02/2010 → 31/07/2026 · מתוכן **28 משוחזרות** |
| `tase_putcall` | snapshot יחיד: `fetch_date=2026-07-31`, `trade_date=30/07` (T-1 תקין), 362 שורות, 4 פקיעות |
| `tase_putcall_history` | 12,516 שורות · 22/05 → 31/07 |
| `paper_trades` | **194** — 34 סגורות · **160 פתוחות** |
| `margin_recommendations` | 49 (`margin-v1.1`), אחרונה 30/07 |
| `decision_log` | 86, אחרונה 30/07 |
| `expiry_history_backup_20260731` | 27 שורות — הגיבוי של השורות שנמחקו |

### העסקאות לפי תיק

| תיק | סה"כ | פתוחות | הערה |
|---|---|---|---|
| 2–7 (benchmark) | 30 כל אחד | 26 כל אחד | 132 שוחזרו ב-02/08; **132 ייסגרו בריצה הראשונה** — הסילוקים קיימים |
| 8 (המלצות) | 14 | 4 | כולל את היתומה המוכרת (id=36) |

> 160 פתוחות זה **לא** מצב תקין קבוע. 132 מהן הן עסקאות ששוחזרו לפקיעות שכבר
> סולקו, ו-`auto_close_expiries` יסגור אותן בריצה הבאה. הנותרות: 24 פקיעות
> עתידיות (04–07/08), 3 של תיק 8, ועסקה 36.

**היתומה המוכרת:** `id=36`, תיק 8, פקיעה 2026-07-23 — תשעה באב, אין ולא יהיה
סילוק. רשומה ב-`_ACKNOWLEDGED_ORPHANS` וב-`KNOWN_UNSETTLED`; מדווחת בכל ריצה.

### המנוע

`regime=calm` · `recent_move=0.612%` · מדגם מותנה **315** · מרווח נבחר **1.75%**

### מתגים — שניהם כבויים בכוונה

| דגל | מצב | תנאי להדלקה |
|---|---|---|
| `RECO_TRADING_ENABLED` | **false** | אחרי 3–4 ימי מסחר עם השערים החדשים בלי הפתעות |
| `HISTORY_UPDATER_ENABLED` | **false** (ברירת מחדל) | אחרי שבאג הסילוק ב-`tase-pipeline` יתוקן |

---

## 1. אוסף הדאטה — מי כותב ל-`tase_putcall`

### 1.1 בעלות — קרא את זה קודם

**`tase-pipeline` הוא מערכת נפרדת של מתכנת שני**, שיושבת על אותו Supabase.
**לא לגעת בו מכאן.** כל ממצא לגביו הוא מידע להעביר, לא משימה.

repo: `github.com/AlonMarkovich4/tase-pipeline` — ציבורי, נוצר 20/05/2026,
push אחרון 30/06/2026. **אין בו GitHub Actions** (`gh run list --repo ...` ריק).

לא n8n, לא Make, לא cron על המק. אומת: `crontab -l` ריק, `~/Library/LaunchAgents/`
מכיל רק Google/Homebrew.

קבצי מפתח: `main.py`, `tase_api.py`, `browser.py` (Playwright), `database.py`,
`option_schema.py` (שער איכות נתונים), `strategy_engine.py`, `telegram_bot.py`,
`config.py`, `Dockerfile`, `health_server.py`, `supabase_setup.sql`.

### 1.2 איך זה רץ

**Docker → Render Background Worker**, auto-deploy מ-`main`.
`health_server.py` חושף `GET /` על `PORT` (ברירת מחדל 10000) ל-liveness,
ומחזיר 503 אחרי 5 כשלונות רצופים.

**שם ה-service ב-Render וה-ID — לא ידוע.** אין גישה ל-Render מכאן.

### 1.3 תדירות ושעות

מ-`config.py`:

```
TRADING_DAYS = {0,1,2,3,4}      # שני–שישי
MARKET_OPEN  = 09:30            # שעון ישראל
MARKET_CLOSE = 17:30
FETCH_INTERVAL_MINUTES = 15
BROWSER_RESTART_SECONDS = 6h
```

> ✅ **אי-ההתאמה שהייתה כאן — תוקנה 31/07/2026.** ה-Actions של `ta35-dashboard` רצו
> על `cron '... 0-4'` (ראשון–חמישי) בעוד הבורסה עברה ל-שני–שישי בתחילת 2026. כלומר
> רצו בימי ראשון בלי דאטה, ודילגו על שישי — יום מסחר מלא עם פקיעות. תוקן ל-`1-5`.
> אומת משני מקורות: `expiry_history` (אפס פקיעות ביום ראשון ב-2026) ו-Yahoo TA35.TA.

### 1.4 מאיפה הוא מושך

Playwright Chromium headless, בקשות מתוך ה-origin של tase.co.il דרך `page.evaluate`
(עוקף WAF):

| מטרה | endpoint |
|---|---|
| רשימת פקיעות | `GET https://api.tase.co.il/api/derivatives/fltrputvscallexpdates?objId=01&lang=0&dType=2&date=` |
| שרשרת Call/Put | `POST https://api.tase.co.il/api/derivatives/putvscall` |

3 ניסיונות לעמוד עם backoff (5/10/20 שניות), המתנה 3–5 שניות בין פקיעות.

**מדד TA-35 עצמו לא מגיע מ-TASE** — `UnderlingAsset` חוזר ריק. המדד ומחיר הסילוק
מגיעים מ-Yahoo: `https://query1.finance.yahoo.com/v8/finance/chart/TA35.TA`.

### 1.5 הכתיבה ל-Supabase

**דרך PostgREST, לא דרך `DATABASE_URL`.** `supabase_client.py` דורש `SUPABASE_URL`
+ `SUPABASE_KEY` — **לא קיימים בפרויקט הזה**, רק ב-env של Render.

- upsert עם `on_conflict=fetch_date,fetch_time,expiry_date,derivativeid_call,derivativeid_put`
- אצוות של 50 שורות
- `SUPABASE_TABLE` (ברירת מחדל `tase_putcall`), `SUPABASE_HISTORY_TABLE` (`tase_putcall_history`)

### 1.6 סמנטיקה של העמודות

| עמודה | משמעות |
|---|---|
| `fetch_date` | תאריך **שעון ישראל** של מחזור האיסוף, `TEXT` `YYYY-MM-DD` |
| `fetch_time` | שעת המחזור שעון ישראל, `TEXT` `HH:MM` |
| `trade_date` | `TradeDate` מה-payload, `TEXT` בפורמט **`DD/MM/YYYY`** (שונה!). יום המסחר שהנתונים מייצגים, בדרך כלל **T-1** |
| `fetched_at` | `timestamptz DEFAULT now()` — זמן ה-INSERT ב-UTC, **לא** זמן האיסוף |
| `drvtype` | pass-through. בפועל תמיד `'04'`. מה זה מייצג — **לא ידוע** |
| `rowtype` | pass-through. בפועל `NULL` תמיד |

מיפוי `key.lower()` מול whitelist `VALID_COLUMNS` — כל שדה שלא ברשימה נזרק בשקט.

### 1.7 מחזור החיים של הטבלה

`tase_putcall` מחזיקה **snapshot אחד בלבד**:

1. upsert לכל הפקיעות.
2. אם **כל** הפקיעות הצליחו → `_clear_old_snapshots()` מוחק כל מה שאינו
   ה-`(fetch_date, fetch_time)` הנוכחי.
3. אם רק **חלק** הצליחו → הניקוי **מדולג בכוונה**, כדי לא לאבד snapshot שלם.
4. במחזור האחרון של היום → `copy_to_history()` מעתיק ל-`tase_putcall_history`,
   מוגן ב-`pipeline_state` תחת `history_copied:<date>`.

**ההיסטוריה היחידה של שרשרות היא `tase_putcall_history`** — snapshot אחד ליום.

### 1.8 מה קורה כשאין מסחר — קריטי להבנה

**א. פקיעה בלי עסקאות** (`items` ריק): `upsert_no_trading()` כותב שורת placeholder
עם `derivativename_* = 'ללא מסחר'`. **בפועל מעולם לא קרה.**

**ב. ה-feed לא התקדם** (`STALE_TRADE_DATE`) — **זה מה שקרה בתשעה באב**:
`option_schema.check_trade_date()` סופר ימי מסחר בין `trade_date` ל-`fetch_date`.
- פער של יום מסחר אחד = T-1 = תקין.
- פער של **2 ומעלה** → `DQLevel.CRITICAL` → **ה-upsert מדולג לחלוטין.**
- התראת Telegram אחת לכל קוד ליום (`dq_alert:<CODE>:<date>`).
- ה-transport נחשב תקין → אין restart ואין crash alert.

מגבלה מתועדת ב-`option_schema.py` עצמו: **אין לוח שנה של חגים.** `TRADING_DAYS`
הוא ימי שבוע בלבד, ולכן היום הראשון אחרי חג באמצע שבוע סופר יום מסחר עודף
ומדליק `STALE_TRADE_DATE`. **בחירה מודעת** — "fail-safe, חוסם במקום לסחור על דאטה ישן".

> 💡 זה בדיוק מה שקרה: האוסף **לא נכשל**. הוא זיהה נכון שאין נתונים חדשים ועצר.
> הבעיה הייתה אצלנו — שלא ידענו לשאול אם בכלל היינו אמורים לקבל משהו.

### 1.9 לוגים

- **לוגים אמיתיים: Render service logs בלבד.** אין טבלת לוגים ב-DB. לא נגישים מכאן.
- **התראות Telegram** — token ו-chat id ב-env של Render.
- **העקבות היחידות שכן נגישות: `pipeline_state`.** זו הדרך המעשית לבדוק מה קרה:

| מפתח | שעה (UTC) | משמעות |
|---|---|---|
| `dq_alert:<CODE>:<date>` | ~06:30 | התראת איכות-נתונים |
| `settlement_done:<date>` | ~07:01 | סילוק הפקיעה של אותו יום |
| `weekly_heartbeat:<YYYY>-W<ww>` | ~07:01 שני | heartbeat שבועי |
| `strategy_triggered:<YYYY>-W<ww>` | ~09:05 שני | יצירת אסטרטגיות לשבוע |
| `daily_summary_sent:<date>` | ~14:20 | סיכום יומי ב-Telegram |
| `history_copied:<date>` | מיד אחריו | העתקה לארכיון |

---

## 2. סכמות DB

מקור: `information_schema` + `pg_indexes`, נקרא 27/07. **שים לב לסוגי האובייקטים** —
חלק Views:

| אובייקט | סוג |
|---|---|
| `tase_putcall`, `tase_putcall_history` | BASE TABLE |
| `iron_condor_strategies` | BASE TABLE |
| **`condor_settled_detail`** | **VIEW** |
| `best_condor_per_expiry`, `condor_weekly_potential` | VIEW |
| `expiry_history`, `paper_trades`, `paper_portfolios` | BASE TABLE |
| `decision_log`, `margin_recommendations` | BASE TABLE |
| `pipeline_state`, `events`, `demo_trades`, `demo_balance` | BASE TABLE |

### `expiry_history`

```
expiry_date TEXT, expiry_time TEXT, expiry_type TEXT,
base_price DOUBLE PRECISION, expiry_price DOUBLE PRECISION,
open_pct, close_price, daily_pct, volume, transactions, points,
abs_move_pct, move_pct  (כולם DOUBLE PRECISION / BIGINT)
```

**אין PK, אין אינדקסים, אין constraints — אפס.** מניעת כפילויות ברמת האפליקציה בלבד.

- `close_price IS NULL` **מבודד בדיוק את השורות המשוחזרות** (28 כרגע). זה סמן המקור היחיד.
- `base_price[i] == close_price[i-1]` בשורות ה-CSV — אומת 12/12. כלומר **תנועת מושב אחד**.

### `condor_settled_detail` (VIEW)

```sql
SELECT ... FROM iron_condor_strategies
WHERE is_valid = true AND actual_pnl_ils IS NOT NULL
```

> ⚠️ **מלכודת שעלתה בדם.** `is_valid=false` מפיל שורות מה-VIEW, ו-`auto_close_expiries`
> רואה **רק** את ה-VIEW. פקיעת 19/06 הייתה עם סטלמנט תקין אבל כל 8 שורותיה
> `is_valid=false` → 6 עסקאות benchmark נשארו פתוחות שישה שבועות בשקט.
> `is_valid=false` אינו נדיר: ~60 שורות מול ~212 `true`.

### `paper_trades`

```
id BIGSERIAL PK, portfolio_id FK, strategy_id INT, strategy_name TEXT,
expiry_date DATE, opened_at, entry_index, entry_cost, legs_json JSONB,
max_profit, max_loss, status TEXT DEFAULT 'open', closed_at, close_index,
pnl, pnl_pct, market_snapshot_json JSONB, num_legs,
entry_commission, exit_commission

UNIQUE idx_trades_unique (portfolio_id, strategy_id, expiry_date)   ← הדדופ האמיתי
```

**אין status של cancelled/void.** מסלול ה-UPDATE היחיד הוא `close_trade`.

### `paper_portfolios`

| id | שם | strategy_ids |
|---|---|---|
| 2–7 | ששת האסטרטגיות | `[1]`…`[6]` — **benchmark קבוע, אל תיגע** |
| 8 | המלצות המערכת — Iron Condor | `[102]` |

כולם `initial_balance = current_balance = 100,000`. `current_balance` לא מתעדכן —
היתרה נגזרת מ-`compute_balance`.

### `decision_log` / `margin_recommendations`

**אין UNIQUE בשתיהן** — הדדופ בקוד בלבד (`*_logged_today`).
**נוצרו ידנית ב-Supabase SQL Editor**, לא במיגרציה. **אין מנגנון מיגרציות בפרויקט.**

⚠️ `engine_version`: **`margin-v1` שגוי. רק `margin-v1.1` תקף.** אין constraint שאוכף.

### מאיפה מגיע `actual_index_close`

```
Yahoo TA35.TA meta.regularMarketOpen
  → tase-pipeline/strategy_engine.py::_fetch_settlement_price()
    → settle_expiry(today_iso)   [רץ אחרי 10:00, רק על הפקיעה של היום]
      → iron_condor_strategies.actual_index_close
        → VIEW condor_settled_detail → ta35-dashboard
```

> 🔴 **אומת — לא עוד חשד.** `actual_index_close` הוא **סגירת המושב הקודם**, לא פתיחת
> יום הפקיעה כפי שהקוד מתכוון. הושווה מול נרות Yahoo על **27 פקיעות: 27/27 התאמה
> מדויקת** לסגירת היום הקודם, אפס התאמות לפתיחת יום הפקיעה.
>
> החשוד: `settle_expiry` רץ ~10:00 שעון ישראל, ובאותו רגע `meta.regularMarketOpen`
> עדיין מציג את המחזור הקודם.
>
> **ההשלכה רחבה מ-`expiry_history`:** `iron_condor_strategies.actual_pnl_ils` מחושב
> מהמחיר הזה, וכך גם `close_index` של עסקאות שנסגרו אוטומטית. כלומר גם ה-P&L מוסט.
>
> **זה ב-`tase-pipeline`, לא כאן.** להעביר למתכנת השני כראיה לבדיקה. הוא שיפר
> לאחרונה את הטיפול בתאריכים — ייתכן שכבר בטיפול; המדידה שלנו היא עד 31/07 אחורה.

---

## 3. תקלות שטופלו (3.1–3.5 = תשעה באב · 3.6 = תיקי ה-benchmark)

### 3.1 מה קרה (23–26/07)

| תאריך | `dq_alert` | שורות | `settlement_done` |
|---|---|---|---|
| 22/07 | — | 259 (`trade_date=21/07`) | ✅ |
| **23/07** (תשעה באב) | **`STALE_TRADE_DATE`** | **0** | ❌ |
| **24/07** | **`STALE_TRADE_DATE`** | **0** | ❌ |
| 25–26/07 | — | — | שבת + ראשון, לא ימי מסחר |
| 27/07 09:30 | — | 352 ✅ | התאושש לבד |

ב-23/07 הבורסה לא נפתחה → TASE לא פרסמה קובץ → הפער הגיע ל-2 ימי מסחר →
כל ה-upserts דולגו. ב-24/07 הפער גדל עוד → דולג שוב.

> **24/07 היה יום מסחר מלא** (Yahoo מראה נר). החסימה באותו יום הייתה תופעת לוואי
> של ספירת ימי המסחר בלי לוח חגים — לא סגירת בורסה.

**מה הדשבורד עשה בינתיים:** כל ה-Actions ירוקים, אף אחד לא בדק טריות. נרשמו
החלטה והמלצת מרווח לפקיעה `2026-07-23` — ביום שהבורסה הייתה סגורה.

### 3.2 מה תוקן (31/07–02/08)

| קומיט | מה |
|---|---|
| `24b25db` | כיבוי `RECO_TRADING_ENABLED` + גידור הזרמת `expiry_history` |
| `8813b46` | שער העוגן החודשי ב-`history_updater` + `scripts/backfill_expiry_history.py` |
| `3b1f395` | `src/trading_calendar.py` + שער יום-מסחר + תיקון ה-cron |
| `7fe77b9` | חיווט שער הטריות ב-`margin_recorder` |
| `2448b0b` | `_report_orphans` — גילוי עסקאות יתומות |
| `e190de5` · `778c80a` · `f2e4441` | עדכון HANDOFF / AGENTS / PROJECT_WORKPLAN |
| `a27930b` | **אוטומציה לתיקי ה-benchmark** (ראה 3.6) |
| `c4ef2ac` | `scripts/backfill_benchmark_trades.py` |

### 3.3 זיהום `expiry_history` — נמחק ושוחזר

**הבעיה:** `history_updater` חישב `move_pct` מ-`condor_settled_detail.base_index_value`,
שהוא עוגן של **סדרה חודשית** — אותו ערך חוזר עד 4 פקיעות שבועיות רצופות.

**המדידה:** 27 שורות (2.7% מהטבלה) שינו את הפלט מקצה לקצה:

| | עם המזוהמות | בלעדיהן |
|---|---|---|
| `recent_move` | **-4.737%** | 0.568% |
| `regime` | volatile | calm |
| מדגם מותנה | **0** | 333 |
| מרווח נבחר | 2.00% | 1.75% |

**הפתרון:** נמחקו (גיבוי: `expiry_history_backup_20260731`) ושוחזרו לפי ההגדרה
הנכונה — `base` = סגירת המושב הקודם, `expiry_price` = פתיחת יום הפקיעה מ-Yahoo.
שיטת השחזור אומתה **6/6 עד האגורה** מול הסילוק הרשמי שב-CSV, בימי החפיפה 30/04–07/05.

### 3.4 עסקאות יתומות — טופלו

**19/06 (6 עסקאות benchmark):** הסטלמנט היה קיים (4182.02) אבל `is_valid=false`.
נסגרו ידנית לפי **4173.07** (הסילוק האמיתי; 4182.02 הוא סגירת 18/06 — באג T-1).
סה"כ P&L **6,487.00 ₪**, זהה ל-dry-run.

> ⚠️ ב-`daily_review.py` היה רשום `KNOWN_UNSETTLED = {"2026-06-19"}` עם ההערה
> "פקיעה ידועה ללא סטלמנט". **ההערה הייתה שגויה** — הסטלמנט היה קיים.
> התגובה לאירוע הראשון הייתה להשתיק את ההתראה על בסיס אבחון לא נכון.

**23/07 (עסקה 36):** נשארת פתוחה. אין סילוק ולא יהיה. רשומה כ**יתומה מוכרת** —
מדווחת בכל ריצה עם הסיבה המלאה, אך אינה מפילה את הריצה.

### 3.5 השערים החדשים

שלושת המצבים שנראו זהים (וכולם ירוקים) כבר לא זהים:

| מצב | לפני | אחרי |
|---|---|---|
| לא יום מסחר | ירוק | `_trading_day_guard` מדלג עם סיבה |
| יום מסחר + דאטה טרי | ירוק | ירוק |
| **יום מסחר + דאטה ישן** | **ירוק** | **`stale_chain` → exit≠0, אדום** |
| **עסקה שלא נסגרה** | **ירוק** | **`_report_orphans` → exit≠0** |

**הנקודה המבנית:** ביום שאינו יום מסחר הרשם כלל לא מגיע לבדיקת הטריות — השער
חוסם קודם. לכן שרשרת ישנה שם **אינה יכולה** להיות "בגלל חג". זו הבחנה מבנית,
לא הנחה. `FORCE_RUN=true` עוקף להרצה ידנית.

`auto_close_expiries` **בכוונה בלי שער יום-מסחר** — הטריגר שלו הוא קיום הסטלמנט,
לא הזמן. חסימה הייתה מוסיפה מצב כשל (סטלמנט מאוחר שלא ייסגר לעולם).

`decision_recorder` **בכוונה בלי שער טריות** — נשען על השרשרת רק לזיהוי W/M, שלא מתיישן.

---

### 3.6 באג נפרד — תיקי ה-benchmark מעולם לא שוגרו (טופל 01–02/08/2026)

**לא קשור לתשעה באב.** רץ בשקט מאז 15/06/2026.

**הממצא:** `open_trades_for_expiry` — הפונקציה היחידה שפותחת עסקאות לשש
האסטרטגיות (תיקים 2–7) — נקראה ממקום אחד בלבד בכל הפרויקט מלבד טסטים:
`pages/5_paper_trading.py:803`, ממשק **Streamlit שאינו פרוס**
(`render.yaml` מרים רק Next.js + webhook). שלושת ה-Actions לא נגעו בו.

כלומר: **מעולם לא הייתה אוטומציה לתיקים האלה.** 24 עסקאות נפתחו ידנית
ב-15/06 בלחיצת כפתור, ומאז כלום — 22 פקיעות, 132 עסקאות חסרות.

> זה לא היה באג ב-UI ולא בנתונים. פשוט לא היה מי שיפעיל את הפונקציה.

**נזק משני שלא היה גלוי:** `decision_validator` משווה את החלטות המנוע מול
ה-P&L של תיקי ה-benchmark. בלי עסקאות חדשות, **19 מתוך 23 החלטות מנוע נשארו
בלי מול-מה-להשוות** — גשר 2 היה משותק שישה שבועות. זה מסביר למה ה-hit-rate
שהוצג לא אמר כלום.

**מה נעשה:**

1. `scripts/auto_open_benchmark_trades.py` + workflow — שני–שישי 09:00 UTC.
   עובר על הפקיעות הקרובות ופותח את 6 האסטרטגיות לכל אחת. דדופ ברמת ה-DB
   (`UNIQUE (portfolio_id, strategy_id, expiry_date)`) → ריצה יומית בטוחה.
   kill-switch `BENCHMARK_TRADING_ENABLED`, **ברירת מחדל דלוק** — בניגוד
   ל-RECO, כאן אין תלות במנוע: האסטרטגיות רצות על פרמטרים מוקפאים ישירות
   מהשרשרת, בלי `expiry_history` ובלי הכיול שנמצא בבדיקה.

2. `scripts/backfill_benchmark_trades.py` — שחזר **132 עסקאות** מהארכיון
   (23/06 → 31/07). לכל פקיעה נטענה השרשרת מהיום הראשון שבו הופיעה, דרך
   `open_trades_for_expiry` האמיתי. תוצאה: `open=132 · duplicate=24 · excluded=1`.
   אומת מול ה-DB: 194 עסקאות סה"כ, 30 לכל אסטרטגיה, רצף 16/06 → 07/08.

3. `supabase_loader.get_latest_option_chain` קיבל `source_table` ו-`fetch_date`
   כדי לקרוא את הארכיון דרך **אותו נתיב סינון** במקום לשכפל 60 שורות לוגיקה.
   שם הטבלה עובר whitelist (`_check_source`).

**⚠️ ההחרגה החשובה:** ה-dry-run חשף שפקיעת **2026-07-23** קיימת בארכיון עם
שרשרת מלאה, ולכן השחזור היה פותח לה 6 עסקאות — לפקיעה שאין לה סילוק ולעולם
לא יהיה. הן היו הופכות ל-6 יתומות קבועות נוספות. מוחרגת ב-`_NO_SETTLEMENT`,
עם בדיקה שמקבעת את זה. **כל שחזור עתידי חייב לשמור על ההחרגה הזו.**

**שתי טעויות שנעשו בדרך, לתיעוד:**
- הרצת `FORCE_RUN=true` על ה-DB החי כ"בדיקה" פתחה 24 עסקאות אמיתיות
  (`id 44–67`, פקיעות 04–07/08). הן נשמרו — הן בדיוק מה שהאוטומציה אמורה
  לעשות. **`FORCE_RUN` הוא להרצת אופרטור, לא לבדיקות.**
- ריצת שחזור ראשונה נכשלה בשקט על נתיבים יחסיים ב-shell רקע ולא כתבה כלום.
  מצב ה-DB אומת אחרי כל אחת מהן.

---

## 4. החלטות שסוכמו בצ'אט ולא נכתבו בקוד

מקור: תמלילי `~/.claude/projects/-Users-alonmarkovich-Projects-ta35-dashboard-ta35-dashboard/`.

### 4.1 `floor=0.97` (12/07/2026)

הסף המקורי 0.90 נדחה: בחר מרווח 1.0% ב-74% מהשבועות, 75 שבירות. נעשתה סריקת ספים
על `[0.90…0.98]`, walk-forward על 768 פקיעות, `w=0.6`.
**0.97 הוא נקודת הברך:** 23 שבירות בעשור (מול **71** ב-0.96), רצף שחור 1, פרמיה 556₪/שבוע.

`w=0.6` **נשאר כפי שהיה ולא נסרק מעולם.**

### 4.2 `wing_pct=0.75` (13/07/2026)

הרקע: המשתמש בונה בפלטפורמה שלו Iron Condor עם הגנות במרחק 20 נקודות.
סריקת כנפיים `[0.25%…2.0%]`, walk-forward על 768. בחירת המרווח זהה בכל הריצות.
**0.75% היא נקודת האיזון:** 80₪/שבוע = 82% מהשיא, max drawdown **3,712₪** מול **6,524₪**.

### 4.3 הפרדה מכוונת ב-paper trading

`strategy_payoff_params` ב-`payoff.py` נשאר על `(2.0, 1.0)` **בכוונה** —
"תיקי הדמו הם ה-benchmark. רק מנגנון ההמלצות עובר ל-0.75."
**תיקים 2–7 = benchmark מוקפא. תיק 8 = המלצות. אל תאחד.**

### 4.4 `RECO_TRADING_ENABLED` (13/07/2026)

נבנה בשלבים: kill-switch כבוי כברירת מחדל → הרצה ידנית מבוקרת → אימות שתי שאלות →
הדלקה. נוסף `min_days_to_expiry=1` אחרי שנפתחה עסקה על פקיעה של למחרת בבוקר.

> ההגנות שנחשבו מספיקות (kill-switch, דדופ, `min_days_to_expiry`, דמו בלבד)
> **לא מנעו פתיחת עסקה על שרשרת ישנה**. זו הפרצה שהתממשה ב-23/07 — ונסגרה
> ב-`7fe77b9`. הדגל כבוי כרגע.

### 4.5 ✅ חקירת "סחיפת העוגן" — **נסגרה 31/07/2026**

הסשן של 22/07 נקטע ב-API error באמצע חקירה, והשאיר סתירה פתוחה:
> *"אחד משני החישובים באג. החשוד: `hold_probability_at_margin` — אולי לא מחשב
> `P(|move| ≤ m)` כפי שהנחתי."*

**התשובה: שני החישובים תקינים. הנתונים היו מזוהמים.**

- `hold_probability_at_margin` נשען על `dist["moves"]`, שנבנה מ-**`move_pct`** —
  העמודה הנכונה (`move_distribution.py:103`). אומת בהרצה: `moves == sorted(move_pct)`.
- שוחזר `hold_blended = 0.9737` במרווח 2.25% — **זהה בדיוק** לערך שנרשם ב-DB.
- מה שהזיז את הפלט היה `recent_move` ו-`regime`, שנגזרו מ-27 השורות המזוהמות (סעיף 3.3).

**עדיין פתוח מאותה חקירה:** `recent_move` הוא קצר-זיכרון (הפקיעה האחרונה בלבד).
הוצע להחליף בחלון מתגלגל — `max|move|` של 5 האחרונות, או סטיית תקן. **לא נעשה.**

### 4.6 ⚠️ מוקש שנותר: `abs_move_pct` ≠ `|move_pct|`

בשורות ה-CSV, `abs_move_pct` (עמודת "אחוז") **אינו** `|move_pct|` — הוא נבדל
ב-962 מתוך 986 שורות. ממוצע 1.28% מול 0.49%. הוא גם אינו `|daily_pct|` (2/965)
ואינו `|open_pct|` (5/965) — **כמות רביעית שאינה מתועדת בשום מקום.**

CLAUDE.md טוען שהעמודה היא "ערך מוחלט תמיד" — **לא מדויק.**

כרגע זה **לא מזיק**: `_abs_move_series` (ב-`context_analyzer` וב-`move_distribution`)
מזין רק את סיווג ה-`regime` ואת שדה הדיווח `abs_mean`. בחירת המרווח נשענת על
`move_pct`. אבל זה מוקש — כל שימוש עתידי ב-`abs_move_pct` כאילו הוא `|move_pct|` ישגה.

---

## 5. גישה — הרצת אבחון read-only

### 5.1 היכן הסוד

`DATABASE_URL` נמצא ב-**`web/.env.local`** (ב-`.gitignore`). **הערך עצמו לא נכתב כאן.**

```bash
cd ~/Projects/ta35-dashboard/ta35-dashboard
DATABASE_URL="$(grep '^DATABASE_URL=' web/.env.local | cut -d= -f2-)" venv/bin/python <script>
```

`.streamlit/secrets.toml` ו-`.env` בשורש **לא קיימים**. זה הסוד המקומי היחיד.

חיבור דרך ה-**pooler** של Supabase (`aws-1-ap-southeast-2.pooler.supabase.com:5432`).
העדף חיבורים קצרים; אל תחזיק טרנזקציה פתוחה או `prepared statements` ארוכי-חיים.

**אין גישה לאוסף** — הוא כותב עם `SUPABASE_URL`/`SUPABASE_KEY` שיושבים ב-Render בלבד.

### 5.2 דפוס האבחון

```python
eng = create_engine(url, connect_args={"connect_timeout": 20})
with eng.connect() as conn:
    conn.execute(text("SET TRANSACTION READ ONLY"))   # ← תמיד ראשון
    ...
```

שתי ההגנות ביחד: `SET TRANSACTION READ ONLY` (השרת דוחה כתיבה) **וגם** סינון
`SELECT`/`WITH` בקוד. אל תוותר על אף אחת.

### 5.3 שאילתות פתיחה

```sql
-- האם ה-feed חי ומה גיל הנתונים  ← הבדיקה החשובה ביותר
SELECT fetch_date, fetch_time, trade_date, count(*) FROM tase_putcall GROUP BY 1,2,3;

-- מה קרה ב-pipeline (תחליף הלוגים)
SELECT key, updated_at FROM pipeline_state
WHERE updated_at >= now() - interval '3 days' ORDER BY updated_at;

-- עסקאות יתומות
SELECT id, portfolio_id, expiry_date FROM paper_trades
WHERE status='open' AND expiry_date < current_date;

-- שורות משוחזרות ב-expiry_history
SELECT count(*) FROM expiry_history WHERE close_price IS NULL;
```

### 5.4 בדיקת בריאות בלי DB

```bash
gh run list --limit 20
```

⚠️ **Actions ירוקים כבר לא מספיקים כהוכחה — אבל מ-31/07 הם כן אומרים משהו.**
לפני התיקון הכל היה ירוק גם כשהדאטה היה קפוא. עכשיו `stale_chain` ויתומה לא-מוכרת
מפילים את הריצה. הבדיקה האמיתית נשארה `max(fetch_date)` ב-`tase_putcall` מול היום.

---

## 6. מה נשאר "לא ידוע"

1. **מה TASE עשתה עם חוזה 2026-07-23** — גלגלה, סילקה בתאריך אחר, או ביטלה?
   זה הדבר היחיד שחוסם את סגירת עסקה 36. ה-snapshot של 22/07 עוד הכיל אותה
   (94 שורות, שמורות ב-`tase_putcall_history` תחת `fetch_date='2026-07-22'`);
   ב-27/07 היא נעלמה. בימים 23–24/07 האוסף היה חסום — אין לנו רישום.
2. **ערבי חג בלוח TASE** — 11/09 (ערב ר"ה) ו-25/09 (ערב סוכות). נוהג הבורסה משתנה
   בין סגירה מלאה למסחר מקוצר. **חסומים כברירת מחדל** ב-`trading_calendar`, לאימות
   מול הלוח הרשמי. 21/09 (יום כיפור) ודאי. חול-המועד סוכות הוא מסחר ואינו חסום.
3. **רשימת החגים מכוסה עד 31/12/2026 בלבד.** `holidays_are_current()` מרעישה כשתתיישן.
4. **שם ה-service וה-ID ב-Render** של האוסף, ומי מחזיק בגישה.
5. **משמעות `drvtype='04'`.**
6. **האם `w=0.6`** (משקל השילוב) נבדק אי פעם.
7. **האם באג הסילוק** (`actual_index_close`) כבר תוקן ב-`tase-pipeline` — המתכנת
   השני שיפר לאחרונה את הטיפול בתאריכים.
8. **תוכן התראות ה-Telegram** שנשלחו ב-23–24/07.

---

## 6ב. ארבעת ה-Actions — מה רץ ומתי

| Action | cron (UTC) | מה עושה | שער יום-מסחר | kill-switch |
|---|---|---|---|---|
| `auto_record_decisions` | `0 7 * * 1-5` | רושם החלטות ל-`decision_log` | ✅ | — |
| `auto_record_margins` | `0 9 * * 1-5` | המלצות מרווח + פתיחה בתיק 8 | ✅ | `RECO_TRADING_ENABLED` (**כבוי**) |
| `auto_open_benchmark_trades` | `0 9 * * 1-5` | פותח 6 אסטרטגיות בתיקים 2–7 | ✅ | `BENCHMARK_TRADING_ENABLED` (דלוק) |
| `auto_close_expiries` | `0 7-13 * * 1-5` | סוגר פקיעות + מדווח יתומות | ❌ **בכוונה** | `HISTORY_UPDATER_ENABLED` (**כבוי**) |

`auto_open_benchmark_trades` רץ באותה שעה כמו `auto_record_margins` כדי ששתי
הקבוצות ייכנסו מאותו snapshot.

---

## 7. הלקח המרכזי

שתי התקלות הגדולות שנמצאו כאן לא היו שגיאות בקוד. שתיהן היו **היעדר** —
ובשתיהן הכל היה ירוק.

> **תשעה באב: המערכת לא הפסיקה לאסוף נתונים. היא הפסיקה לדעת שהיא לא מקבלת אותם.**
>
> **ה-benchmark: הקוד עבד מצוין. פשוט לא היה מי שיפעיל אותו.**

האוסף עשה בדיוק את הדבר הנכון ועצר. שלוש שכבות אצלנו — ה-cron, הלואדר, והרושמים —
המשיכו לעבוד כאילו כלום, כי אף אחת מהן לא ידעה לשאול "האם בכלל הייתי אמור לקבל
נתונים היום?".

ותיקי ה-benchmark חיכו שש שבועות ללחיצת כפתור בממשק שאינו פרוס — בזמן שגשר 2,
שכל תפקידו להשוות את המנוע למציאות, ישב בלי מציאות להשוות אליה.

וכשמשהו כן נשבר (6 עסקאות פתוחות שישה שבועות), התגובה הייתה להשתיק את ההתראה
במקום לחקור אותה — על בסיס אבחון שהתברר כשגוי.

**שלושה כללים שנגזרים מזה:**
1. הצלחה שקטה מסוכנת יותר מכישלון רועש. אם מסלול לא יכול להאדים — הוא לא מנוטר.
2. רשומה ברשימת "ידוע/מוכר" חייבת סיבה, תאריך, ודיווח בכל ריצה. אחרת היא לא
   תיעוד — היא הסתרה.
3. **פונקציה שאין לה קורא מתוזמן היא פונקציה שלא רצה.** לפני שמניחים שפיצ'ר
   פועל — לבדוק מי קורא לו, ומאיפה. `grep` על שם הפונקציה הוא הבדיקה הזולה
   ביותר בפרויקט הזה, והיא זו שחשפה את 3.6.
