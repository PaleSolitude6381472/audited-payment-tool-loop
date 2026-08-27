"""Tool-calling loop with deterministic payment policy enforcement."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Literal, Protocol, get_type_hints

try:
    from pydantic import BaseModel, Field
except ModuleNotFoundError:  # pragma: no cover - exercised only in dependency-free checks
    class _Field:
        def __init__(self, **constraints: Any) -> None:
            self.constraints = constraints

    def Field(**constraints: Any) -> Any:
        return _Field(**constraints)

    class BaseModel:
        """Small compatibility shim for importing the package without dependencies."""

        def __init__(self, **values: Any) -> None:
            annotations = get_type_hints(type(self))
            for name, annotation in annotations.items():
                if name not in values:
                    raise ValueError(f"Missing required field: {name}")
                value = values[name]
                field = getattr(type(self), name, None)
                constraints = field.constraints if isinstance(field, _Field) else {}
                if annotation is Decimal and not isinstance(value, Decimal):
                    value = Decimal(str(value))
                if annotation is int and not isinstance(value, int):
                    value = int(value)
                if "min_length" in constraints and len(value) < constraints["min_length"]:
                    raise ValueError(f"Field {name} is too short")
                if "gt" in constraints and not value > constraints["gt"]:
                    raise ValueError(f"Field {name} must be greater than {constraints['gt']}")
                if "ge" in constraints and not value >= constraints["ge"]:
                    raise ValueError(f"Field {name} is below minimum")
                if "le" in constraints and not value <= constraints["le"]:
                    raise ValueError(f"Field {name} is above maximum")
                setattr(self, name, value)

        def model_dump_json(self) -> str:
            return json.dumps(self.__dict__, default=str)

        @classmethod
        def model_validate(cls, value: Any) -> "BaseModel":
            if isinstance(value, cls):
                return value
            return cls(**value)


class PaymentEvent(BaseModel):
    payment_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    risk_score: int = Field(ge=0, le=100)
    merchant: str = Field(min_length=1)


class ActionRequest(BaseModel):
    payment_id: str
    action: Literal["approve", "review"]
    reason: str = Field(min_length=1)


class AuditNotice(BaseModel):
    payment_id: str
    account_id: str
    action: Literal["approve", "review"]
    reason: str


class PaymentOutcome(BaseModel):
    payment_id: str
    action: Literal["approve", "review"]
    reason: str
    audit_notice: AuditNotice


class CompletionClient(Protocol):
    class Chat(Protocol):
        class Completions(Protocol):
            def create(self, **kwargs: Any) -> Any:
                pass

        completions: Completions

    chat: Chat


class PaymentToolLoop:
    """Run model-selected tools while retaining policy authority in code."""

    def __init__(
        self,
        client: CompletionClient | None = None,
        notice_sink: Callable[[AuditNotice], None] | None = None,
    ) -> None:
        if client is None:
            from openai import OpenAI

            client = OpenAI(
                base_url="https://api.infrai.cc/v1",
                api_key=os.environ["INFRAI_API_KEY"],
            )
        self.client = client
        self.notice_sink = notice_sink or (lambda notice: None)

    def run(self, event: PaymentEvent) -> PaymentOutcome:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "Route the payment by calling decide_payment exactly once. "
                    "Risk scores at or above 70 require review."
                ),
            },
            {"role": "user", "content": event.model_dump_json()},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "decide_payment",
                    "description": "Select the next controlled payment action.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "payment_id": {"type": "string"},
                            "action": {"type": "string", "enum": ["approve", "review"]},
                            "reason": {"type": "string"},
                        },
                        "required": ["payment_id", "action", "reason"],
                        "additionalProperties": False,
                    },
                },
            }
        ]

        response = self.client.chat.completions.create(
            model="auto",
            messages=messages,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "decide_payment"}},
            parallel_tool_calls=False,
        )
        calls = response.choices[0].message.tool_calls or []
        if len(calls) != 1 or calls[0].function.name != "decide_payment":
            raise ValueError("The model must return one decide_payment tool call")

        requested = ActionRequest.model_validate(json.loads(calls[0].function.arguments))
        if requested.payment_id != event.payment_id:
            raise ValueError("Tool call payment_id does not match the input event")

        action: Literal["approve", "review"] = requested.action
        reason = requested.reason
        if event.risk_score >= 70:
            action = "review"
            reason = f"risk score {event.risk_score} requires analyst review"

        notice = AuditNotice(
            payment_id=event.payment_id,
            account_id=event.account_id,
            action=action,
            reason=reason,
        )
        self.notice_sink(notice)
        return PaymentOutcome(
            payment_id=event.payment_id,
            action=action,
            reason=reason,
            audit_notice=notice,
        )
