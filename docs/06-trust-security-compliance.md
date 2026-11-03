# 06 — Trust, Security & Compliance

> **Trust is the product.** We place real phone calls and handle people's health, financial, and
> identity data. If a customer cannot trust us, nothing else matters. This doc defines the policies
> that gate the entire system — several are *hard, code-enforced preconditions*, not guidelines.

---

## 1. The consent gate (hard precondition — nothing runs without it)

**Policy: we only ever test a bot the customer has proven they own or are authorized to test.**
This is enforced in the Run Orchestrator (doc 03 §1): `assert consent_valid(target_id)` aborts any
run lacking a valid record. Why it's non-negotiable: placing automated, recorded calls to a line you
don't own is potentially illegal (robocall/TCPA, wiretap/consent laws) and unethical.

**Ownership verification methods** (at least one required before a Target becomes `verified`):
1. **Call-back code** — we place a one-time call to the target number; an admin logged into the
   dashboard reads back the spoken code. Proves control of the line.
2. **Domain/endpoint proof** (chat) — DNS TXT record or a signed header on the endpoint.
3. **Signed Test Authorization** — the org attests in writing they own/control the target and
   authorize automated testing, with the authorizing user and timestamp recorded.

**Scoping policy.** Runs are rate-limited to a customer-declared max concurrency against their own
line (default 5), with per-day call caps, so we never resemble a denial-of-service against our own
customer. Targets can be allow-listed to specific numbers/endpoints per org.

---

## 2. Telephony & recording law (TCPA / two-party consent)

- We call **only verified targets owned by the customer** — we are not cold-calling third parties.
- **Recording:** calls are recorded for evidence. Because the target line is the customer's own
  automated system (not a live third-party human), and the customer has authorized it, recording is
  within the customer's rights. For any configuration that could reach a human, the synthetic caller
  discloses it is an automated test call, and jurisdictions requiring all-party consent are handled
  via the customer's own authorization + disclosure.
- **No PSTN robocalling of real consumers, ever.** The platform technically refuses targets that
  fail ownership verification. This is both policy and code.

---

## 3. Data protection

**Encryption.** TLS 1.2+ in transit everywhere; AES-256 at rest (S3 SSE-KMS, encrypted Postgres).
**Per-tenant keys** for audio/transcripts so one tenant's data is cryptographically isolated.

**PII/PHI handling.** Transcripts are scanned for PII/PHI; sensitive fields are tokenized into the
**PII vault** and referenced by token in the control plane, which therefore never stores raw
sensitive content. Raw conversation data lives only in the isolated data plane.

**Data residency.** Data-plane workers and stores are **region-pinned** (US, EU, etc.). Audio and
transcripts never leave the customer's chosen region. Enterprise option: **single-tenant / in-VPC
data plane** so raw audio never leaves the customer's cloud account at all.

**Retention & deletion.** Default 30-day TTL on raw audio/transcripts; configurable down to
**zero-retention** (score-only). Hard-delete on request (GDPR/CCPA right to erasure), propagated to
backups within the documented window. Deletion is logged.

**Data minimization & no-training.** We **do not train foundation models on customer conversation
data.** Judge calibration uses only explicitly consented, de-identified golden-set data. This is a
contractual commitment, not just a policy page.

---

## 4. Tenant isolation & access control

- **Strict multi-tenancy:** every query is tenant-scoped; row-level security in Postgres; object
  keys namespaced and key-isolated per tenant. Judges and workers never receive cross-tenant data.
- **RBAC:** org roles (Owner, Admin, Engineer, Viewer, Auditor) with least-privilege. SSO/SCIM for
  enterprise.
- **Access to raw conversation content** by Proctor staff is break-glass only: justified, time-boxed,
  audited, and customer-notifiable. Most operations work on metadata/scores, never raw content.

---

## 5. Prompt-injection & adversarial-input hardening

Because we deliberately feed adversarial inputs into bots and then feed transcripts to judge LLMs,
we are a prime injection target. Controls:
- Transcripts are passed to judges as **clearly delimited data, never as instructions**; judge
  prompts state that content between delimiters is untrusted.
- The synthetic-user generator and judges run with **no tool access** to customer systems — they can
  only read/score, never act.
- Adversarial personas that attempt injection *against the customer's bot* are a **feature** (we test
  for it), but their outputs are sandboxed and cannot affect Proctor's own control flow.

---

## 6. Compliance roadmap (what we certify, in order)

| Stage | Certification / framework | Unlocks | When |
|---|---|---|---|
| 1 | **SOC 2 Type I → Type II** | Mid-market & most SaaS buyers | Build controls from day 1; Type II after 6–12 mo of evidence |
| 2 | **HIPAA + BAA** | Healthcare customers (our beachhead) | Early — gated behind the data-plane isolation we already designed |
| 3 | **GDPR / CCPA** DPA, DSRs | EU + CA customers | With EU region + deletion tooling |
| 4 | **PCI-adjacent controls** | Fintech (we handle dispute/card scenarios, not card numbers) | As fintech segment grows |
| 5 | **ISO 27001**, **EU AI Act** alignment | Large enterprise & EU regulatory posture | As we move up-market |

**Design-for-compliance principle:** the control/data-plane split (doc 02 §2), per-tenant keys,
region pinning, and short retention were chosen *specifically* so that achieving these certifications
is a matter of evidence collection, not re-architecture.

---

## 7. Trust policies summarized (the public-facing commitments)

1. **We only test bots you own and have verified.** Hard-enforced.
2. **Your raw audio/transcripts stay in your region (or your VPC) and auto-expire.**
3. **We never train models on your data.**
4. **Every verdict is backed by evidence you can inspect and export for auditors.**
5. **Strict tenant isolation; staff access to raw content is break-glass and audited.**
6. **You can delete your data at any time, permanently.**
7. **We rate-limit against your own systems so testing never harms your production line.**

---

## 8. Platform security hygiene (table stakes, stated for completeness)

Secrets in Vault/KMS (customer telephony creds never in plaintext/env — note: the prototype's
`.env` and a committed `twilio_2FA_recovery_code.txt` must move to a secret manager **before any
real customer data**); least-privilege IAM; WAF + rate limiting at the edge; dependency and
container scanning in CI; signed images; audit logging on every privileged action; incident-response
runbook + responsible-disclosure program; regular pen-tests before and after SOC 2.
