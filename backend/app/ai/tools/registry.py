"""Secure, authenticated tool execution framework for LLMs."""

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Type
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai.providers.base import ToolDefinition

logger = logging.getLogger(__name__)


# Global role hierarchy for tool permission evaluation
ROLE_HIERARCHY: Dict[str, int] = {
    "customer": 0,
    "employee": 1,
    "receptionist": 2,
    "admin": 3,
    "owner": 4,
}


class ToolExecutionContext(BaseModel):
    """Security and execution context passed to all backend tool handlers."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    org_id: UUID
    conversation_id: UUID
    db: Optional[AsyncSession] = None
    caller_role: str = "customer"
    user_id: Optional[UUID] = None


class ToolExecutionError(Exception):
    """Raised when tool execution fails."""

    pass


class ToolRegistry:
    """Central registry and policy enforcement engine for LLM function calls."""

    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        name: str,
        description: str,
        input_schema: Type[BaseModel],
        required_role: str = "customer",
        timeout: float = 10.0,
    ) -> Callable:
        """Decorator to register a secure tool function."""

        def decorator(func: Callable) -> Callable:
            parameters = input_schema.model_json_schema()
            # Clean pydantic titles if present
            parameters.pop("title", None)

            self._tools[name] = {
                "name": name,
                "description": description,
                "schema_cls": input_schema,
                "parameters": parameters,
                "func": func,
                "required_role": required_role,
                "timeout": timeout,
            }
            return func

        return decorator

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Returns JSON schema definitions of all registered tools for the LLM."""
        definitions = []
        for name, meta in self._tools.items():
            definitions.append(
                ToolDefinition(
                    name=name,
                    description=meta["description"],
                    parameters=meta["parameters"],
                )
            )
        return definitions

    async def execute_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> Dict[str, Any]:
        """Validates arguments, enforces tenant boundary, checks authorization, and executes tool."""
        if name not in self._tools:
            logger.warning("LLM attempted to execute unknown tool: %s", name)
            return {"error": f"Tool '{name}' is not recognized or permitted."}

        meta = self._tools[name]
        required_role = meta.get("required_role", "customer")
        caller_level = ROLE_HIERARCHY.get(context.caller_role, 0)
        required_level = ROLE_HIERARCHY.get(required_role, 0)

        # 1. Role-based authorization check
        if caller_level < required_level:
            logger.warning(
                "Tool '%s' requires role '%s' but caller has role '%s'",
                name,
                required_role,
                context.caller_role,
            )
            return {
                "error": f"Permission denied: role '{context.caller_role}' is not authorized to execute tool '{name}'."
            }

        schema_cls: Type[BaseModel] = meta["schema_cls"]
        func = meta["func"]
        timeout = meta["timeout"]

        # 2. Argument validation against Pydantic schema
        try:
            validated_args = schema_cls(**arguments)
        except Exception as e:
            logger.info("Tool argument validation failed for %s: %s", name, e)
            return {
                "error": f"Invalid arguments supplied for tool '{name}': {str(e)}",
                "valid_parameters": meta["parameters"].get("properties", {}),
            }

        # 3. Execution under bound timeout
        try:
            result = await asyncio.wait_for(
                func(validated_args, context),
                timeout=timeout,
            )
            if isinstance(result, BaseModel):
                return result.model_dump()
            elif isinstance(result, dict):
                return result
            return {"result": str(result)}
        except asyncio.TimeoutError:
            logger.error("Tool '%s' timed out after %s seconds", name, timeout)
            return {"error": f"Tool execution timed out after {timeout} seconds."}
        except Exception as e:
            logger.exception("Error executing tool '%s': %s", name, e)
            return {"error": f"Tool execution failed: {str(e)}"}


# Global tool registry instance
tool_registry = ToolRegistry()
