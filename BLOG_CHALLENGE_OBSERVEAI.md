# From Zero Observability Exposure to Building ObserveAI with SigNoz

_How a WeMakeDevs x SigNoz hackathon challenge pushed me to self-host SigNoz, send real telemetry, and finally understand traces, logs, metrics, dashboards, alerts, and MCP._

## Why I Started This

I saw the **Agents of SigNoz Hackathon by WeMakeDevs**, and it immediately caught my attention.

Until now, I had not had much hands-on exposure to observability. I had heard the usual words:

- logs
- metrics
- traces
- dashboards
- alerts
- OpenTelemetry
- SRE
- incident debugging

But I had not deeply understood how they all connect in a real system.

So before jumping directly into a hackathon idea, I decided to build a learning project first.

That project became:

```text
ObserveAI
```

ObserveAI is a local observability lab for understanding how production-style systems behave across microservices, Kafka-style async flows, basic AI services, OpenTelemetry, and SigNoz.

The goal was simple:

```text
Do not just read about observability.
Build a system, break it, send telemetry to SigNoz, and learn from the evidence.
```

## What I Built

ObserveAI is a small e-commerce-style system with a checkout flow.

The current architecture looks like this:

```text
Client / UI
  |
  v
ui-service
  |
  v
checkout-service
  |----> cart-service -> Redis
  |----> inventory-service
  |----> payment-service
  |----> PostgreSQL orders
  |
  v
Redpanda topic: fraud.check.requested
  |
  v
ai-fraud-service
  |
  v
Redpanda topic: fraud.check.completed
  |----> notification-service -> PostgreSQL notifications
  |
  v
analytics-service -> PostgreSQL analytics_events

All services -> OpenTelemetry Collector -> SigNoz
```

It includes:

- FastAPI microservices
- Redpanda as a Kafka-compatible broker
- PostgreSQL
- Redis
- a rules-based AI fraud service
- notification and analytics consumers
- OpenTelemetry traces, metrics, and logs
- a local OpenTelemetry Collector
- SigNoz as the observability platform
- a web UI to trigger scenarios and visualize the architecture
- failure scenarios for payment, inventory, Kafka lag, DLQ, AI fraud latency, database slowness, notification failures, and analytics lag

This is not meant to be a fancy product yet. It is a learning lab.

## Self-Hosting SigNoz

The first important step was running SigNoz locally.

I used a self-hosted SigNoz setup and connected ObserveAI to it through OpenTelemetry.

One thing I learned quickly: local observability setups can have port conflicts.

SigNoz uses common OTLP ports:

```text
4317 - OTLP/gRPC
4318 - OTLP/HTTP
8080 - SigNoz UI
```

So I changed ObserveAI to expose its app ports separately:

```text
checkout-service: http://localhost:18080
cart-service:     http://localhost:18081
ObserveAI UI:     http://localhost:18082
SigNoz UI:        http://localhost:8080
```

Another key learning was Docker networking.

At first, telemetry was not showing in SigNoz. The OpenTelemetry Collector was trying to export to the wrong place. After inspecting the SigNoz Docker network, I connected ObserveAI’s collector to the SigNoz network and exported telemetry to the SigNoz ingester.

That was the first “aha” moment:

```text
Observability starts before dashboards.
First, telemetry has to actually reach the backend.
```

## Sending Real Telemetry

Once the services were connected, I added a traffic generator.

The traffic generator continuously creates:

- normal checkouts
- slow payment requests
- payment failures
- provider timeout failures
- inventory failures
- slow database requests
- slow fraud-service requests
- Kafka consumer lag scenarios
- poison messages that go to DLQ
- notification slow/failure scenarios
- analytics slow scenarios
- cart-backed checkouts

This made SigNoz much more useful.

Without continuous traffic, the observability platform becomes quiet. With continuous traffic, I could actually see:

- services appearing in SigNoz
- traces flowing in
- latency changing
- error spans increasing
- logs connecting back to trace IDs
- dashboard panels getting data
- alert queries becoming meaningful

## The SigNoz Feature I Liked Most: Traces

The feature I liked most was **distributed tracing**.

Before this project, I understood logs more naturally. Logs say what happened at one point in time.

But traces answered a more powerful question:

```text
Where did the request spend time?
```

For example, a checkout request may look like this:

```text
POST /checkout
  ui-service
  checkout-service
  cart-service
  inventory-service
  payment-service
  PostgreSQL insert_order
  Kafka publish fraud.check.requested
  ai-fraud-service consumer
  notification-service
  analytics-service
```

When I triggered a `payment_slow` scenario, I could see the payment span dominate the request.

When I triggered a `db_slow` scenario, I could see the PostgreSQL span become the bottleneck.

When I triggered a `poison_message` scenario, checkout still succeeded, but the async fraud path showed retries and DLQ behavior.

That changed how I thought about debugging.

Without tracing, I would only know:

```text
Checkout is slow.
```

With tracing, I could say:

```text
Checkout is slow because the payment-service span is slow.
```

Or:

```text
The user-facing request succeeded, but fraud processing failed later in the Kafka consumer and produced DLQ events.
```

That is a much better debugging story.

## Logs Became More Useful With Trace IDs

I also learned that logs become far more useful when they are connected to traces.

ObserveAI emits structured JSON logs with fields like:

```json
{
  "service.name": "payment-service",
  "message": "payment failed",
  "trace_id": "example-trace-id",
  "span_id": "example-span-id",
  "scenario": "provider_timeout",
  "order_id": "ord_123",
  "error_type": "provider_timeout"
}
```

This helped me connect:

- the request
- the trace
- the service
- the scenario
- the error message
- the order ID

That is when logs stopped feeling like isolated text and started becoming part of the same incident story.

## Metrics, p50, p90, and p99 Finally Made Sense

Metrics helped me understand the system from a higher level.

Instead of opening individual traces every time, I could look at:

- request rate
- error rate
- p50 latency
- p90 latency
- p99 latency
- service span volume
- Kafka consumer lag estimate
- DLQ event count
- payment failure rate
- fraud inference latency

The percentile metrics were especially useful.

Simple version:

```text
p50 = typical user experience
p90 = slower users
p99 = worst 1% experience
```

If p50 is fine but p99 is bad, most users are okay, but some users are having a terrible experience.

That is important because production incidents often start in the tail.

## Dashboards and Alerts

After traces/logs/metrics were flowing, I started creating dashboard and alert plans.

ObserveAI has dashboard query packs for:

- System Overview
- Checkout Health
- Payment Health
- Database and Redis Health
- Fraud Pipeline
- Downstream Consumers

It also has alert query plans for:

- checkout p99 latency
- checkout error rate
- payment provider error rate
- payment p99 latency
- PostgreSQL slow query latency
- Redis/cache latency
- fraud AI latency
- Kafka consumer lag
- fraud DLQ events
- notification failures
- analytics latency
- telemetry silence

One important lesson:

```text
Dashboards are for seeing.
Alerts are for acting.
```

A dashboard tells me the payment service is slow.

An alert tells me the payment service is slow enough that someone should care.

## The ObserveAI UI

To make the project easier to understand, I also built a local UI.

It lets me:

- check service health
- trigger demo scenarios
- view a pictorial architecture map
- animate HTTP calls, Kafka events, and OTLP telemetry movement
- use presentation mode for demos
- inspect the latest scenario with a trace helper
- copy useful SigNoz ClickHouse queries
- understand the AI investigation loop: SigNoz evidence → SigNoz MCP → Codex investigator

The UI helped me connect the mental model:

```text
Scenario trigger
  -> service behavior
  -> telemetry export
  -> SigNoz traces/logs/metrics
  -> dashboard/alert evidence
```

## Trying SigNoz MCP

I also explored SigNoz MCP.

The idea is powerful:

```text
Instead of manually clicking through every screen,
an AI assistant can query SigNoz through MCP tools.
```

For example, I connected Codex to SigNoz MCP and asked it to list ObserveAI services sending telemetry.

It was able to identify services like:

- traffic-generator
- checkout-service
- payment-service
- inventory-service
- cart-service
- ui-service
- ai-fraud-service
- notification-service
- analytics-service

This made me think about the next direction:

```text
AI agents should not guess about incidents.
They should query observability evidence.
```

That is also shaping my hackathon thinking.

## What I Learned

This project helped me understand observability much more deeply.

My biggest learnings:

1. Observability is not just dashboards.

   Dashboards are useful, but the real value is understanding why something happened.

2. Traces are the storyline of a request.

   They show how a request moves across services and where time is spent.

3. Logs are better when connected to traces.

   A log with a trace ID is much more useful than a random log line.

4. Metrics show system behavior over time.

   They help identify trends, spikes, regressions, and tail latency.

5. Async systems need special observability.

   Kafka lag, retries, poison messages, and DLQs are not always visible in the original HTTP request.

6. Alerts should be tied to user or business impact.

   Alerting on every technical symptom creates noise. Alerting on latency, errors, DLQ, and failed workflows is more meaningful.

7. MCP can make observability AI-native.

   If an AI assistant can query SigNoz directly, it can investigate with evidence instead of guessing.

## What I Want To Build Next

ObserveAI is my preparation project.

For the hackathon itself, I want to build something separate and more agent-native.

The current idea is:

```text
Blackbox War Room
```

The concept:

```text
Blackbox = SigNoz records the telemetry evidence.
War Room = multiple AI agents investigate the incident using SigNoz MCP.
```

The tagline:

```text
When production breaks, replay the blackbox and let the agents investigate.
```

The long-term idea is:

- Metrics Agent checks latency and error rate
- Trace Agent finds slow spans and bottlenecks
- Logs Agent finds error patterns
- Alert Agent checks what fired or what is missing
- Remediation Agent suggests safe next actions
- Coordinator Agent produces the final incident report

And importantly:

```text
The agents use SigNoz to observe production,
while SigNoz also observes the agents.
```

That means AI for observability and observability for AI.

## Final Thoughts

Before this challenge, observability felt like a collection of separate words:

```text
logs, metrics, traces, dashboards, alerts
```

After building ObserveAI, it feels more like a connected investigation system.

If something breaks, I now think in questions:

```text
What changed?
Which service is slow?
Where did the request spend time?
Which logs match the trace?
Did errors increase?
Is this user-facing or async?
Should an alert fire?
What evidence supports the root cause?
```

That is the real shift for me.

SigNoz gave me a practical way to see all of this locally. And now, going into the hackathon, I feel much more prepared to build something meaningful around AI and observability.

## Project Links

- GitHub repo: https://github.com/ghantasala-sr/ObserveAI
- Local ObserveAI UI: `http://127.0.0.1:18082`
- Local SigNoz UI: `http://127.0.0.1:8080`

## Screenshots To Add Before Publishing

I would add 3–5 screenshots:

1. ObserveAI architecture UI or Presentation mode.
2. SigNoz services list showing ObserveAI services.
3. A trace for `payment_slow`, `provider_timeout`, or `db_slow`.
4. A dashboard panel showing p50/p90/p99 or error rate.
5. An alert rule or ClickHouse query panel if available.

## AI Assistance Disclosure

I used AI assistance while planning, coding, debugging, and writing parts of this project and blog draft. The project design, implementation choices, local testing, and learning process were guided by my own exploration while using AI as a coding and writing collaborator.
