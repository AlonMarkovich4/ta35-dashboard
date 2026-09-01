# -*- coding: utf-8 -*-
"""בדיקות ל-scripts/dispatch_pipeline.py.

הבדיקה המרכזית כאן היא **שכישלון אינו שקט**. הסקריפט הזה הוא ההדק היחיד של
הצינור אחרי שה-`schedule` של GitHub הפסיק להיות אמין; סקריפט שמחזיר exit 0
כשהוא לא ירה ייראה כמו הצלחה בזמן שהצינור מת, ושום ניטור לא יתפוס את זה.
לכן כל מסלול כשל כאן נעול בבדיקה, ולא רק המסלול המוצלח.
"""
import io
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import dispatch_pipeline as dp  # noqa: E402

TOKEN = "ghp_TESTTOKEN_do_not_log_me"


class _Resp:
    """תחליף ל-http.client.HTTPResponse עבור urlopen כ-context manager."""

    def __init__(self, status): self.status = status
    def __enter__(self): return self
    def __exit__(self, *a): return False


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("GH_DISPATCH_TOKEN", TOKEN)
    monkeypatch.delenv("GH_REPO", raising=False)
    monkeypatch.delenv("GH_REF", raising=False)


# ---------------------------------------------------------------- מסלול תקין

def test_204_הוא_הצלחה(monkeypatch, env):
    monkeypatch.setattr(dp.urllib.request, "urlopen", lambda *a, **k: _Resp(204))
    assert dp.main(["--workflow", "a.yml"]) == dp.EXIT_OK


def test_שני_workflows_שניהם_נורים(monkeypatch, env):
    seen = []

    def fake(req, *a, **k):
        seen.append(req.full_url)
        return _Resp(204)

    monkeypatch.setattr(dp.urllib.request, "urlopen", fake)
    assert dp.main(["--workflow", "a.yml", "--workflow", "b.yml"]) == dp.EXIT_OK
    assert len(seen) == 2
    assert seen[0].endswith("/workflows/a.yml/dispatches")


def test_ברירת_המחדל_יורה_את_שני_ה_workflows_של_הצינור(monkeypatch, env):
    seen = []
    monkeypatch.setattr(dp.urllib.request, "urlopen",
                        lambda req, *a, **k: (seen.append(req.full_url), _Resp(204))[1])
    assert dp.main([]) == dp.EXIT_OK
    assert len(seen) == len(dp.DEFAULT_WORKFLOWS) == 2
    # הסגירה חייבת להיות ברשימה — היא הדבר שנפל ב-01/09.
    assert any("auto_close_expiries.yml" in u for u in seen)
    assert any("auto_trade_daily.yml" in u for u in seen)


# --------------------------------------------------- כישלון חייב להיות רועש

@pytest.mark.parametrize("code", [200, 201, 202])
def test_קוד_2xx_שאינו_204_נחשב_כישלון(monkeypatch, env, code):
    """204 הוא ההצלחה היחידה. 2xx אחר = ה-API השתנה תחתינו, לא הצלחה."""
    monkeypatch.setattr(dp.urllib.request, "urlopen", lambda *a, **k: _Resp(code))
    assert dp.main(["--workflow", "a.yml"]) == dp.EXIT_ERROR


@pytest.mark.parametrize("code", [401, 403, 404, 422, 500])
def test_שגיאת_HTTP_מחזירה_exit_שונה_מאפס(monkeypatch, env, code):
    def boom(*a, **k):
        raise urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(b""))

    monkeypatch.setattr(dp.urllib.request, "urlopen", boom)
    assert dp.main(["--workflow", "a.yml"]) == dp.EXIT_ERROR


def test_כשל_רשת_מחזיר_exit_שונה_מאפס(monkeypatch, env):
    def boom(*a, **k):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(dp.urllib.request, "urlopen", boom)
    assert dp.main(["--workflow", "a.yml"]) == dp.EXIT_ERROR


def test_כשל_חלקי_הוא_כשל(monkeypatch, env, capsys):
    """1 מתוך 2 = חצי צינור מת. exit 0 כאן היה מסתיר את זה."""
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp(204)
        raise urllib.error.HTTPError("u", 403, "forbidden", {}, io.BytesIO(b""))

    monkeypatch.setattr(dp.urllib.request, "urlopen", fake)
    assert dp.main(["--workflow", "a.yml", "--workflow", "b.yml"]) == dp.EXIT_ERROR
    assert "1/2 נורו" in capsys.readouterr().out


def test_בלי_token_יוצא_בקוד_תצורה_ולא_פונה_לרשת(monkeypatch, capsys):
    monkeypatch.delenv("GH_DISPATCH_TOKEN", raising=False)

    def must_not_call(*a, **k):
        raise AssertionError("פנה לרשת בלי token")

    monkeypatch.setattr(dp.urllib.request, "urlopen", must_not_call)
    assert dp.main(["--workflow", "a.yml"]) == dp.EXIT_CONFIG
    assert "GH_DISPATCH_TOKEN" in capsys.readouterr().out


def test_token_ריק_או_רווחים_נחשב_חסר(monkeypatch):
    monkeypatch.setenv("GH_DISPATCH_TOKEN", "   ")
    monkeypatch.setattr(dp.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("פנה לרשת בלי token"))
    assert dp.main(["--workflow", "a.yml"]) == dp.EXIT_CONFIG


# ------------------------------------------------------------------ הסוד

def test_ה_token_לעולם_אינו_נרשם_ללוג(monkeypatch, env, capsys):
    """גם במסלול הכושל — הודעת השגיאה לא תדליף את ה-PAT."""
    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 401, "unauthorized", {}, io.BytesIO(b""))

    monkeypatch.setattr(dp.urllib.request, "urlopen", boom)
    dp.main(["--workflow", "a.yml"])
    out = capsys.readouterr().out
    assert TOKEN not in out
    assert "ghp_" not in out


def test_ה_token_נשלח_ככותרת_Bearer(monkeypatch, env):
    seen = {}
    monkeypatch.setattr(dp.urllib.request, "urlopen",
                        lambda req, *a, **k: (seen.update(req.headers), _Resp(204))[1])
    dp.main(["--workflow", "a.yml"])
    # urllib מנרמל שמות כותרות ל-Title-Case
    assert seen.get("Authorization") == f"Bearer {TOKEN}"


# ------------------------------------------------------------------ dry-run

def test_dry_run_אינו_פונה_לרשת_ואינו_דורש_token(monkeypatch, capsys):
    monkeypatch.delenv("GH_DISPATCH_TOKEN", raising=False)
    monkeypatch.setattr(dp.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("dry-run פנה לרשת"))
    assert dp.main(["--dry-run", "--workflow", "a.yml"]) == dp.EXIT_OK
    assert "DRY-RUN" in capsys.readouterr().out


def test_ברירת_המחדל_אינה_dry_run(monkeypatch, env):
    """נעילה על ההיפוך המכוון מקונבנציית ה-repo: טריגר שברירת המחדל שלו
    היא no-op הוא נפילה שקטה. אם מישהו יהפוך את זה — הבדיקה תיפול."""
    fired = []
    monkeypatch.setattr(dp.urllib.request, "urlopen",
                        lambda req, *a, **k: (fired.append(1), _Resp(204))[1])
    dp.main(["--workflow", "a.yml"])
    assert fired, "ברירת המחדל לא ירתה — הטריגר הפך ל-no-op שקט"


# ------------------------------------------------------------------ ref/repo

def test_ref_ו_repo_ניתנים_לעקיפה(monkeypatch, env):
    seen = {}

    def fake(req, *a, **k):
        seen["url"] = req.full_url
        seen["body"] = req.data.decode()
        return _Resp(204)

    monkeypatch.setattr(dp.urllib.request, "urlopen", fake)
    dp.main(["--repo", "o/r", "--ref", "dev", "--workflow", "a.yml"])
    assert "/repos/o/r/actions/workflows/a.yml/dispatches" in seen["url"]
    assert '"ref": "dev"' in seen["body"]
