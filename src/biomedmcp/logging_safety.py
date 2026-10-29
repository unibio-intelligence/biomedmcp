"""Defense-in-depth redaction before standard or structured log rendering."""

import logging
import os
import re
import traceback
from urllib.parse import quote, quote_plus

_QUERY_SECRET = re.compile(r"(?i)((?:api[_-]?key|access_token|token|client_secret|password)=)[^&\s\"'<>]+")
_ENV_SECRET = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|DSN|REDIS_URL)$")
_PUBLIC_EVIDENCE_GRANT = re.compile(r"public_[a-f0-9]{32}_[a-f0-9]{64}")


def redactor():
    """Prepare current secrets once for one synchronous traversal.

    Keep this snapshot local: the next traversal must see environment rotation
    and its own provider credential context, without a global secret cache.
    """
    from .provider_credentials import redaction_forms

    forms = set(redaction_forms())
    for name, secret in os.environ.items():
        if secret and _ENV_SECRET.search(name):
            forms.update((secret, quote(secret, safe=""), quote_plus(secret)))
    forms = tuple(sorted(forms, key=len, reverse=True))

    def clean(value: str) -> str:
        value = _QUERY_SECRET.sub(r"\1[REDACTED]", value)
        for form in forms:
            value = value.replace(form, "[REDACTED]")
        return value

    return clean


def redact(value: str) -> str:
    return redactor()(value)


def redact_event(logger, method, event):
    redact_value = redactor()

    def clean(value):
        if isinstance(value, str):
            return _PUBLIC_EVIDENCE_GRANT.sub("[PUBLIC_EVIDENCE_GRANT]", redact_value(value))
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        return value

    return clean(event)


def install_log_redaction():
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_ubi_redacts", False):
        return

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        redact_value = redactor()
        record.msg, record.args = _PUBLIC_EVIDENCE_GRANT.sub("[PUBLIC_EVIDENCE_GRANT]", redact_value(record.getMessage())), ()
        if record.exc_info:
            record.exc_text = _PUBLIC_EVIDENCE_GRANT.sub("[PUBLIC_EVIDENCE_GRANT]", redact_value("".join(traceback.format_exception(*record.exc_info))))
            record.exc_info = None
        if record.stack_info:
            record.stack_info = redact_value(record.stack_info)
        return record

    factory._ubi_redacts = True
    logging.setLogRecordFactory(factory)
