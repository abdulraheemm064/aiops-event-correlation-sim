# AIOps Event Correlation - Simulation Report

> **SIMULATION RESULT ON SYNTHETIC DATA - not a measurement of any real environment.**
> Representative portfolio project built with synthetic data. Not derived from any employer or client code.

- Scenario: 24 h of synthetic monitoring traffic, seed `7`, 12 injected incidents
- Engine version: 1.0.0

![Alert funnel and simulated MTTR](noise-reduction.png)

## Alert funnel

| Stage | Count |
|---|---|
| Raw alert events (triggers) | 1609 |
| After de-duplication | 258 |
| After flap suppression (active, non-flapping) | 222 (+4 flapping alerts suppressed) |
| Correlated alert groups | 144 |
| Actionable incidents (score >= threshold) | 19 |

**Noise reduction (raw events -> actionable incidents): 98.8%** (de-duplication alone: 84.0%).

## Quality against ground truth

| Metric | Value |
|---|---|
| Injected incidents detected as actionable | 12 / 12 |
| Mean groups per incident (1.0 = never fragmented) | 1.0 |
| Group purity (events in a group sharing its dominant label) | 97.4% |
| Root cause: top-1 candidate correct | 75.0% |
| Root cause: correct within top-3 | 83.3% |
| Actionable groups that were really noise (false positives) | 7 |

## Simulated MTTR

| | Mean minutes |
|---|---|
| Baseline (operators work from raw alerts) | 109.8 |
| With correlation + root-cause hint | 55.0 |
| Improvement | 49.9% |

Model assumptions (minutes) - change them in `MttrAssumptions`:

- `baseline_minutes_per_alert` = 2.0
- `baseline_triage_cap` = 45.0
- `baseline_diagnosis` = 40.0
- `aiops_triage` = 5.0
- `aiops_diagnosis_correct_rca` = 10.0
- `aiops_diagnosis_wrong_rca` = 40.0
- Fix time per incident is drawn at random (15-60 min) and is identical in both arms.

## Per-incident detail

| Incident | True root | Raw events | Groups | Priority | Top candidate | Top-1 hit | MTTR base | MTTR AIOps |
|---|---|---|---|---|---|---|---|---|
| INC-SIM-001 | cbk-dwh-app-01 | 12 | 1 | P2 | APP-DataWarehouse | no | 82.0 | 63.0 |
| INC-SIM-002 | cb-acc-sw-05 | 84 | 1 | P1 | cb-acc-sw-05 | yes | 140.0 | 70.0 |
| INC-SIM-003 | cb-core-sw-02 | 240 | 1 | P1 | cb-core-sw-02 | yes | 143.0 | 73.0 |
| INC-SIM-004 | cb-acc-sw-02 | 95 | 1 | P1 | cb-acc-sw-02 | yes | 116.0 | 46.0 |
| INC-SIM-005 | cbk-tel-app-02 | 24 | 1 | P2 | cbk-tel-app-02 | yes | 141.0 | 71.0 |
| INC-SIM-006 | cb-acc-sw-06 | 72 | 1 | P1 | cb-acc-sw-06 | yes | 127.0 | 57.0 |
| INC-SIM-007 | APP-PaymentsGateway | 12 | 1 | P1 | cb-lb-01 | no | 83.0 | 64.0 |
| INC-SIM-008 | cbk-tel-db-01 | 8 | 1 | P2 | APP-BranchTeller | no | 81.0 | 70.0 |
| INC-SIM-009 | cb-acc-sw-03 | 69 | 1 | P1 | cb-acc-sw-03 | yes | 112.0 | 42.0 |
| INC-SIM-010 | cbk-ob-app-01 | 12 | 1 | P1 | cbk-ob-app-01 | yes | 80.0 | 31.0 |
| INC-SIM-011 | cb-acc-sw-05 | 36 | 1 | P2 | cb-acc-sw-05 | yes | 113.0 | 43.0 |
| INC-SIM-012 | cb-acc-sw-03 | 60 | 1 | P1 | cb-acc-sw-03 | yes | 100.0 | 30.0 |

## Actionable incidents (highest priority first)

| Group | Start (hh:mm) | Priority | Score | Alerts | Raw events | Services | Root-cause candidates |
|---|---|---|---|---|---|---|---|
| GRP0016 | 02:18 | P1 | 100.0 | 7 | 84 | Card Authorization, Claims Portal, Data Warehouse | cb-acc-sw-05 100%, cbk-clm-app-02 29%, cbk-clm-app-01 29% |
| GRP0029 | 04:38 | P1 | 100.0 | 20 | 240 | Card Authorization, Mobile API, Online Banking ... | cb-core-sw-02 100%, cb-acc-sw-05 40%, cb-lb-02 25% |
| GRP0041 | 06:17 | P1 | 100.0 | 9 | 95 | Card Authorization, Claims Portal, Data Warehouse | cb-acc-sw-02 100%, cbk-clm-db-01 22%, cbk-card-app-02 22% |
| GRP0065 | 10:36 | P1 | 100.0 | 9 | 87 | Payments Gateway, Policy Administration | cb-acc-sw-06 86%, cbk-pay-app-02 29%, cbk-pol-app-02 29% |
| GRP0107 | 16:37 | P1 | 100.0 | 8 | 84 | Mobile API, Payments Gateway, Branch Teller ... | cb-acc-sw-03 75%, cbk-pol-db-01 25%, cbk-pay-app-02 25% |
| GRP0136 | 22:25 | P1 | 100.0 | 5 | 60 | Payments Gateway, Policy Administration | cb-acc-sw-03 (inferred) 100%, cbk-pol-db-01 40%, cbk-pay-app-02 40% |
| GRP0079 | 12:22 | P1 | 91.0 | 3 | 23 | Mobile API, Payments Gateway | cb-lb-01 (inferred) 100%, APP-MobileAPI 50%, APP-PaymentsGateway 50% |
| GRP0121 | 18:48 | P1 | 88.0 | 1 | 12 | Online Banking | cbk-ob-app-01 100% |
| GRP0130 | 20:46 | P2 | 84.0 | 3 | 36 | Claims Portal | cb-acc-sw-05 (inferred) 100%, cbk-clm-app-02 67%, cbk-clm-app-01 67% |
| GRP0054 | 08:29 | P2 | 81.0 | 2 | 24 | Branch Teller | cbk-tel-app-02 100%, APP-BranchTeller 50% |
| GRP0092 | 14:38 | P2 | 78.0 | 1 | 8 | Branch Teller | APP-BranchTeller 100% |
| GRP0004 | 00:38 | P2 | 70.5 | 1 | 12 | Data Warehouse | APP-DataWarehouse 100% |
| GRP0005 | 00:44 | P3 | 52.0 | 2 | 9 | Card Authorization, Claims Portal | cb-acc-sw-05 (inferred) 100%, APP-ClaimsPortal 50%, APP-CardAuthorization 50% |
| GRP0025 | 03:58 | P3 | 52.0 | 2 | 12 | Mobile API, Online Banking | cb-acc-sw-04 (inferred) 100%, cbk-ob-db-01 50%, cbk-mob-app-01 50% |
| GRP0062 | 09:58 | P3 | 52.0 | 2 | 12 | Card Authorization, Data Warehouse | cb-acc-sw-02 (inferred) 100%, cbk-card-app-02 50%, APP-DataWarehouse 50% |
| GRP0082 | 13:20 | P3 | 52.0 | 2 | 14 | Card Authorization, Data Warehouse | cb-acc-sw-02 (inferred) 100%, cbk-card-app-01 50%, APP-DataWarehouse 50% |
| GRP0111 | 17:21 | P3 | 52.0 | 2 | 12 | Card Authorization, Data Warehouse | cb-acc-sw-05 (inferred) 100%, cbk-dwh-db-01 50%, cbk-card-db-01 50% |
| GRP0132 | 21:02 | P3 | 52.0 | 2 | 11 | Mobile API, Online Banking | cb-acc-sw-04 (inferred) 100%, cbk-mob-app-02 50%, cbk-ob-db-01 50% |
| GRP0142 | 23:09 | P3 | 52.0 | 2 | 11 | Card Authorization, Claims Portal | cb-acc-sw-05 (inferred) 100%, cbk-clm-app-01 50%, cbk-card-db-01 50% |

_SIMULATION RESULT ON SYNTHETIC DATA - not a measurement of any real environment._
