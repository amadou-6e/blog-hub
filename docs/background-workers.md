# Durable background workers

BlogHub stores asynchronous work in SQLite and processes it in a separate worker
process. API requests only enqueue jobs. Generation, inspection, regeneration,
editor chat turns, deterministic and browser publishing, and scheduled remote
synchronization continue independently of the FastAPI process that accepted the
request.

## Running a worker

The development launchers start a worker automatically:

```bash
python start.py --reload
./start.sh
```

Run a worker directly when the API is managed separately:

```bash
python scripts/bloghub_worker.py
```

Useful options include:

```bash
python scripts/bloghub_worker.py \
  --queues agents,publishing \
  --worker-id worker-1 \
  --lease-seconds 30 \
  --poll-seconds 1
```

The worker uses `BLOGHUB_DB_PATH` and `BLOGHUB_BLOBS_DIR`, matching the API.
Multiple workers may share the same database. Claims are atomic, and each worker
renews its lease while a handler is running.

## Job lifecycle

Jobs use these states:

- `queued`: ready for a worker
- `running`: claimed by a worker with an active lease
- `waiting`: delayed by retry backoff or parked for operator reconciliation
- `completed`: finished successfully
- `failed`: exhausted attempts or encountered a permanent error
- `canceled`: canceled before or during execution
- `expired`: exceeded its enqueue lifetime before it could run

Transient failures move to `waiting` with exponential backoff. A worker restart or
expired lease recovers abandoned work. Attempts, heartbeat timestamps, checkpoints,
errors, and lease ownership are stored with the job.

A `waiting` job with no `availableAt` is intentionally parked. This happens when a
worker cannot prove whether an external side effect completed. It must be reconciled
and retried explicitly; automatic execution could publish the same content twice.

## Idempotency and effects

Clients may send `Idempotency-Key` on generation, regeneration, and push requests.
Submitting the same key for the same user and job type returns the existing active or
completed job.

Worker handlers also record durable effect keys. A completed provider or publication
result is reused after a retry instead of repeating that action. If a worker dies after
starting an external publication but before recording its result, the effect becomes
uncertain and the job is parked. Provider failures known not to have produced an
output release their effect so normal retries can proceed.

## Operations API

Authenticated clients can inspect and control work through:

```text
GET  /api/jobs?status=running&queue=agents
GET  /api/jobs/{job_id}
POST /api/jobs/{job_id}/cancel
POST /api/jobs/{job_id}/retry
GET  /api/jobs/metrics
GET  /api/jobs/sync-schedules
PUT  /api/jobs/sync-schedules
DELETE /api/jobs/sync-schedules/{platform}
```

Hashnode and Medium schedules use a minimum five-minute interval. The worker turns a
due schedule into one idempotent `sync` job, then advances the next run before claiming
work. This prevents multiple workers from enqueueing the same occurrence. The sync
handler uses the connected browser profile, with Hashnode PAT retrieval as a fallback.

Cancellation is immediate for unclaimed work and cooperative for running work.
Handlers check cancellation and timeouts between durable operations. Blocking provider
calls keep their lease alive, then observe the cancellation or timeout before recording
completion.

Queue metrics expose per-queue state counts, the oldest queued timestamp, total jobs,
and average attempts. Production monitoring should alert on old queued work, parked
jobs, repeated failures, and running jobs with stale heartbeats.

## Recovery notes

On startup, the API marks expired worker leases as orphaned and schedules safe work for
retry. Workers perform the same recovery before claims. Completed effects are never
repeated. In-progress effects are marked uncertain and require explicit reconciliation.

Use `--once` to claim at most one job during diagnostics:

```bash
python scripts/bloghub_worker.py --once --log-level DEBUG
```
