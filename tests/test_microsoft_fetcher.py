"""
Tests for microsoft_fetcher.MicrosoftAdsFetcher token-rotation persistence.

Microsoft rotates the OAuth refresh token on every refresh. The fetcher must write the
new refresh_token back to microsoft-ads.yaml so the 90-day inactivity window resets each
run (otherwise the token eventually expires with AADSTS700082).
"""
import sys
from pathlib import Path

import pytest
import yaml

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
