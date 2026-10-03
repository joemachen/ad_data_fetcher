"""
Per-fetcher retry rules: which errors are transient (retried) vs permanent (fail fast),
and the Reddit/TikTok HTTP request loops end to end with a fake urlopen.
"""
import io
import json
import logging
import sys
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import grpc
import pytest
from facebook_business.exceptions import FacebookRequestError
from google.ads.googleads.errors import GoogleAdsException
from google.api_core import exceptions as api_exceptions

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api_fetcher
import meta_fetcher
import microsoft_fetcher
import reddit_fetcher
import tiktok_fetcher

# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------


def _google_exc(status: grpc.StatusCode) -> GoogleAdsException:
    error = SimpleNamespace(code=lambda: status)
    return GoogleAdsException(error, None, None, "req-123")


@pytest.mark.parametrize(
    "status, expected",
    [
        (grpc.StatusCode.UNAVAILABLE, True),
        (grpc.StatusCode.RESOURCE_EXHAUSTED, True),
        (grpc.StatusCode.DEADLINE_EXCEEDED, True),
        (grpc.StatusCode.INTERNAL, True),
        (grpc.StatusCode.INVALID_ARGUMENT, False),
        (grpc.StatusCode.PERMISSION_DENIED, False),
        (grpc.StatusCode.UNAUTHENTICATED, False),
    ],
)
def test_google_grpc_status_classification(status, expected):
    assert api_fetcher._is_transient(_google_exc(status)) is expected


def test_google_api_core_errors():
    assert api_fetcher._is_transient(api_exceptions.ServiceUnavailable("down")) is True
    assert api_fetcher._is_transient(api_exceptions.MethodNotImplemented("501 sunset API")) is False
    assert api_fetcher._is_transient(ValueError("bad")) is False


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


def _meta_exc(code: int, is_transient: bool = False) -> FacebookRequestError:
    body = json.dumps({"error": {"code": code, "message": "m", "is_transient": is_transient}})
    return FacebookRequestError("m", {}, 400, {}, body)


@pytest.mark.parametrize("code", [1, 2, 4, 17, 32, 613])
def test_meta_rate_limit_codes_are_transient(code):
    assert meta_fetcher._is_transient(_meta_exc(code)) is True


def test_meta_is_transient_flag_respected():
    assert meta_fetcher._is_transient(_meta_exc(100, is_transient=True)) is True


def test_meta_token_expiry_and_bad_requests_not_retried():
    assert meta_fetcher._is_transient(_meta_exc(190, is_transient=True)) is False
    assert meta_fetcher._is_transient(_meta_exc(100)) is False
    assert meta_fetcher._is_transient(ValueError("x")) is False


# ---------------------------------------------------------------------------
# Microsoft
# ---------------------------------------------------------------------------


def _ms_fault(*errors, kind: str = "AdApiFaultDetail") -> microsoft_fetcher.WebFault:
    items = [SimpleNamespace(Code=c, ErrorCode=n, Message=m) for c, n, m in errors]
    one_or_list = items[0] if len(items) == 1 else items
    if kind == "AdApiFaultDetail":
        detail = SimpleNamespace(AdApiFaultDetail=SimpleNamespace(Errors=SimpleNamespace(AdApiError=one_or_list)))
    else:
        detail = SimpleNamespace(
            ApiFaultDetail=SimpleNamespace(OperationErrors=SimpleNamespace(OperationError=one_or_list))
        )
    return microsoft_fetcher.WebFault(SimpleNamespace(detail=detail, faultstring="fault"), None)


def test_ms_rate_limit_and_internal_error_are_transient():
    assert microsoft_fetcher._is_transient(_ms_fault(("117", "CallRateExceeded", "slow down"))) is True
    assert microsoft_fetcher._is_transient(_ms_fault(("0", "InternalError", "oops"), kind="ApiFaultDetail")) is True


def test_ms_invalid_client_data_not_retried():
    fault = _ms_fault(("2004", "ReportingServiceInvalidCustomDateRangeEnd", "End date is in the future."))
    assert microsoft_fetcher._is_transient(fault) is False
    assert microsoft_fetcher.fault_errors(fault) == [
        ("2004", "ReportingServiceInvalidCustomDateRangeEnd", "End date is in the future.")
    ]
    assert "2004" in microsoft_fetcher._describe_error(fault)


def test_ms_network_errors_are_transient():
    assert microsoft_fetcher._is_transient(ConnectionError("reset")) is True
    assert microsoft_fetcher._is_transient(TimeoutError()) is True
    assert microsoft_fetcher._is_transient(ValueError("bad csv")) is False


# ---------------------------------------------------------------------------
# Reddit / TikTok request loops (fake urlopen, recorded sleeps)
# ---------------------------------------------------------------------------


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code: int, retry_after: str = "") -> urllib.error.HTTPError:
    headers = Message()
    if retry_after:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://api.test", code, "err", headers, io.BytesIO(b""))


@pytest.fixture
def script_urlopen(monkeypatch):
    """Replace urlopen with a scripted sequence and record time.sleep calls."""
    sleeps = []
    monkeypatch.setattr(reddit_fetcher.time, "sleep", sleeps.append)

    def install(outcomes):
        calls = []

        def fake_urlopen(req, timeout=None):
            outcome = outcomes[len(calls)]
            calls.append(req)
            if isinstance(outcome, BaseException):
                raise outcome
            return _FakeResponse(json.dumps(outcome).encode())

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        return calls

    return install, sleeps


def _reddit():
    f = object.__new__(reddit_fetcher.RedditAdsFetcher)
    f.logger = logging.getLogger("test.reddit")
    f._access_token = "tok"
    f._v3_me_cached = None
    f._headers = lambda: {"Authorization": "Bearer tok"}
    return f


def _tiktok():
    f = object.__new__(tiktok_fetcher.TikTokAdsFetcher)
    f.logger = logging.getLogger("test.tiktok")
    f._access_token = "tok"
    f._get_access_token = lambda: "tok"
    return f


@pytest.mark.parametrize("make", [_reddit, _tiktok])
def test_http_503_then_success(make, script_urlopen):
    install, sleeps = script_urlopen
    calls = install([_http_error(503), {"code": 0, "data": {"ok": True}}])
    assert make()._api_request("https://api.test/x")["data"] == {"ok": True}
    assert len(calls) == 2 and len(sleeps) == 1 and 0 <= sleeps[0] < 2


@pytest.mark.parametrize("make", [_reddit, _tiktok])
def test_http_429_honours_retry_after(make, script_urlopen):
    install, sleeps = script_urlopen
    install([_http_error(429, "7"), {"code": 0, "data": {}}])
    make()._api_request("https://api.test/x")
    assert sleeps == [7.0]


@pytest.mark.parametrize("make", [_reddit, _tiktok])
def test_http_400_not_retried(make, script_urlopen):
    install, sleeps = script_urlopen
    calls = install([_http_error(400), {"never": True}])
    with pytest.raises(urllib.error.HTTPError):
        make()._api_request("https://api.test/x")
    assert len(calls) == 1 and sleeps == []


def test_tiktok_rate_limit_body_code_retried(script_urlopen):
    install, sleeps = script_urlopen
    calls = install([{"code": 40100, "message": "Too many requests", "request_id": "r1"}, {"code": 0, "data": {}}])
    assert _tiktok()._api_request("https://api.test/x") == {"code": 0, "data": {}}
    assert len(calls) == 2 and len(sleeps) == 1


def test_tiktok_permanent_body_code_raises_with_details(script_urlopen):
    install, sleeps = script_urlopen
    install([{"code": 40002, "message": "No permission", "request_id": "r2"}])
    with pytest.raises(tiktok_fetcher.TikTokApiError) as info:
        _tiktok()._api_request("https://api.test/x")
    assert info.value.code == 40002 and info.value.request_id == "r2" and sleeps == []
