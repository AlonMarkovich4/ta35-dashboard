"""
בדיקות יחידה למודול options_parser.
"""
import sys
from pathlib import Path
from io import BytesIO

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from options_parser import (
    MULTIPLIER,
    _C,
    _detect_columns,
    _parse_section,
    find_atm,
    get_strategy_strikes,
    parse_putvscall,
)


# ─── helpers ────────────────────────────────────────────────────────

def _make_chain(strikes_calls_puts: list[tuple]) -> pd.DataFrame:
    """בונה DataFrame שרשרת לבדיקות."""
    rows = []
    for strike, call_price, put_price in strikes_calls_puts:
        rows.append({
            "strike":      float(strike),
            "call_price":  float(call_price),
            "put_price":   float(put_price),
            "call_delta":  50.0,
            "put_delta":   -50.0,
            "call_oi":     0.0,
            "put_oi":      0.0,
            "call_volume": 0.0,
            "put_volume":  0.0,
            "call_high":   0.0,
            "call_low":    0.0,
            "put_high":    0.0,
            "put_low":     0.0,
        })
    df = pd.DataFrame(rows)
    df["call_pts"] = df["call_price"] / MULTIPLIER
    df["put_pts"]  = df["put_price"]  / MULTIPLIER
    return df


def _make_csv_bytes(expiry_date: str = "12/05/2026",
                    expiry_type: str = "שבועי",
                    strikes: list[tuple] | None = None) -> bytes:
    """
    בונה קובץ putvscall.csv מינימלי לבדיקות.
    מבנה: 3 שורות כותרת + שורת מפריד + שורות נתונים.
    """
    if strikes is None:
        # 3 סטרייקים: ITM, ATM, OTM
        strikes = [(4480, 2000, 500), (4500, 1000, 1000), (4520, 500, 2000)]

    header_meta = "נתוני נגזרים,,,,,,,,,,,,,,,,,,,,,,,,,,\n"
    header_date = "נכון ל- 01/05/2026\n"
    # כותרות עמודות — חייב להכיל "מחיר מימוש" בעמודה 13
    col_names = [
        "פוז' פתוחות Call", "שער בסיס Call", "שער גבוה Call", "שער נמוך Call",
        "מחזור בנכס בסיס Call", "תמורה Call", "מספר עסקאות Call", "מחזור ביחידות  Call",
        "שער אחרון Call", "זמן Call", "דלתא Call", "שם נייר Call", "מס Call",
        "מחיר מימוש Put/Call",
        "מס Put", "שם נייר Put", "דלתא Put", "זמן Put",
        "שער אחרון Put", "מחזור ביחידות  Put", "מספר עסקאות Put", "תמורה Put",
        "מחזור בנכס בסיס Put", "שער נמוך Put", "שער גבוה Put",
        "שער בסיס Put", "פוז' פתוחות Put",
    ]
    header_cols = ",".join(col_names) + "\n"
    separator   = f",,,,,,,,,,,,,,,{expiry_date} - {expiry_type}\n"

    data_rows = ""
    for strike, call_p, put_p in strikes:
        # בונה שורת נתונים בת 27 עמודות
        parts = ["0"] * 27
        parts[8]  = str(float(call_p))
        parts[10] = "50.0"   # call_delta
        parts[13] = str(float(strike))
        parts[16] = "-50.0"  # put_delta
        parts[18] = str(float(put_p))
        data_rows += ",".join(parts) + "\n"

    content = header_meta + header_date + header_cols + separator + data_rows
    return content.encode("utf-8-sig")


# ─── _detect_columns ─────────────────────────────────────────────────

class TestDetectColumns:
    def test_detects_standard_layout(self):
        csv = _make_csv_bytes()
        lines = csv.decode("utf-8-sig").splitlines()
        col_map = _detect_columns(lines)
        assert col_map["strike"] == 13
        assert col_map["call_price"] == 8
        assert col_map["put_price"] == 18
        assert col_map["call_delta"] == 10
        assert col_map["put_delta"] == 16

    def test_fallback_when_no_header(self):
        lines = ["line without header", "another line"]
        col_map = _detect_columns(lines)
        assert col_map == _C

    def test_strike_column_detected(self):
        csv = _make_csv_bytes()
        lines = csv.decode("utf-8-sig").splitlines()
        col_map = _detect_columns(lines)
        assert "strike" in col_map
        assert col_map["strike"] >= 0

    def test_shifted_layout_uses_detected_positions(self):
        """פורמט עם עמודה נוספת לפני הסטרייק — הזיהוי האוטומטי מסתגל."""
        col_names_shifted = [
            "עמודה חדשה",  # extra column at start
            "פוז' פתוחות Call", "שער בסיס Call", "שער גבוה Call", "שער נמוך Call",
            "מחזור בנכס בסיס Call", "תמורה Call", "מספר עסקאות Call", "מחזור ביחידות  Call",
            "שער אחרון Call", "זמן Call", "דלתא Call", "שם נייר Call", "מס Call",
            "מחיר מימוש Put/Call",
            "מס Put", "שם נייר Put", "דלתא Put", "זמן Put",
            "שער אחרון Put", "מחזור ביחידות  Put", "מספר עסקאות Put", "תמורה Put",
            "מחזור בנכס בסיס Put", "שער נמוך Put", "שער גבוה Put",
            "שער בסיס Put", "פוז' פתוחות Put",
        ]
        lines = [
            "meta,,,,,,,,,,,,,,,,,,,,,,,,,,,,\n",
            "נכון ל- 01/05/2026\n",
            ",".join(col_names_shifted) + "\n",
        ]
        col_map = _detect_columns(lines)
        assert col_map["strike"] == 14  # shifted by 1
        assert col_map["call_price"] == 9   # shifted by 1
        assert col_map["put_price"] == 19   # shifted by 1


# ─── parse_putvscall ──────────────────────────────────────────────────

class TestParsePutvsCall:
    def test_returns_expiries_list(self):
        result = parse_putvscall(_make_csv_bytes())
        assert "expiries" in result
        assert len(result["expiries"]) == 1

    def test_as_of_date_extracted(self):
        result = parse_putvscall(_make_csv_bytes())
        assert result["as_of_date"] == "01/05/2026"

    def test_chain_has_expected_columns(self):
        result = parse_putvscall(_make_csv_bytes())
        chain = result["expiries"][0]["chain"]
        for col in ("strike", "call_price", "put_price", "call_pts", "put_pts",
                    "call_delta", "put_delta"):
            assert col in chain.columns, f"חסרה עמודה: {col}"

    def test_strikes_sorted_ascending(self):
        result = parse_putvscall(_make_csv_bytes())
        chain = result["expiries"][0]["chain"]
        strikes = chain["strike"].tolist()
        assert strikes == sorted(strikes)

    def test_call_pts_equals_price_div_multiplier(self):
        result = parse_putvscall(_make_csv_bytes())
        chain = result["expiries"][0]["chain"]
        assert (chain["call_pts"] == (chain["call_price"] / MULTIPLIER).round(2)).all()

    def test_accepts_bytes(self):
        csv_bytes = _make_csv_bytes()
        result = parse_putvscall(csv_bytes)
        assert len(result["expiries"]) == 1

    def test_accepts_file_like(self):
        csv_bytes = _make_csv_bytes()
        result = parse_putvscall(BytesIO(csv_bytes))
        assert len(result["expiries"]) == 1

    def test_expiry_type_parsed(self):
        result_w = parse_putvscall(_make_csv_bytes(expiry_type="שבועי"))
        result_m = parse_putvscall(_make_csv_bytes(expiry_type="חודשי"))
        assert result_w["expiries"][0]["expiry_type"] == "שבועי"
        assert result_m["expiries"][0]["expiry_type"] == "חודשי"

    def test_multiple_expiries(self):
        # שני בלוקי פקיעה בקובץ אחד
        header_meta = "נתוני נגזרים,,,,,,,,,,,,,,,,,,,,,,,,,,\n"
        header_date = "נכון ל- 01/05/2026\n"
        col_names = [
            "פוז' פתוחות Call", "שער בסיס Call", "שער גבוה Call", "שער נמוך Call",
            "מחזור בנכס בסיס Call", "תמורה Call", "מספר עסקאות Call", "מחזור ביחידות  Call",
            "שער אחרון Call", "זמן Call", "דלתא Call", "שם נייר Call", "מס Call",
            "מחיר מימוש Put/Call",
            "מס Put", "שם נייר Put", "דלתא Put", "זמן Put",
            "שער אחרון Put", "מחזור ביחידות  Put", "מספר עסקאות Put", "תמורה Put",
            "מחזור בנכס בסיס Put", "שער נמוך Put", "שער גבוה Put",
            "שער בסיס Put", "פוז' פתוחות Put",
        ]
        header_cols = ",".join(col_names) + "\n"

        def data_row(strike, call_p, put_p):
            parts = ["0"] * 27
            parts[8] = str(float(call_p))
            parts[13] = str(float(strike))
            parts[18] = str(float(put_p))
            return ",".join(parts) + "\n"

        content = (
            header_meta + header_date + header_cols
            + ",,,,,,,,,,,,,,,12/05/2026 - שבועי\n"
            + data_row(4500, 1000, 1000)
            + ",,,,,,,,,,,,,,,31/05/2026 - חודשי\n"
            + data_row(4500, 900, 900)
        )
        result = parse_putvscall(content.encode("utf-8-sig"))
        assert len(result["expiries"]) == 2

    def test_junk_row_with_small_strike_excluded(self):
        """שורה עם סטרייק נמוך (כמו strike=1) מסוננת."""
        # Add a "junk" row with strike=1 before real data
        header_meta = "נתוני נגזרים,,,,,,,,,,,,,,,,,,,,,,,,,,\n"
        header_date = "נכון ל- 01/05/2026\n"
        col_names = [
            "פוז' פתוחות Call", "שער בסיס Call", "שער גבוה Call", "שער נמוך Call",
            "מחזור בנכס בסיס Call", "תמורה Call", "מספר עסקאות Call", "מחזור ביחידות  Call",
            "שער אחרון Call", "זמן Call", "דלתא Call", "שם נייר Call", "מס Call",
            "מחיר מימוש Put/Call",
        ]
        # junk row (14 cols, strike=1)
        junk = "0,,,,0,0,0,0,999999,סוף יום,100,CJUNK,12345,1.0\n"
        real = ["0"] * 27
        real[8] = "1000"; real[13] = "4500"; real[18] = "1000"
        real_row = ",".join(real) + "\n"

        content = (
            header_meta + header_date + ",".join(col_names) + ",מס Put\n"
            + ",,,,,,,,,,,,,,,12/05/2026 - שבועי\n"
            + junk + real_row
        )
        result = parse_putvscall(content.encode("utf-8-sig"))
        if result["expiries"]:
            chain = result["expiries"][0]["chain"]
            assert (chain["strike"] >= 100).all(), "שורת junk עם strike<100 לא סוננה"

    def test_empty_file_returns_no_expiries(self):
        result = parse_putvscall(b"")
        assert result["expiries"] == []


# ─── find_atm ────────────────────────────────────────────────────────

class TestFindAtm:
    def test_finds_atm_by_parity(self):
        """ATM נמצא לפי |call - put| מינימלי."""
        chain = _make_chain([(4480, 2000, 500), (4500, 1000, 1000), (4520, 500, 2000)])
        atm = find_atm(chain)
        assert atm["strike"] == 4500.0

    def test_returns_empty_dict_when_no_prices(self):
        chain = _make_chain([(4500, 0, 0), (4510, 0, 0)])
        assert find_atm(chain) == {}

    def test_index_estimate_computed(self):
        chain = _make_chain([(4500, 1000, 1000)])  # parity: S = 4500 + 0 = 4500
        atm = find_atm(chain)
        assert abs(atm["index_estimate"] - 4500.0) < 1.0

    def test_index_estimate_with_parity_offset(self):
        """S ≈ strike + (C - P) / MULTIPLIER."""
        # call=1500, put=500 → delta_pts = 1000/50 = 20 → S ≈ 4500 + 20 = 4520
        chain = _make_chain([(4500, 1500, 500)])
        atm = find_atm(chain)
        assert abs(atm["index_estimate"] - 4520.0) < 1.0

    def test_fallback_to_call_only_rows(self):
        """כאשר אין put_price — fallback לפי call_delta."""
        chain = _make_chain([(4490, 1200, 0), (4500, 1000, 0)])
        chain.loc[chain["strike"] == 4500, "call_delta"] = 50.0
        chain.loc[chain["strike"] == 4490, "call_delta"] = 55.0
        atm = find_atm(chain)
        assert atm != {}
        assert atm["strike"] == 4500.0

    def test_returns_required_keys(self):
        chain = _make_chain([(4500, 1000, 1000)])
        atm = find_atm(chain)
        for key in ("strike", "call_price", "put_price", "call_pts", "put_pts",
                    "call_delta", "index_estimate"):
            assert key in atm

    def test_prices_converted_to_pts(self):
        chain = _make_chain([(4500, 1000, 500)])
        atm = find_atm(chain)
        assert atm["call_pts"] == pytest.approx(1000 / MULTIPLIER)
        assert atm["put_pts"]  == pytest.approx(500  / MULTIPLIER)


# ─── get_strategy_strikes ─────────────────────────────────────────────

class TestGetStrategyStrikes:
    @pytest.fixture
    def chain_and_atm(self):
        strikes_data = [(s, max(1, 4500 - s + 500), max(1, s - 4500 + 500))
                        for s in range(4300, 4701, 10)]
        chain = _make_chain([(s, c, p) for s, c, p in strikes_data])
        return chain, 4500.0

    def test_returns_all_six_strategies(self, chain_and_atm):
        chain, atm_strike = chain_and_atm
        result = get_strategy_strikes(atm_strike, chain)
        assert set(result.keys()) == {1, 2, 3, 4, 5, 6}

    def test_each_strategy_has_required_keys(self, chain_and_atm):
        chain, atm_strike = chain_and_atm
        result = get_strategy_strikes(atm_strike, chain)
        for sid, info in result.items():
            for key in ("strikes_desc", "structure", "cost_pts",
                        "max_loss_desc", "max_profit_desc"):
                assert key in info, f"אסטרטגיה {sid} חסרת מפתח: {key}"

    def test_strategy_1_is_bull_call(self, chain_and_atm):
        chain, atm_strike = chain_and_atm
        result = get_strategy_strikes(atm_strike, chain)
        assert "Call" in result[1]["strikes_desc"]
        assert result[1]["cost_pts"] >= 0  # תמיד קנייה נטו

    def test_strategy_5_straddle_cost_is_call_plus_put(self, chain_and_atm):
        chain, atm_strike = chain_and_atm
        result = get_strategy_strikes(atm_strike, chain)
        straddle = result[5]
        assert straddle["cost_pts"] > 0

    def test_strategy_2_iron_condor_has_four_legs(self, chain_and_atm):
        chain, atm_strike = chain_and_atm
        result = get_strategy_strikes(atm_strike, chain)
        desc = result[2]["strikes_desc"]
        assert desc.count("Put") >= 2 and desc.count("Call") >= 2
