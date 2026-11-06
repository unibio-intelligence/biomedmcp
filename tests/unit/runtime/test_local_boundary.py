import pytest

from biomedmcp import local_boundary as boundary


def test_missing_hosted_package_cannot_downgrade_auth(monkeypatch):
    monkeypatch.delenv("UBI_PROFILE", raising=False)
    with pytest.raises(ValueError, match="Hosted"):
        boundary.AuthSettings.from_env(default_url="https://public.example")
    monkeypatch.setenv("UBI_PROFILE", "hosted")
    with pytest.raises(ValueError):
        boundary.build_auth(boundary.AuthSettings("local", "http://localhost"))
    with pytest.raises(ValueError):
        boundary.build_ledger("hosted")
    monkeypatch.setenv("UBI_PROFILE", "local")
    assert boundary.build_auth(boundary.AuthSettings.from_env(default_url="http://localhost")) is None
