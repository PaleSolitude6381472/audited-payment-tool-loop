"""HTTP boundary for payment automation requests."""

from fastapi import FastAPI

from .payment_operator import PaymentEvent, PaymentOutcome, PaymentToolLoop

service = FastAPI(title="Audited payment tool loop")


@service.post("/payments/decide", response_model=PaymentOutcome)
def decide_payment(event: PaymentEvent) -> PaymentOutcome:
    return PaymentToolLoop().run(event)

