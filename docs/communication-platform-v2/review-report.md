# Architecture review report

Reviewed: 2026-08-26

Scope: the Communication Platform V2 planning package only. No application
implementation exists yet, so this review does not claim runtime, provider, UI,
database, load, or production test results.

## Result

**Pass with corrections applied.** The package is coherent enough to start
Phase 0 decision records, schemas, emulators, and executable contracts. It is
not approval for a big-bang production rewrite.

## Evidence

| Check | Result |
| --- | --- |
| Five original planning documents are present and non-empty | Pass |
| Markdown fence pairing, heading hierarchy, final newline, and whitespace | Pass |
| Four relative document links resolve | Pass |
| Four Mermaid blocks have balanced fences and non-empty bodies | Pass (structural) |
| 28 requested architecture/feature/security/test concepts are traceable | Pass |
| Schedule ranges agree between overview and delivery plan | Pass after correction |
| Current Hub Go ownership, Core isolation, ordering, final results, three-cycle DLQ, templates, identities, messages, teams/folders/cases, and flows map to the target plan | 10/10 checks pass |
| Functional/failure/security/UI/load/migration release assertions are defined | Pass |

Mermaid was structurally reviewed but not rendered by a Mermaid compiler because
the repository has no Mermaid CLI/parser dependency. Diagram rendering should be
added to documentation CI in Phase 0.

## Defects found and corrected

### 1. Route-wide cursor could cause head-of-line blocking

The first draft acknowledged one highest contiguous sequence for an entire Core
route. One poison customer event could therefore block unrelated customers.

Correction: each subscription now has fixed logical partitions. Events use a
stable thread ordering key, sequences/cursors are partition scoped, unrelated
partitions continue, and a quarantined gap remains visible and redrivable.

### 2. Queue claim could hold database locks across HTTP

The first wording did not explicitly end the PostgreSQL transaction before Core
delivery.

Correction: the worker claims and leases with `FOR UPDATE SKIP LOCKED`, commits
the short transaction, and performs network I/O afterward. Tests now assert the
lease/idempotency behavior around expiry and concurrent workers.

### 3. Initial schedule was internally inconsistent

The original 16–22 week single-engineer estimate was shorter than the detailed
phase effort.

Correction: the reviewed estimate is 24–32 weeks for one sequential engineer,
12–16 weeks for a focused three-person team, and 6–8 weeks for a non-production
prototype. External provider approval time is separate.

### 4. Existing WhatsApp parity tests were underspecified

The first test matrix mentioned calls, groups, templates, and Meta Flows but did
not cover their operational edge cases.

Correction: the matrix now includes template samples/sync, call SDP/ICE/TURN,
answer ownership, concurrent calls, dual-party recording and consent, groups,
Meta Flow encryption/actions, permission context, status rendering, and durable
Hub acceptance.

### 5. Standalone Hub administration authentication was implicit

Correction: the architecture now requires OIDC/OAuth, MFA policy, tenant RBAC,
short sessions, CSRF protection, and audited privilege changes, with matching
security tests. Hub must not create another password store.

## Compatibility review

The proposal retains the current production-critical boundaries:

- current Go relay logic remains the WhatsApp reference adapter;
- Core stays isolated from Meta credentials and the transport database;
- provider acceptance/results remain idempotent and durable;
- per-thread ordering remains while cross-thread concurrency increases;
- Core receives management/read-model projections and owns its local UI;
- current three-cycle automatic dead-letter recovery and terminal retention are
  migration requirements;
- existing templates, campaigns, flows, calls, groups, teams, folders, cases,
  identities, conversations, messages, and reads require parity before old paths
  can be disabled.

## Risks that must be closed in Phase 0

1. Benchmark PostgreSQL outbox/lease tables at the target backlog and churn;
   PostgreSQL is approved conditionally, not by assumption.
2. Choose and document fixed subscription partition counts and cursor migration.
3. Select OIDC, KMS, object-storage, regional residency, backup, and retention
   profiles without embedding one vendor in the domain.
4. Define email provider modes, IMAP concurrency limits, reputation, bounce, and
   suppression operations.
5. Define recording consent/legal policy per tenant and jurisdiction before call
   recording can be declared generally available.
6. Write versioned JSON schemas and compatibility rules before any persistence
   migration or adapter implementation.
7. Add executable documentation checks, including Mermaid rendering, to CI.

## Review verdict

Proceed with **Phase 0 only**: ADRs, schemas, adapter/Core contracts, synthetic
provider fixtures, queue benchmarks, and migration inventory. Do not start data
migration, provider cutover, or delete JetStream/Frappe Hub paths until those
gates pass.
