"""Tenant isolation context primitives and automatic ORM query enforcement.

Provides request-scoped tenant isolation via ContextVar and automatic query filtering
via SQLAlchemy 2.0 with_loader_criteria event hooks.
"""

import uuid
from contextvars import ContextVar
from typing import Optional
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

_tenant_id_ctx: ContextVar[Optional[uuid.UUID]] = ContextVar(
    "tenant_id", default=None
)

_hook_registered: bool = False


class TenantContext:
    """Manages the current tenant context for the request lifecycle."""

    @staticmethod
    def set_current_tenant_id(tenant_id: Optional[uuid.UUID]) -> None:
        """Sets the active organization/tenant ID for current coroutine context."""
        _tenant_id_ctx.set(tenant_id)

    @staticmethod
    def get_current_tenant_id() -> Optional[uuid.UUID]:
        """Returns the active organization/tenant ID, or None if unauthenticated."""
        return _tenant_id_ctx.get()

    @staticmethod
    def require_tenant_id() -> uuid.UUID:
        """Returns the active tenant ID, raising ValueError if unset."""
        tenant_id = _tenant_id_ctx.get()
        if tenant_id is None:
            raise ValueError("Operation requires an active tenant context, but none was set.")
        return tenant_id

    @staticmethod
    def clear() -> None:
        """Clears the tenant context."""
        _tenant_id_ctx.set(None)


def register_tenant_isolation_hook() -> None:
    """Enforces multi-tenant query and mutation isolation at the SQLAlchemy ORM layer.

    1. SELECT: Automatically appends 'WHERE org_id = current_tenant_id' to all SELECT queries
       touching entities inheriting from TenantMixin.
    2. INSERT / UPDATE / DELETE: Validates on flush that entities cannot be assigned, modified,
       or deleted across tenants.
    """
    global _hook_registered
    if _hook_registered:
        return

    from backend.app.models.base import TenantMixin
    from backend.app.core.exceptions import TenantAccessForbiddenError

    @event.listens_for(Session, "do_orm_execute")
    def _apply_tenant_isolation(execute_state):
        if (
            execute_state.is_select
            and not execute_state.is_column_load
            and not execute_state.execution_options.get("ignore_tenant_isolation", False)
        ):
            tenant_id = TenantContext.get_current_tenant_id()
            if tenant_id is not None:
                execute_state.statement = execute_state.statement.options(
                    with_loader_criteria(
                        TenantMixin,
                        lambda cls: cls.org_id == tenant_id,
                        include_aliases=True,
                    )
                )

    @event.listens_for(Session, "before_flush")
    def _validate_tenant_mutation_on_flush(session, flush_context, instances):
        tenant_id = TenantContext.get_current_tenant_id()
        session_opts = getattr(session, "_execution_options", {})
        if tenant_id is None or session_opts.get("ignore_tenant_isolation", False):
            return

        for obj in session.new:
            if isinstance(obj, TenantMixin) and obj.org_id != tenant_id:
                raise TenantAccessForbiddenError(
                    f"Forbidden: Cannot create {obj.__class__.__name__} for tenant '{obj.org_id}'. Active tenant is '{tenant_id}'."
                )

        for obj in session.dirty:
            if isinstance(obj, TenantMixin) and obj.org_id != tenant_id:
                raise TenantAccessForbiddenError(
                    f"Forbidden: Cannot modify {obj.__class__.__name__} belonging to tenant '{obj.org_id}'. Active tenant is '{tenant_id}'."
                )

        for obj in session.deleted:
            if isinstance(obj, TenantMixin) and obj.org_id != tenant_id:
                raise TenantAccessForbiddenError(
                    f"Forbidden: Cannot delete {obj.__class__.__name__} belonging to tenant '{obj.org_id}'. Active tenant is '{tenant_id}'."
                )

    _hook_registered = True

    _hook_registered = True
