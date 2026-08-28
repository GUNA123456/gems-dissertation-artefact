# Redis-kill demo — run sheet (the cascade demo, ~6 minutes)

*The foundation demo: proves failures propagate observably, hop by hop, with
the broken dependency named at every level. Run it FIRST — it is the
precondition every other demo builds on. All expected outputs below were
measured on live runs (2026-08-18 and 2026-08-20).*

## What this demo claims — say it before touching anything

**Claim:** cascading failure is real, and this testbed makes it fully
observable. **Not claimed:** prediction — this fault has no precursor, so the
model's tiles will stay green, and that is correct behaviour. Announce it:

> "This first demo isn't about my model — pod death has no precursor, so
> nothing can predict it, including mine. That's my contrast class. This demo
> shows the disease itself: a failure three layers deep reaching the customer
> in seconds. The next demo shows the early warning."

## T-2 min — pre-flight

```bash
ssh azureuser@51.11.129.130
kubectl get pods -n default                                          # 12/12 Running
kubectl get workflow,networkchaos,stresschaos,podchaos -n default    # empty
```
Optional browser tabs: storefront (:30080), Prometheus (:30900).
(NSG is IP-locked — if links time out, update the rules to today's IP.)

## Act 1 — health (~30s)

Paste the probe block (one paste, it is quote-safe):

```bash
CHK=$(kubectl get svc stylehub-checkout-service -o jsonpath='{.spec.clusterIP}')
CART=$(kubectl get svc stylehub-cart-service -o jsonpath='{.spec.clusterIP}')
ORDER='{"user_id":"demo","user_currency":"USD","email":"d@x.io","address":{"street_address":"1 Way","city":"NG","state":"NG","country":"UK","zip_code":1},"credit_card":{"credit_card_number":"4432-8015-6152-0454","credit_card_cvv":123,"credit_card_expiration_year":2028,"credit_card_expiration_month":12}}'
probe() {
  curl -s -o /dev/null -X POST http://$CART:8082/api/cart/add -H 'Content-Type: application/json' -d '{"user_id":"demo","item":{"product_id":"SH-001","quantity":1}}'
  curl -s -m 8 -X POST http://$CHK:8086/api/checkout -H 'Content-Type: application/json' -d "$ORDER" | head -c 120; echo
}
probe
```
Expected: `{"order": {"order_id": "ORD-SH-..."}}`

**Say:** "A real order, placed end to end — cart, catalogue, shipping,
payment, all healthy."

## Act 2 — the kill (~1 min)

```bash
kubectl scale deploy stylehub-redis --replicas=0
sleep 8 && probe
```
Expected: `{"detail":"cart-service unavailable (ReadTimeout) — order not placed"}`

**Say:** "I've deleted the database at the very bottom of the chain — three
hops from the user. Eight seconds later, checkout is refusing orders, and
look at the words: it *names* the broken dependency. In my first-round build,
this exact scenario returned a successful order with payment never taken —
half this project was making failure honest enough to study."

*(Optional browser beat: attempt checkout in the storefront — the
order-failed page renders live.)*

## Act 3 — the propagation trail (~2 min)

Prometheus (:30900), query: `service_dependency_errors_total`

Expected shape (numbers grow while redis stays dead):
```
cart-service  -> redis        largest   (hundreds; retries under traffic)
checkout      -> cart-service smaller   (~tens)
frontend      -> checkout     smallest  (~units)
```

**Say:** "Here is the cascade as data. Error volume *decreases* with distance
from the root cause — each layer folds many failures below it into fewer
above. That decreasing gradient pointing at redis is exactly the structure my
model's cause head learned to read. And notice: redis itself has no failing
metric anywhere — everything we know about its death, we know from its
neighbours."

*(If asked about the model tiles being green: the contrast-class answer from
the top of this sheet. If cart is probed directly and returns nothing (curl
`000`) rather than a named 503: a Service with zero endpoints blackholes
connections — the named errors live at the checkout hop, which is where the
probe looks.)*

## Act 4 — resurrection (~1.5 min)

```bash
kubectl scale deploy stylehub-redis --replicas=1
kubectl rollout status deploy/stylehub-redis
sleep 8 && probe
```
Expected: `{"order": ...}` — a successful order again.

**Say:** "Redis is back, and the application healed itself — no restarts
anywhere else, no manual repair. The cart's connection logic re-establishes
on the next request. From kill to full recovery: under two minutes, and every
step of it is in the metrics."

## Close + handoff

```bash
kubectl get pods -n default        # 12/12, restart counts unchanged except redis
```

**Handoff line:** "So that's the disease — fast, deep, and fully observable.
The obvious question is whether anything could have warned us. For *this*
fault class, nothing can. For the next one, watch the screen."
→ proceed to the cart-mem run sheet.

## Pitfalls

| Trap | Avoidance |
|---|---|
| empty-cart false failure | always use `probe` (it seeds the cart); browser checkout with an empty cart fails *correctly* and looks like a bug |
| expecting model alarms | pre-empted by the opening line; tiles stay green by design |
| probing cart directly during the kill | may hang/`000` (blackholed connections) — demonstrate at the checkout hop |
| forgetting to restore | Act 4 is part of the demo; the healing is evidence too |
| running it right before cart-mem | fine — the kill does NOT restart cart (no age suppression); only redis's own pod is touched |
