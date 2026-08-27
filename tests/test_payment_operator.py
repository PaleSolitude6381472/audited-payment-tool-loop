import json
from types import SimpleNamespace

from fintech_automation.payment_operator import PaymentEvent, PaymentToolLoop


class FakeCompletions:
    def create(self, **request):
        assert request["model"] == "auto"
        assert request["parallel_tool_calls"] is False
        arguments = json.dumps(
            {
                "payment_id": "pay_1042",
                "action": "approve",
                "reason": "model selected straight-through processing",
            }
        )
        call = SimpleNamespace(
            function=SimpleNamespace(name="decide_payment", arguments=arguments)
        )
        message = SimpleNamespace(tool_calls=[call])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_high_risk_payment_is_reviewed_and_audited():
    notices = []
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    event = PaymentEvent(
        payment_id="pay_1042",
        account_id="acct_88",
        amount="4800.00",
        currency="USD",
        risk_score=86,
        merchant="Northwind Parts",
    )

    outcome = PaymentToolLoop(client=client, notice_sink=notices.append).run(event)

    assert outcome.action == "review"
    assert outcome.reason == "risk score 86 requires analyst review"
    assert notices == [outcome.audit_notice]
    assert notices[0].account_id == "acct_88"
