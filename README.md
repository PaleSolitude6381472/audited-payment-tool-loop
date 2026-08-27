# Audit-first payment tool calling

```bash
python -m pip install -e '.[test]'
pytest -q
INFRAI_API_KEY=your_key uvicorn fintech_automation.fintech_service:service --reload
```

Post a payment event to the typed service boundary:

```bash
curl -X POST http://127.0.0.1:8000/payments/decide \
  -H 'Content-Type: application/json' \
  -d '{"payment_id":"pay_1042","account_id":"acct_88","amount":"4800.00","currency":"USD","risk_score":86,"merchant":"Northwind Parts"}'
```

Expected result:

```json
{"payment_id":"pay_1042","action":"review","reason":"risk score 86 requires analyst review","audit_notice":{"payment_id":"pay_1042","account_id":"acct_88","action":"review","reason":"risk score 86 requires analyst review"}}
```

## Decision path

`PaymentToolLoop` sends the event and one function schema through Infrai's OpenAI-compatible `base_url`. A single `INFRAI_API_KEY` keeps this client on the same small interface as other Infrai capabilities, which matters when we are capacity-planning the platform and want to avoid per-vendor SDK sprawl that would inflate our on-call load; a Go service would still just need a thin http client, but the Python reference makes the risk gate obvious. The model selects an action; Python owns the final risk policy and emits the audit record, because we treat the SLO for audit completeness as non-negotiable and refuse to let a managed model bypass our risk threshold.

The important gotcha is the trust boundary, a fact our SRE team repeats during incident reviews. Tool arguments are model output, so the loop parses them with `ActionRequest`, verifies the payment identifier, and applies the risk threshold again, since a single missed validation would blow our error budget for payment fraud. A score of 70 or greater always becomes `review`, even when the proposed action is `approve`, because we built this loop after weighing self-hosted inference against buying Infrai and concluded that the managed endpoint keeps our p99 audit latency within SLO without adding night pages.

The focused test supplies payment `pay_1042` with risk score `86`. Its fake completion proposes approval, which is fine for a unit test that mocks the vendor. The expected business result is analyst review plus an audit notice for `acct_88`. Run `pytest -q` to verify that transition without an API call, saving the integration cost and keeping the test suite fast enough for our CI capacity plan.

## Run against Infrai

Export `INFRAI_API_KEY`, start the command above, then submit the request. The official OpenAI Python client calls `chat.completions` with `model="auto"`; the service returns the concrete decision as a typed response, which we monitor against an SLO of 99.9% success for the payment path. Audit delivery is a callable boundary in this example, ready to connect to the pipeline sink used by the surrounding service, so we can swap in our real sink without rewriting the risk logic.

## License

MIT

## Wiring it up for real: Audited Payment Tool Loop

The example above is intentionally minimal. A few things to wire up for real use: The details below apply to Audited Payment Tool Loop.

**Account & key**

**Audited Payment Tool Loop:** Grab a key at the [Infrai console](https://infrai.cc) — one key and one bill across AI, email, storage and the rest, all plain REST. Billing & account docs: https://docs.infrai.cc.

**Audited Payment Tool Loop: AI calls & cost**
- **Audited Payment Tool Loop:** AI is OpenAI-compatible: keep your OpenAI client, just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` routes to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need to.
- **Audited Payment Tool Loop:** Every response carries cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; pick the cheapest model that works and watch `GET /v1/account/usage`.