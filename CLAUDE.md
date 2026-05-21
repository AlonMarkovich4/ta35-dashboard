# TA-35 Expiry Intelligence — הוראות לסוכן

## מה הפרויקט
דשבורד ניתוח הסתברותי של פקיעות מדד TA-35.
המערכת מלבישה 6 אסטרטגיות אופציות על 965 פקיעות היסטוריות (2010–2026),
ומייצרת תמונת מצב הסתברותית לפקיעה הקרובה.

**חשוב:** המערכת היא כלי מחקר בלבד — לא המלצת מסחר, לא ביצוע עסקאות.

---

## ארכיטקטורה

- **שפה:** Python 3.11+
- **דשבורד:** Streamlit
- **בסיס נתונים:** SQLite (מעבר ל-PostgreSQL בפרודקשן)
- **ספריות:** pandas, numpy, plotly, streamlit, sqlalchemy
- **סביבה נוכחית:** מקומית (localhost)
- **סביבה עתידית:** VPS / Railway + PostgreSQL

---

## מבנה תיקיות

```
ta35-dashboard/
├── CLAUDE.md                  # הקובץ הזה — קרא תמיד ראשון
├── PROJECT_WORKPLAN.md        # תוכנית עבודה + סטטוס
├── app.py                     # נקודת כניסה Streamlit
├── requirements.txt
├── .gitignore
├── database/
│   └── ta35.db               # SQLite (נוצר אוטומטית)
├── data/
│   ├── uploads/              # CSV שמועלים ידנית
│   │   └── market_data.csv   # פקיעות היסטוריות
│   └── current/              # נתוני פקיעה קרובה
│       ├── putvscall.csv     # שרשרת אופציות (Call vs Put)
│       └── derivativesall.csv
├── src/
│   ├── __init__.py
│   ├── data_loader.py        # טעינה וניקוי CSV
│   ├── strategies.py         # לוגיקת 6 האסטרטגיות
│   ├── backtester.py         # backtest הסתברותי
│   ├── events.py             # שכבת אירועים/חדשות
│   ├── options_parser.py     # פרסור שרשרת אופציות
│   └── charts.py             # גרפים (plotly)
├── pages/
│   ├── 1_historical.py       # ניתוח היסטורי
│   ├── 2_strategies.py       # השוואת אסטרטגיות
│   ├── 3_upcoming.py         # פקיעה קרובה
│   └── 4_events.py           # אירועים והקשר
└── tests/
    └── test_strategies.py
```

---

## נתונים — מה חשוב לדעת

### קובץ פקיעות היסטוריות (`market_data.csv`)
- encoding: `utf-8-sig`
- עמודות: תאריך, שעה, סוג, בסיס, פקיעה, פתיחה%, נעילה, יומי%, מחזור, עסקאות, נקודות, אחוז
- עמודת "אחוז" = ערך מוחלט תמיד (לא שלילי!)
- כיוון תנועה נגזר מ: `(פקיעה - בסיס) / בסיס * 100`
- שורה אחרונה כתוב "פקיעה ראשונה" — לדלג עליה
- שורות עם סוג "-" — לסמן כ-unknown
- סוג W = שבועי, M = חודשי

### שרשרת אופציות (`putvscall.csv`)
- encoding: `utf-8-sig`
- 2 שורות כותרת לפני headers
- Call ו-Put זה לצד זה לפי סטרייק
- מכפיל: 50 ש"ח לנקודה
- מורד ידנית מ-tase.co.il

---

## שש האסטרטגיות

| # | שם | מנצח כאשר |
|---|----|----|
| 1 | Bull Call Spread | move_pct > 0 (עלייה) |
| 2 | Short Iron Condor | abs_move < X% (בטווח) |
| 3 | Long Call Butterfly | abs_move קטן מאוד |
| 4 | Long Put Butterfly | abs_move קטן מאוד |
| 5 | Long Straddle | abs_move > X% (תנועה חזקה) |
| 6 | Long Strangle | abs_move > X% (תנועה חזקה, OTM) |

**פרמטרים לחקירה:**
- Iron Condor: טווח 1%, 1.5%, 2%, 2.5%, 3%
- Butterfly: כנפיים 20, 40, 60, 80 נקודות
- Bull Call Spread: רוחב 10, 20, 30, 50 נקודות
- Strangle/Straddle: מרחק 0.5%, 1%, 1.5%, 2%

---

## כללי קוד — חובה לפעול לפיהם

1. **docstrings בעברית** על כל פונקציה ציבורית
2. **לא למחוק** קבצים מ-`data/uploads/` או `data/current/`
3. **כל גישה ל-DB** דרך SQLAlchemy בלבד — לא sqlite3 ישיר
4. **לא להכניס** מחירים מדויקים בדוחות ללא disclaimer
5. **כל עמוד Streamlit** חייב להכיל הודעת disclaimer בתחתית
6. **בדיקות** — כל פונקציה ב-`src/` חייבת unit test מינימלי

---

## מצב נוכחי — עדכן כאן בכל פגישה

**תאריך עדכון אחרון:** 18/05/2026
**שלב נוכחי:** Milestone 1.1 — הקמת סביבה
**הושלם:**
- [x] הגדרת מטרות ומבנה
- [x] ניתוח קבצי CSV
- [x] גיבוש ארכיטקטורה
- [x] PROJECT_WORKPLAN.md
- [x] CLAUDE.md

**הבא לביצוע:**
- [ ] יצירת מבנה תיקיות
- [ ] requirements.txt
- [ ] app.py בסיסי
- [ ] data_loader.py
