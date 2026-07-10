# ObservableShop AI

**End-to-end observability lab for microservices, Kafka-compatible event streaming, and basic AI services using OpenTelemetry + SigNoz.**

ObservableShop AI is a production-style learning project designed to understand observability deeply before building an AI/SRE copilot on top of SigNoz MCP.

The project simulates an e-commerce checkout platform where synchronous microservices, asynchronous Kafka events, and basic AI services are fully instrumented with logs, metrics, traces, dashboards, and alerts.

---

## 1. Project Goal

The goal is to learn how observability works in real enterprise systems.

This project helps answer:

```text
What happened?
Where did it happen?
Why did it happen?
Who or what was affected?
Which service caused the issue?
Which trace/log/metric proves it?
What alert should catch this next time?
```

By the end, we should understand:

```text
OpenTelemetry
SigNoz
Logs
Metrics
Traces
Dashboards
Alerts
Kafka observability
Consumer lag
Dead-letter queues
AI inference observability
Microservice debugging
Root-cause analysis
```

---

## 2. One-Line Pitch

**ObservableShop AI is an OpenTelemetry-instrumented microservices observability lab that uses SigNoz to debug checkout, payment, Kafka, and AI-service failures through logs, metrics, traces, dashboards, and alerts.**

---

## 3. High-Level Architecture

```text
Client / API Tester
        |
        v
API Gateway
        |
        v
Checkout Service
   |        |        |
   |        |        |
   v        v        v
Cart     Inventory   Payment
Service  Service     Service
   |        |          |
   v        v          v
Redis   PostgreSQL  PostgreSQL

Checkout Service publishes events
        |
        v
Kafka-compatible broker / Redpanda
        |
        |-- order.created
        |-- payment.completed
        |-- payment.failed
        |-- fraud.check.requested
        |-- fraud.check.completed
        |-- recommendation.requested
        |-- recommendation.generated
        |
        v
Consumers
   |
   |-- Notification Service
   |-- Analytics Service
   |-- AI Fraud Service
   |-- AI Recommendation Service

All services send telemetry
        |
        v
OpenTelemetry Collector
        |
        v
SigNoz
```

---

## 4. Why This Project Exists

Most developers learn logging, metrics, and tracing separately.

But in enterprises, debugging requires correlating all of them together.

Example incident:

```text
Checkout is slow.
```

Observability should help us discover:

```text
checkout-service p95 latency increased
payment-service span is slow
payment provider timeout logs increased
Kafka fraud-check consumer lag increased
AI fraud inference is delayed
checkout success rate dropped
```

This project creates those failures intentionally so we can learn how to debug them.

---

## 5. Tech Stack

Recommended stack:

```text
Language: Python
Backend Framework: FastAPI
Service Communication: HTTP
Async Messaging: Redpanda / Kafka-compatible broker
Database: PostgreSQL
Cache: Redis
Telemetry: OpenTelemetry
Observability Platform: SigNoz
Containerization: Docker Compose
```

Why FastAPI?

```text
Easy to build microservices
Easy OpenTelemetry support
Simple for AI/ML services
Good for resume and interviews
```

Why Redpanda?

```text
Kafka-compatible
Simpler local setup
No ZooKeeper required
Good for local development and demos
```

---

## 6. Services

### 6.1 API Gateway

Entry point for all client requests.

Responsibilities:

```text
Route requests to backend services
Create the root trace for user requests
Forward trace context to downstream services
Expose clean public APIs
```

Endpoints:

```http
GET  /health
GET  /products
POST /cart/add
GET  /cart/{user_id}
POST /checkout
GET  /orders/{order_id}
```

Observability:

```text
HTTP request count
HTTP latency
HTTP status codes
Trace propagation
Gateway logs
```

---

### 6.2 Product Service

Provides product catalog.

Endpoints:

```http
GET /health
GET /products
GET /products/{product_id}
```

Example response:

```json
[
  {
    "id": "p1",
    "name": "Wireless Mouse",
    "price": 29.99,
    "category": "electronics"
  },
  {
    "id": "p2",
    "name": "Mechanical Keyboard",
    "price": 89.99,
    "category": "electronics"
  }
]
```

Observability:

```text
Product lookup latency
Product request count
Product service error rate
Optional Redis cache hit/miss
```

---

### 6.3 Cart Service

Manages shopping cart state.

Uses:

```text
Redis
```

Endpoints:

```http
GET  /health
POST /cart/add
GET  /cart/{user_id}
DELETE /cart/{user_id}
```

Observability:

```text
Redis call latency
Cart add count
Cart read count
Cart errors
Cache failures
```

---

### 6.4 Checkout Service

Main orchestrator for the checkout workflow.

Responsibilities:

```text
Fetch cart
Reserve inventory
Run fraud check request
Process payment
Create order
Publish Kafka events
Return checkout result
```

Endpoint:

```http
POST /checkout
```

Checkout flow:

```text
1. Receive checkout request
2. Get cart from cart-service
3. Reserve items using inventory-service
4. Call payment-service
5. Write order to PostgreSQL
6. Publish order.created event
7. Publish fraud.check.requested event
8. Publish recommendation.requested event
9. Return response
```

Observability:

```text
Checkout request count
Checkout success rate
Checkout failure rate
Checkout p95 latency
Custom spans:
  - get_cart
  - reserve_inventory
  - process_payment
  - create_order
  - publish_order_created
  - publish_fraud_check_requested
Kafka producer latency
Kafka publish failures
```

---

### 6.5 Inventory Service

Checks and reserves inventory.

Uses:

```text
PostgreSQL
```

Endpoints:

```http
GET  /health
GET  /inventory/{product_id}
POST /inventory/reserve
```

Observability:

```text
Inventory reservation latency
Out-of-stock count
Inventory DB query duration
Inventory errors
```

Important concept:

```text
Out of stock is a business failure, not necessarily a system error.
```

---

### 6.6 Payment Service

Simulates payment processing.

Endpoints:

```http
GET  /health
POST /payment/charge
```

Scenarios:

```text
success
payment_failed
payment_slow
provider_timeout
random_500
```

Observability:

```text
Payment request count
Payment success rate
Payment failure rate
Payment p95 latency
Payment timeout logs
External provider simulation span
```

---

### 6.7 Notification Service

Consumes events and simulates customer notifications.

Consumes topics:

```text
order.created
payment.failed
```

Responsibilities:

```text
Send fake order confirmation
Send fake payment failure message
Log notification status
```

Observability:

```text
Messages consumed
Notification processing latency
Notification failures
Consumer lag
```

---

### 6.8 Analytics Service

Consumes order and payment events for business metrics.

Consumes topics:

```text
order.created
payment.completed
payment.failed
inventory.reserved
```

Responsibilities:

```text
Track order count
Track payment success/failure
Track business event metrics
```

Observability:

```text
Orders created
Payments completed
Payments failed
Inventory reservations
Business event counters
Consumer lag
```

---

### 6.9 AI Fraud Service

Basic AI-style service for fraud risk scoring.

Consumes topic:

```text
fraud.check.requested
```

Publishes topic:

```text
fraud.check.completed
```

Input:

```json
{
  "order_id": "ord_123",
  "user_id": "u123",
  "order_value": 799.99,
  "item_count": 7,
  "country": "US"
}
```

Output:

```json
{
  "order_id": "ord_123",
  "risk_score": 0.82,
  "decision": "review",
  "reason": "High order value with multiple expensive items",
  "model_version": "fraud-rules-v1"
}
```

Start with rules:

```text
if order_value > 500 and item_count > 5:
    risk_score = 0.8
else:
    risk_score = 0.2
```

Later upgrade:

```text
scikit-learn LogisticRegression
RandomForestClassifier
local model loaded from pickle/joblib
```

Observability:

```text
Fraud inference latency
Fraud risk score distribution
High-risk order count
Model version
Model errors
Consumer lag
```

---

### 6.10 AI Recommendation Service

Basic recommendation service.

Consumes topic:

```text
recommendation.requested
```

Publishes topic:

```text
recommendation.generated
```

Input:

```json
{
  "user_id": "u123",
  "purchased_items": ["keyboard", "mouse"]
}
```

Output:

```json
{
  "user_id": "u123",
  "recommendations": ["mouse pad", "USB hub", "laptop stand"],
  "model_version": "recommendation-rules-v1"
}
```

Start with rule-based recommendations.

Example:

```text
keyboard -> mouse pad
laptop -> laptop stand
phone -> charger
mouse -> desk mat
```

Later upgrade:

```text
item-item similarity
embedding similarity
small local ML model
```

Observability:

```text
Recommendation latency
Empty recommendation count
Recommendation error count
Items recommended count
Model version
Consumer lag
```

---

## 7. Kafka / Redpanda Topics

Core topics:

```text
order.created
payment.completed
payment.failed
inventory.reserved
fraud.check.requested
fraud.check.completed
recommendation.requested
recommendation.generated
notification.sent
dead-letter.events
```

Kafka observability concepts to learn:

```text
Producer latency
Producer failure rate
Consumer lag
Consumer processing latency
Retries
Poison messages
Dead-letter topic
Event throughput
```

---

## 8. Telemetry Model

Each service should emit three telemetry types:

```text
Logs
Metrics
Traces
```

---

### 8.1 Logs

Logs explain what happened at a specific point in time.

Use structured JSON logs.

Example:

```json
{
  "timestamp": "2026-07-10T10:00:00Z",
  "level": "error",
  "service": "payment-service",
  "message": "Payment provider timeout",
  "trace_id": "abc123",
  "span_id": "def456",
  "order_id": "ord_123",
  "duration_ms": 2100
}
```

Every important log should include:

```text
service.name
trace_id
span_id
request_id
order_id, if available
user_id, if safe
error message
duration_ms
```

---

### 8.2 Metrics

Metrics explain system behavior over time.

Core service metrics:

```text
http_requests_total
http_request_duration_ms
http_errors_total
service_errors_total
```

Checkout metrics:

```text
checkout_requests_total
checkout_success_total
checkout_failure_total
checkout_duration_ms
checkout_failure_by_reason_total
```

Payment metrics:

```text
payment_requests_total
payment_success_total
payment_failure_total
payment_duration_ms
payment_timeout_total
```

Kafka metrics:

```text
kafka_messages_produced_total
kafka_messages_consumed_total
kafka_producer_errors_total
kafka_consumer_errors_total
kafka_consumer_lag
kafka_message_processing_duration_ms
dead_letter_events_total
```

AI metrics:

```text
fraud_requests_total
fraud_inference_duration_ms
fraud_high_risk_total
fraud_model_errors_total
fraud_score_avg

recommendation_requests_total
recommendation_duration_ms
recommendation_empty_results_total
recommendation_errors_total
recommendation_items_generated_total
```

---

### 8.3 Traces

Traces explain how a request flows across services.

Example checkout trace:

```text
POST /checkout
  api-gateway
  checkout-service
    get_cart
      cart-service
        redis_get_cart
    reserve_inventory
      inventory-service
        postgres_update_inventory
    process_payment
      payment-service
        fake_payment_provider_call
    create_order
      postgres_insert_order
    kafka_publish_order_created
    kafka_publish_fraud_check_requested
    kafka_publish_recommendation_requested
```

For async Kafka flows, propagate trace context through message headers.

Example:

```text
checkout-service publishes fraud.check.requested
  |
  v
ai-fraud-service consumes message
  |
  v
ai-fraud-service creates child span
  |
  v
ai-fraud-service publishes fraud.check.completed
```

---

## 9. OpenTelemetry Requirements

Each service should use OpenTelemetry for:

```text
HTTP server instrumentation
HTTP client instrumentation
Kafka producer instrumentation
Kafka consumer instrumentation
PostgreSQL instrumentation
Redis instrumentation
Custom spans
Error recording
Context propagation
```

Service attributes:

```text
service.name
service.version
deployment.environment
```

Example service names:

```text
api-gateway
product-service
cart-service
checkout-service
payment-service
inventory-service
notification-service
analytics-service
ai-fraud-service
ai-recommendation-service
```

Environment values:

```text
local
dev
staging
prod
```

---

## 10. SigNoz Dashboards

Create dashboards manually first. Later export JSON.

---

### 10.1 System Overview Dashboard

Panels:

```text
Request rate by service
p95 latency by service
p99 latency by service
Error rate by service
Top endpoints by traffic
Top failing endpoints
Service dependency view
```

---

### 10.2 Checkout Health Dashboard

Panels:

```text
Checkout request count
Checkout success rate
Checkout failure rate
Checkout p95 latency
Checkout p99 latency
Checkout failures by reason
Slowest checkout traces
Recent checkout error logs
```

---

### 10.3 Payment Service Dashboard

Panels:

```text
Payment requests
Payment success vs failure
Payment failure rate
Payment p95 latency
Provider timeout count
Payment errors by type
Slow payment traces
```

---

### 10.4 Kafka Health Dashboard

Panels:

```text
Messages produced by topic
Messages consumed by topic
Consumer lag by consumer group
Producer error rate
Consumer error rate
Dead-letter message count
Event processing latency
```

---

### 10.5 AI Services Dashboard

Panels:

```text
Fraud inference p95 latency
Fraud decisions by type
Fraud risk score distribution
Fraud model errors
Recommendation latency
Empty recommendation rate
Recommendation errors
Model version breakdown
```

---

### 10.6 Business Metrics Dashboard

Panels:

```text
Orders created
Payments completed
Payments failed
Checkout conversion
Inventory reservation failures
High-risk orders
Notifications sent
Recommendations generated
```

---

## 11. Alerts

Create these alerts in SigNoz.

---

### 11.1 Checkout Alerts

```text
Alert: Checkout High Latency
Condition: checkout p95 latency > 1s for 5 minutes
Severity: warning/critical

Alert: Checkout Error Rate High
Condition: checkout error rate > 3% for 5 minutes
Severity: critical

Alert: Checkout Success Rate Low
Condition: checkout success rate < 95% for 10 minutes
Severity: critical
```

---

### 11.2 Payment Alerts

```text
Alert: Payment Failure Spike
Condition: payment failure rate > 5% for 5 minutes
Severity: critical

Alert: Payment Provider Timeout
Condition: payment timeout logs > 10 in 5 minutes
Severity: critical

Alert: Payment Latency High
Condition: payment p95 latency > 800ms for 5 minutes
Severity: warning
```

---

### 11.3 Kafka Alerts

```text
Alert: Kafka Consumer Lag High
Condition: consumer lag > 1000 for 5 minutes
Severity: critical

Alert: Kafka Producer Errors
Condition: producer error rate > 2% for 5 minutes
Severity: critical

Alert: Dead Letter Events Increasing
Condition: dead-letter events > 10 in 10 minutes
Severity: warning/critical
```

---

### 11.4 AI Service Alerts

```text
Alert: Fraud Inference Slow
Condition: fraud inference p95 latency > 500ms for 5 minutes
Severity: warning

Alert: Fraud Model Errors
Condition: fraud model errors > 5 in 5 minutes
Severity: critical

Alert: Recommendation Empty Rate High
Condition: empty recommendation rate > 30% for 10 minutes
Severity: warning

Alert: Recommendation Service Errors
Condition: recommendation service error rate > 3% for 5 minutes
Severity: critical
```

---

## 12. Failure Scenarios

The project should include scripts to trigger failures.

---

### 12.1 Scenario: Payment Slow

Command:

```bash
./scenarios/payment_slow.sh
```

Expected behavior:

```text
checkout latency increases
payment-service span becomes slow
payment dashboard shows p95 spike
latency alert fires
logs show provider delay
```

---

### 12.2 Scenario: Payment Failure

Command:

```bash
./scenarios/payment_fail.sh
```

Expected behavior:

```text
payment failures increase
checkout failures increase
payment-service logs show errors
checkout error rate alert fires
```

---

### 12.3 Scenario: Kafka Consumer Lag

Command:

```bash
./scenarios/kafka_lag.sh
```

Expected behavior:

```text
fraud.check.requested messages increase
ai-fraud-service consumes slowly
consumer lag increases
Kafka dashboard shows backlog
lag alert fires
```

---

### 12.4 Scenario: AI Fraud Slow

Command:

```bash
./scenarios/fraud_ai_slow.sh
```

Expected behavior:

```text
fraud inference latency increases
AI dashboard shows latency spike
trace shows ai-fraud-service delay
alert fires
```

---

### 12.5 Scenario: Recommendation Failure

Command:

```bash
./scenarios/recommendation_fail.sh
```

Expected behavior:

```text
orders still succeed
recommendation.generated events fail
recommendation error logs increase
business dashboard shows empty recommendations
```

---

### 12.6 Scenario: Database Slow Query

Command:

```bash
./scenarios/db_slow.sh
```

Expected behavior:

```text
checkout trace shows create_order slow
database latency increases
dashboard shows DB bottleneck
```

---

### 12.7 Scenario: Poison Kafka Message

Command:

```bash
./scenarios/poison_message.sh
```

Expected behavior:

```text
consumer repeatedly fails
retry count increases
message goes to dead-letter.events
dead-letter alert fires
```

---

## 13. Suggested Repository Structure

```text
observable-shop-ai/
│
├── README.md
├── docker-compose.yml
├── otel-collector-config.yaml
├── .env.example
│
├── services/
│   ├── api-gateway/
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── product-service/
│   ├── cart-service/
│   ├── checkout-service/
│   ├── payment-service/
│   ├── inventory-service/
│   ├── notification-service/
│   ├── analytics-service/
│   ├── ai-fraud-service/
│   └── ai-recommendation-service/
│
├── shared/
│   ├── telemetry.py
│   ├── logging_config.py
│   ├── kafka_client.py
│   ├── http_client.py
│   ├── config.py
│   └── models.py
│
├── database/
│   ├── init.sql
│   └── seed.sql
│
├── dashboards/
│   ├── system-overview.json
│   ├── checkout-health.json
│   ├── payment-service.json
│   ├── kafka-health.json
│   ├── ai-services.json
│   └── business-metrics.json
│
├── alerts/
│   ├── checkout-alerts.md
│   ├── payment-alerts.md
│   ├── kafka-alerts.md
│   └── ai-service-alerts.md
│
├── scenarios/
│   ├── payment_slow.sh
│   ├── payment_fail.sh
│   ├── kafka_lag.sh
│   ├── fraud_ai_slow.sh
│   ├── recommendation_fail.sh
│   ├── db_slow.sh
│   └── poison_message.sh
│
├── docs/
│   ├── architecture.md
│   ├── observability-basics.md
│   ├── debugging-playbook.md
│   ├── dashboard-design.md
│   └── alert-design.md
│
└── tests/
    ├── smoke_test.sh
    └── load_test.py
```

---

## 14. Development Phases

### Phase 1: Minimal Synchronous System

Build:

```text
api-gateway
checkout-service
payment-service
inventory-service
```

Goal:

```text
Create working checkout flow.
Add traces, logs, and basic metrics.
View services and traces in SigNoz.
```

---

### Phase 2: Add Cart, Product, Postgres, Redis

Build:

```text
product-service
cart-service
PostgreSQL
Redis
```

Goal:

```text
Add realistic dependencies.
Trace database and Redis calls.
Debug slow DB/cache scenarios.
```

---

### Phase 3: Add Kafka / Redpanda

Build:

```text
order.created topic
payment.completed topic
payment.failed topic
notification-service
analytics-service
```

Goal:

```text
Understand producer/consumer observability.
Track consumer lag and async processing.
```

---

### Phase 4: Add Basic AI Services

Build:

```text
ai-fraud-service
ai-recommendation-service
```

Goal:

```text
Observe AI inference latency, model decisions, and AI service failures.
```

---

### Phase 5: Dashboards and Alerts

Build:

```text
System dashboard
Checkout dashboard
Payment dashboard
Kafka dashboard
AI services dashboard
Business dashboard
```

Goal:

```text
Turn telemetry into operational views.
Create useful alerts.
```

---

### Phase 6: Incident Scenarios and Debugging Reports

Build:

```text
failure scenario scripts
debugging playbooks
incident report examples
```

Goal:

```text
Practice root-cause analysis.
Document what each failure looks like in logs, metrics, and traces.
```

---

## 15. MVP Scope

To avoid overbuilding, start with this MVP:

```text
checkout-service
payment-service
inventory-service
Redpanda
ai-fraud-service
OpenTelemetry Collector
SigNoz
Docker Compose
```

MVP flow:

```text
POST /checkout
        |
        v
checkout-service
        |
        |-- calls payment-service
        |-- calls inventory-service
        |-- publishes fraud.check.requested
        |
        v
Redpanda / Kafka
        |
        v
ai-fraud-service
        |
        v
publishes fraud.check.completed
```

MVP observability:

```text
Distributed trace across checkout, payment, and inventory
Kafka producer span
Kafka consumer span
AI fraud inference span
Structured logs with trace_id
Basic metrics for latency/errors
```

### V1 Boundary: No External LLM Required

Version 1 must run locally without a Claude, ChatGPT, or other hosted LLM API key.

The v1 AI services are intentionally simple and deterministic:

```text
ai-fraud-service          -> rules-based risk scoring
ai-recommendation-service -> rules-based recommendations
```

Their purpose in v1 is to teach observability for AI-like workloads:

```text
inference latency
model version attributes
decision distributions
model errors
consumer lag
async trace propagation
```

This keeps the first release reproducible, inexpensive, and suitable for offline development. The services should expose a model version such as `fraud-rules-v1`, even though no external model API is being called.

### Future LLM Integration

The README’s future “SRE Sidekick” may use an external LLM to interpret SigNoz telemetry. The provider is intentionally not selected for v1. Possible providers include OpenAI’s API, Anthropic’s Claude API, or a self-hosted model.

When that phase begins, isolate the provider behind an application interface:

```text
SRE Sidekick
    -> LLMProvider interface
        -> OpenAI adapter
        -> Anthropic adapter
        -> local-model adapter, optional
```

Provider configuration should be supplied through environment variables or a secret manager, never committed to the repository:

```env
LLM_PROVIDER=openai
LLM_MODEL=<chosen-model>
LLM_API_KEY=<secret>
```

The future AI layer must not send raw sensitive logs or payment data to an external provider. It should first filter and summarize SigNoz data, retain evidence links such as trace IDs, and record provider latency, token usage, failures, and model version as telemetry.

---

## 16. Local Setup Plan

Expected command:

```bash
docker compose up --build
```

Expected local URLs:

```text
SigNoz UI: http://localhost:3301
API Gateway: http://localhost:8080
Redpanda Console: http://localhost:8081
```

Example request:

```bash
curl -X POST http://localhost:8080/checkout \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "u123",
    "items": [
      {"product_id": "p1", "quantity": 1},
      {"product_id": "p2", "quantity": 2}
    ],
    "payment_method": "card"
  }'
```

Scenario request:

```bash
curl -X POST "http://localhost:8080/checkout?scenario=payment_slow" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "u123",
    "items": [
      {"product_id": "p1", "quantity": 1}
    ],
    "payment_method": "card"
  }'
```

---

## 17. Environment Variables

Example `.env.example`:

```env
ENVIRONMENT=local
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc

POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_USER=observability
POSTGRES_PASSWORD=observability
POSTGRES_DB=observable_shop

REDIS_HOST=redis
REDIS_PORT=6379

KAFKA_BOOTSTRAP_SERVERS=redpanda:9092

LOG_LEVEL=INFO
```

---

## 18. Observability Design Principles

Use these principles while building.

### 18.1 Every Request Must Have a Trace

Every request should be traceable across services.

```text
API Gateway -> Checkout -> Payment -> Inventory -> Kafka -> AI Fraud
```

---

### 18.2 Every Error Must Have Context

Bad log:

```text
Payment failed
```

Good log:

```json
{
  "message": "Payment failed",
  "service": "payment-service",
  "order_id": "ord_123",
  "user_id": "u123",
  "reason": "provider_timeout",
  "trace_id": "abc123",
  "duration_ms": 2200
}
```

---

### 18.3 Dashboards Should Answer Questions

Bad dashboard:

```text
Random CPU and memory charts
```

Good dashboard:

```text
Is checkout healthy?
Are payments failing?
Is Kafka lag increasing?
Are AI services slow?
```

---

### 18.4 Alerts Should Be User-Impact Based

Bad alert:

```text
CPU > 80%
```

Better alert:

```text
Checkout p95 latency > 1s and checkout error rate > 3%
```

---

## 19. Debugging Playbook

When something breaks, follow this order.

```text
1. Check dashboard
2. Identify service with high latency/error rate
3. Open traces
4. Find slow or failed span
5. Open related logs using trace_id
6. Check Kafka lag if async flow is involved
7. Check AI service inference latency if AI flow is involved
8. Identify root-cause hypothesis
9. Propose fix
10. Add or improve alert
```

Example root-cause format:

```text
Incident:
Checkout latency increased.

Evidence:
- checkout-service p95 increased from 250ms to 1.8s
- traces show payment-service span taking 1.5s
- payment-service logs show provider_timeout
- payment timeout alert fired

Root-cause hypothesis:
Payment provider latency caused checkout requests to slow down.

Recommended action:
Add timeout, retry with exponential backoff, circuit breaker, and payment latency alert.
```

---

## 20. Future Upgrade: SigNoz MCP + AI SRE Copilot

After completing the observability lab, build the AI layer:

```text
SRE Sidekick
```

Future workflow:

```text
User asks:
"Why is checkout slow?"

AI agent uses SigNoz MCP to:
1. Query metrics
2. Query traces
3. Query logs
4. Check dashboards
5. Check alerts
6. Generate root-cause hypothesis
7. Suggest remediation
```

This README prepares the foundation for that project.

---

## 21. Resume Bullets

```text
Built ObservableShop AI, an OpenTelemetry-instrumented microservices observability lab using FastAPI, SigNoz, Kafka-compatible Redpanda, PostgreSQL, and Redis to correlate logs, metrics, traces, consumer lag, and AI inference latency across checkout, payment, fraud, and recommendation workflows.
```

```text
Designed production-style dashboards and alerts for p95 latency, error rate, payment failures, Kafka consumer lag, dead-letter events, and AI model latency, simulating real incident scenarios to debug synchronous and asynchronous system failures.
```

---

## 22. First Codex Prompt

Use this prompt in Codex to start implementation:

```text
Create a production-style Python FastAPI microservices project called ObservableShop AI.

Build the initial MVP with:
1. checkout-service
2. payment-service
3. inventory-service
4. ai-fraud-service
5. Redpanda as Kafka-compatible broker
6. OpenTelemetry Collector
7. SigNoz integration
8. Docker Compose

Requirements:
- Each service should have a Dockerfile and requirements.txt.
- Use FastAPI for all services.
- checkout-service exposes POST /checkout.
- checkout-service calls payment-service and inventory-service over HTTP.
- checkout-service publishes fraud.check.requested event to Redpanda.
- ai-fraud-service consumes fraud.check.requested and publishes fraud.check.completed.
- Implement scenarios using query param: payment_slow, payment_fail, inventory_fail, fraud_ai_slow.
- Add OpenTelemetry tracing for HTTP server, HTTP client, Kafka producer, and Kafka consumer flows.
- Add structured JSON logs with service name, trace_id, span_id, order_id, and scenario.
- Add basic metrics for request count, latency, errors, checkout success/failure, payment failures, Kafka produced/consumed messages, and fraud inference latency.
- Add docker-compose.yml to run all services locally.
- Add README instructions for running the project and testing scenarios.
- Keep the code simple, readable, and suitable for learning observability.
```

---

## 23. Definition of Done

The MVP is done when:

```text
docker compose up --build works
POST /checkout returns success
payment_slow scenario creates slow traces
payment_fail scenario creates error logs
inventory_fail scenario creates failed checkout
fraud_ai_slow scenario creates delayed AI fraud processing
SigNoz shows all services
SigNoz shows distributed traces
Logs include trace_id and span_id
Kafka events are produced and consumed
At least one dashboard can be built from collected telemetry
At least one alert can be configured from collected telemetry
```

---

## 24. Next Steps

Recommended order:

```text
1. Generate MVP structure using Codex
2. Run docker compose
3. Test normal checkout
4. Add OpenTelemetry traces
5. Verify traces in SigNoz
6. Add structured logs
7. Add Kafka event flow
8. Add AI fraud service
9. Create failure scenarios
10. Build dashboards and alerts
```

---

## 25. Non-Negotiable Reliability and Correlation Controls

The following controls are required for the MVP. They are essential for producing trustworthy data in SigNoz.

### 25.1 Kafka Trace Context Propagation

Every producer must inject the current OpenTelemetry context into Kafka message headers. Every consumer must extract that context before creating its processing span.

Required async trace flow:

```text
checkout-service
  └── produces fraud.check.requested
        └── ai-fraud-service extracts parent context
              └── creates fraud processing span
                    └── produces fraud.check.completed
```

Required message headers:

```text
traceparent
tracestate, when present
```

Required consumer span attributes:

```text
messaging.system = kafka
messaging.destination.name
messaging.operation.type = process
messaging.kafka.consumer.group
messaging.message.conversation_id, when available
```

Acceptance criteria:

```text
The checkout trace is connected to the fraud consumer trace in SigNoz.
Kafka producer and consumer spans are visible.
The order_id is searchable across the complete async workflow.
```

### 25.2 Privacy-Safe Structured Logging

All services must emit JSON logs through the shared logging package. Logs must be correlated with OpenTelemetry without exposing sensitive information.

Allowed common fields:

```text
timestamp
level
service.name
service.version
deployment.environment
message
trace_id
span_id
request_id
order_id
user_id, only when required and approved
scenario
duration_ms
error_type
```

Never log:

```text
payment card numbers
CVV or payment tokens
passwords
authorization headers
session cookies
full request bodies by default
```

User and order identifiers must not be metric labels. They may be log fields when needed for investigation. Request bodies must be redacted or omitted unless a scenario explicitly requires a safe test payload.

Acceptance criteria:

```text
Every error log contains service, trace_id, span_id, and a safe failure reason.
Sensitive fields are redacted before export.
SigNoz log search can correlate an error with its trace.
```

### 25.3 Reliable Failure Handling

Service calls and Kafka consumers must fail predictably and preserve system consistency.

HTTP calls must define:

```text
connect timeout
read timeout
bounded retries
exponential backoff with jitter
retryable versus non-retryable errors
```

Payment and order operations must be idempotent using an order or request idempotency key. A timeout must not cause an uncontrolled duplicate charge or duplicate order.

Kafka consumers must implement:

```text
manual acknowledgment after successful processing
bounded retries
backoff between retries
dead-letter.events publishing after retry exhaustion
poison-message logging with message metadata only
```

Business failures and technical failures must remain distinct:

```text
payment_declined       -> expected business outcome
inventory_unavailable  -> expected business outcome
provider_timeout       -> technical dependency failure
database_unavailable   -> technical infrastructure failure
```

Expected business outcomes should be represented with controlled status values and counters. Technical failures should record exceptions on spans, emit error logs, and contribute to service error metrics.

Acceptance criteria:

```text
payment_fail does not crash the service.
provider_timeout respects the configured timeout.
Repeated checkout requests do not create duplicate orders.
Failed Kafka messages are retried and eventually reach dead-letter.events.
SigNoz distinguishes business failures from technical errors.
```

These controls must be implemented in shared components where possible so every service follows the same behavior.
