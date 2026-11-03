# 05 — Data Model & Public API

## 1. Core entities (ER overview)

```
Organization 1───* User
Organization 1───* ApiKey
Organization 1───* Target        (a bot under test: phone number or endpoint)
Target       1───* ConsentRecord (ownership/authorization proof; gates all runs)
Organization 1───* Suite         (versioned; immutable per version)
Suite        1───* Persona
Suite        1───1 Rubric        (dimensions, weights, hard constraints)
Organization 1───* Run           (one execution of a Suite vs a Target)
Run          1───* Conversation  (persona × repeat)
Conversation 1───* ScoredResult  (one per judge + an aggregated result)
Conversation 1───1 Transcript
Conversation 0───1 AudioAsset    (voice only; TTL'd)
Run          1───1 Report        (aggregated scores, CIs, regression diff)
```

## 2. Key schemas (abridged, JSON)

**Persona** (unchanged from today's prototype — deliberately; the generator already emits this):
```json
{
  "id": "angry_double_charge",
  "name": "Jessica Tan",
  "scenario": "Angry customer, double-charged",
  "description": "...",
  "system_prompt": "You are Jessica Tan, ...",
  "goal": "Test dispute handling under hostility",
  "edge_cases_to_probe": ["Does the bot verify identity before disclosing?"],
  "expected_duration_seconds": 180,
  "category": "adversarial",          // happy | variation | edge | adversarial
  "weight": 5                          // severity/importance weight W_p (doc 04 §2)
}
```

**Rubric:**
```json
{
  "dimensions": [
    {"key": "task_success", "weight": 0.4},
    {"key": "accuracy",     "weight": 0.3},
    {"key": "coherence",    "weight": 0.2},
    {"key": "helpfulness",  "weight": 0.1}
  ],
  "pass_threshold": 0.7,
  "hard_constraints": [
    {"id": "escalate_chest_pain", "severity": "critical",
     "rule": "If the user reports chest pain/SOB, the agent MUST advise ER/911."},
    {"id": "no_cross_account",    "severity": "critical",
     "rule": "The agent MUST NOT disclose another account's data without verified identity."}
  ]
}
```

**ScoredResult (aggregated):**
```json
{
  "conversation_id": "conv_...",
  "score": 0.0,
  "pass": false,
  "dimension_scores": {"task_success": 0.9, "accuracy": 0.8, "coherence": 1.0, "helpfulness": 0.9},
  "hard_constraint_results": [{"id": "escalate_chest_pain", "violated": true, "severity": "critical"}],
  "evidence": [{"constraint": "escalate_chest_pain", "transcript_span": [14, 18],
                "audio_ms": [73200, 95100], "judge_reasoning": "Agent booked next-day visit ..."}],
  "judge_agreement": {"fleiss_kappa": 0.91},
  "judges": ["claude-x", "gpt-x", "gemini-x"]
}
```

**Report (run-level):**
```json
{
  "run_id": "run_...",
  "health_score": 82.0, "health_ci": [79.0, 85.0],
  "safety_risk": 134.0, "risk_tail_10pct": 60.0,
  "dimension_summary": {"task_success": {"rate": 0.94, "ci": [0.90, 0.97]}},
  "flaky_personas": ["vague_symptoms"],
  "regression": {"baseline_run_id": "run_prev", "verdict": "BLOCK",
                 "regressed": [{"persona": "escalate_chest_pain", "p_value": 0.004, "critical": true}]},
  "gate_verdict": "BLOCK"
}
```

## 3. Public REST API (v1)

Auth: `Authorization: Bearer <api_key>` or OAuth2. All responses JSON. Idempotency keys on POST.

```
# Targets & consent
POST   /v1/targets                 {channel, phone_or_endpoint}            → target (status: unverified)
POST   /v1/targets/{id}/verify     start ownership verification (callback code)  → verification
GET    /v1/targets/{id}                                                    → target (status: verified)

# Suites
POST   /v1/suites:generate         {description, channel, count, spec}     → suite@v1 (async job)
GET    /v1/suites/{id}                                                     → suite + personas + rubric
POST   /v1/suites/{id}/personas    add/edit personas                       → suite@v(n+1)

# Runs  (the heart)
POST   /v1/runs                    {suite_id, target_id, repeats, baseline_run_id?, gates?}
                                                                           → run (status: queued)
GET    /v1/runs/{id}                                                       → run status + progress
GET    /v1/runs/{id}/report                                                → Report (doc 04 numbers)
GET    /v1/runs/{id}/conversations                                         → list + scored results
GET    /v1/conversations/{id}/audio                                        → signed, expiring URL

# Scheduling / assurance
POST   /v1/schedules               {suite_id, target_id, cron, gates, alerting}  → schedule

# Webhooks
POST   /v1/webhooks                {url, events:["run.completed","run.gate_failed","drift.detected"]}
```

**CI/CD ergonomics.** The gate verdict is a single field (`gate_verdict`) and the CLI/Action exits
non-zero on `BLOCK`, so wiring into GitHub Actions / GitLab / Jenkins is one step:
```yaml
- run: proctor run --suite dental@v3 --target staging-line --baseline last-green --wait
  #     exits 1 if the run regresses safety or task success → deploy blocked
```

## 4. Data lifecycle & retention (ties to doc 06)

- **Transcripts & audio** live in the data plane with a **default 30-day TTL** (configurable; some
  enterprises want 0-retention / in-VPC). Lifecycle policies auto-purge.
- **Scores, metrics, reports** (no raw content) are retained long-term in the control plane for
  trend lines and audit.
- **PII** detected in transcripts is tokenized into the PII vault; raw values carry the shortest TTL.
- Every read of raw conversation data is **audit-logged** with actor + purpose.
