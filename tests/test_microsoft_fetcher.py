"""
Tests for microsoft_fetcher.MicrosoftAdsFetcher token-rotation persistence.

Microsoft rotates the OAuth refresh token on every refresh. The fetcher must write the
new refresh_token back to microsoft-ads.yaml so the 90-day inactivity window resets each
run (otherwise the token eventually expires with AADSTS700082).
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from suds import WebFault

# Allow importing from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import microsoft_fetcher
from microsoft_fetcher import MicrosoftAdsFetcher
from utils import TokenExpiredError


class _FakeTokens:
    def __init__(self, access_token, refresh_token):
        self.access_token = access_token
        self.refresh_token = refresh_token


class _FakeAuth:
    """Stands in for OAuthDesktopMobileAuthCodeGrant; returns a rotated refresh token."""

    def __init__(self, returned_refresh):
        self._returned_refresh = returned_refresh

    def request_oauth_tokens_by_refresh_token(self, refresh_token):
        return _FakeTokens(access_token="fake-access", refresh_token=self._returned_refresh)


class _FakeAuthRaises:
    """Stands in for the SDK auth when the refresh token is expired/invalid."""

    def request_oauth_tokens_by_refresh_token(self, refresh_token):
        raise Exception("AADSTS700082: The refresh token has expired due to inactivity.")


@pytest.fixture
def ms_config(tmp_path, monkeypatch):
    """Point the fetcher's app dir at tmp_path and write a baseline microsoft-ads.yaml."""
    monkeypatch.setattr(microsoft_fetcher, "_APP_DIR", tmp_path)
    monkeypatch.setattr(microsoft_fetcher, "_BINGADS_AVAILABLE", True)
    monkeypatch.setattr(microsoft_fetcher, "AuthorizationData", lambda **kw: object())
    yaml_path = tmp_path / "microsoft-ads.yaml"
    yaml_path.write_text(
        yaml.dump(
            {
                "client_id": "cid",
                "refresh_token": "OLD_TOKEN",
                "developer_token": "devtok",
            }
        ),
        encoding="utf-8",
    )
    return tmp_path, yaml_path


def _build_fetcher(tmp_path, returned_refresh, monkeypatch):
    monkeypatch.setattr(
        microsoft_fetcher,
        "OAuthDesktopMobileAuthCodeGrant",
        lambda **kw: _FakeAuth(returned_refresh),
    )
    return MicrosoftAdsFetcher(customer_id="12345", output_dir=str(tmp_path / "out"))


def test_rotated_refresh_token_is_persisted(ms_config, monkeypatch):
    tmp_path, yaml_path = ms_config
    _build_fetcher(tmp_path, returned_refresh="NEW_TOKEN", monkeypatch=monkeypatch)

    saved = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert saved["refresh_token"] == "NEW_TOKEN"
    # Other keys must be preserved, not reconstructed.
    assert saved["client_id"] == "cid"
    assert saved["developer_token"] == "devtok"


def test_unchanged_refresh_token_does_not_rewrite(ms_config, monkeypatch):
    tmp_path, yaml_path = ms_config
    before_mtime = yaml_path.stat().st_mtime_ns
    _build_fetcher(tmp_path, returned_refresh="OLD_TOKEN", monkeypatch=monkeypatch)

    # Same token returned -> no write.
    assert yaml_path.stat().st_mtime_ns == before_mtime
    saved = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert saved["refresh_token"] == "OLD_TOKEN"


def test_expired_refresh_raises_token_expired_error(ms_config, monkeypatch):
    """An expired refresh token must surface as utils.TokenExpiredError (so the GUI can
    show the per-platform Re-authenticate button), not a bare RuntimeError."""
    tmp_path, _ = ms_config
    monkeypatch.setattr(
        microsoft_fetcher,
        "OAuthDesktopMobileAuthCodeGrant",
        lambda **kw: _FakeAuthRaises(),
    )
    with pytest.raises(TokenExpiredError) as exc_info:
        MicrosoftAdsFetcher(customer_id="12345", output_dir=str(tmp_path / "out"))
    assert exc_info.value.platform == "Microsoft"


def test_save_failure_is_soft(ms_config, monkeypatch):
    """A write failure during persistence must be logged, not raised."""
    tmp_path, yaml_path = ms_config
    fetcher = _build_fetcher(tmp_path, returned_refresh="NEW_TOKEN", monkeypatch=monkeypatch)

    # Point the save target at a directory that does not exist so open() raises.
    monkeypatch.setattr(microsoft_fetcher, "_APP_DIR", tmp_path / "missing_dir")
    fetcher.config["refresh_token"] = "ANOTHER_TOKEN"
    # Must not raise.
    fetcher._save_config_safe()


# --------------------------------------------------------------------------- #
# fetch_month_data: date clamping and SOAP fault handling
# --------------------------------------------------------------------------- #

class _FakeManager:
    """Stands in for ReportingServiceManager; writes a small CSV or raises a preset error."""

    raise_exc = None
    calls = 0

    def __init__(self, **kw):
        self.service_client = SimpleNamespace(factory=object())

    def download_file(self, params):
        type(self).calls += 1
        if type(self).raise_exc is not None:
            raise type(self).raise_exc
        path = Path(params.result_file_directory) / params.result_file_name
        path.write_text(
            "Campaign Name,Impressions,Clicks,Spend,All conversions,All revenue\nC1,10,2,1.5,1,20\n",
            encoding="utf-8",
        )
        return str(path)


@pytest.fixture
def ms_fetcher(ms_config, monkeypatch):
    """A fetcher wired to _FakeManager, recording the dates passed to _build_report_request."""
    tmp_path, _ = ms_config
    fetcher = _build_fetcher(tmp_path, returned_refresh="OLD_TOKEN", monkeypatch=monkeypatch)
    _FakeManager.raise_exc = None
    _FakeManager.calls = 0
    monkeypatch.setattr(microsoft_fetcher, "ReportingServiceManager", _FakeManager)
    monkeypatch.setattr(microsoft_fetcher, "ReportingDownloadParameters", lambda **kw: SimpleNamespace(**kw))
    built = []
    monkeypatch.setattr(fetcher, "_build_report_request", lambda factory, s, e: built.append((s, e)) or object())
    sleeps = []
    monkeypatch.setattr(microsoft_fetcher.time, "sleep", lambda s: sleeps.append(s))
    return fetcher, built, sleeps


def _today():
    return datetime.combine(datetime.now().date(), datetime.min.time())


def test_future_end_date_is_clamped_to_today(ms_fetcher):
    """Microsoft rejects a CustomDateRangeEnd after today ('Invalid client data'); clamp it."""
    fetcher, built, _ = ms_fetcher
    start = _today() - timedelta(days=5)
    df = fetcher.fetch_month_data(start, _today() + timedelta(days=20))

    assert df is not None and list(df["Campaign"]) == ["C1"]
    assert built == [(start, _today())]
    assert fetcher.last_error is None


def test_future_start_date_returns_none_with_error(ms_fetcher):
    fetcher, built, _ = ms_fetcher
    df = fetcher.fetch_month_data(_today() + timedelta(days=1), _today() + timedelta(days=10))

    assert df is None
    assert built == []
    assert "in the future" in fetcher.last_error


def _ad_api_fault(code, error_code, message):
    detail = SimpleNamespace(
        AdApiFaultDetail=SimpleNamespace(
            Errors=SimpleNamespace(AdApiError=SimpleNamespace(Code=code, ErrorCode=error_code, Message=message))
        )
    )
    return WebFault(SimpleNamespace(faultstring="Invalid client data.", detail=detail), None)


def test_format_ms_fault_includes_detail_codes():
    e = _ad_api_fault(2015, "SomeErrorCode", "Explains what is wrong.")
    assert microsoft_fetcher._format_ms_fault(e) == "SomeErrorCode (2015): Explains what is wrong."


def test_format_ms_fault_falls_back_to_str():
    assert microsoft_fetcher._format_ms_fault(RuntimeError("boom")) == "boom"


def test_client_fault_is_not_retried_and_sets_last_error(ms_fetcher):
    fetcher, _, sleeps = ms_fetcher
    _FakeManager.raise_exc = _ad_api_fault(2015, "SomeErrorCode", "Explains what is wrong.")

    df = fetcher.fetch_month_data(_today() - timedelta(days=5), _today())

    assert df is None
    assert _FakeManager.calls == 1
    assert sleeps == []
    assert fetcher.last_error == "SomeErrorCode (2015): Explains what is wrong."


def test_transient_error_is_retried(ms_fetcher):
    fetcher, _, sleeps = ms_fetcher
    _FakeManager.raise_exc = ConnectionError("network down")

    df = fetcher.fetch_month_data(_today() - timedelta(days=5), _today())

    assert df is None
    assert _FakeManager.calls == microsoft_fetcher.MAX_RETRIES
    assert len(sleeps) == microsoft_fetcher.MAX_RETRIES - 1
    assert fetcher.last_error == "network down"
