"""Bulk evidence retains secret isolation without per-field setup work."""

import json
import time
from urllib.parse import quote, quote_plus

import pytest

from biomedmcp import logging_safety, provider_credentials
from biomedmcp.evidence import bound
from biomedmcp.receipts import _safe_request
from biomedmcp.snapshot_codec import pack


def sanitize(kind, value):
    if kind == 'evidence':
        return bound(value, rows=1000)[0]
    if kind == 'request':
        return _safe_request(value)[0]
    if kind == 'snapshot':
        return pack(value)[1]
    return logging_safety.redact_event(None, None, value)


@pytest.mark.parametrize('kind', ['evidence', 'request', 'snapshot', 'event'])
def test_bulk_redaction_setup_is_bounded_and_nested_secrets_remain_hidden(monkeypatch, kind):
    secret = 'synthetic-bulk-secret/a+space value'
    monkeypatch.setenv('BULK_TEST_SECRET', secret)
    calls = []
    original = logging_safety.quote

    def counted(value, **kwargs):
        if value == secret:
            calls.append(value)
        return original(value, **kwargs)

    monkeypatch.setattr(logging_safety, 'quote', counted)
    values = [secret, quote(secret, safe=''), quote_plus(secret), 'api_key=unregistered-value']
    result = sanitize(kind, {'rows': [{'value': values, 'password': secret} for _ in range(200)]})
    serialized = json.dumps(result)
    assert all(value not in serialized for value in values)
    assert '[REDACTED]' in serialized
    assert len(calls) <= 1, 'Secret encoding setup must be per traversal, not per field'


@pytest.mark.parametrize('kind', ['evidence', 'request', 'snapshot', 'event'])
def test_bulk_redaction_observes_environment_rotation_between_traversals(monkeypatch, kind):
    first, second = 'synthetic-first-secret', 'synthetic-second-secret'
    monkeypatch.setenv('BULK_TEST_SECRET', first)
    assert sanitize(kind, {'value': first})['value'] == '[REDACTED]'
    monkeypatch.setenv('BULK_TEST_SECRET', second)
    assert sanitize(kind, {'value': second})['value'] == '[REDACTED]'
    monkeypatch.delenv('BULK_TEST_SECRET')
    assert sanitize(kind, {'value': second})['value'] == second


@pytest.mark.parametrize('kind', ['evidence', 'request', 'snapshot', 'event'])
def test_bulk_redaction_does_not_reuse_another_accounts_provider_keys(kind):
    first, second = 'synthetic-provider-first', 'synthetic-provider-second'

    def snapshot(secret, partition):
        return provider_credentials.RequestCredentials(
            partition=partition, deadline=time.monotonic() + 60,
            values={'ncbi': secret}, pacing={'ncbi': partition + ':n', 'openfda': partition + ':f'},
        )

    with provider_credentials.credential_context(snapshot(first, 'first')):
        assert sanitize(kind, {'value': first})['value'] == '[REDACTED]'
        with provider_credentials.credential_context(snapshot(second, 'second')):
            assert sanitize(kind, {'value': second})['value'] == '[REDACTED]'
            assert sanitize(kind, {'value': first})['value'] == first
        assert sanitize(kind, {'value': first})['value'] == '[REDACTED]'
    assert sanitize(kind, {'value': first})['value'] == first
