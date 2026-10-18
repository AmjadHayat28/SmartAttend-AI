"""Write audit log entries. Callers commit; the entry joins the caller's transaction
so the audit row and the change it describes succeed or fail together."""

import enum
import logging
from datetime import date, datetime, time
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from backend.app.models import AuditLog, User

log = logging.getLogger("smartclass.audit")


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    # Only trust X-Forwarded-For when running behind a known reverse proxy
    # (configure uvicorn --proxy-headers --forwarded-allow-ips accordingly).
    return request.client.host if request.client else None


def record_audit(
    db: Session,
    *,
    actor: User | None,
    action: str,
    entity: str,
    entity_id: Any = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    department_id: int | None = None,
    request: Request | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=actor.id if actor else None,
        department_id=department_id if department_id is not None else (actor.department_id if actor else None),
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        old_value=old_value,
        new_value=new_value,
        ip_address=client_ip(request),
        user_agent=(request.headers.get("user-agent", "")[:300] if request else None),
    )
    db.add(entry)
    # One line per audited action for the server log: who did what to which record — never the
    # old/new values (they can hold personal data). The full entry is in the audit_logs table.
    log.info("%s actor=%s role=%s entity=%s:%s ip=%s", action, actor.id if actor else None,
             actor.role.value if actor else None, entity, entity_id, entry.ip_address)
    return entry


_NEVER_LOG = {"password", "password_hash", "new_password", "current_password"}


def _json_safe(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return value


def snapshot(obj: Any, *fields: str) -> dict[str, Any]:
    """JSON-safe dict of selected attributes for old_value/new_value. Secrets are never included."""
    return {f: _json_safe(getattr(obj, f)) for f in fields if f not in _NEVER_LOG}


def changes(old: dict[str, Any], new: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reduce two snapshots to only the keys whose values differ."""
    keys = [k for k in new if old.get(k) != new.get(k)]
    return {k: old.get(k) for k in keys}, {k: new[k] for k in keys}
