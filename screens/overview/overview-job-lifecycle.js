(function (root, factory) {
  const exported = factory();
  if (typeof module === 'object' && module.exports) module.exports = exported;
  root.OverviewJobLifecycle = exported.OverviewJobLifecycle;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const BUSY = new Set(['submitting', 'queued', 'running', 'retrying', 'recovering', 'canceling']);
  const TERMINAL = new Set(['completed', 'done', 'failed', 'canceled', 'expired']);

  function randomKey(prefix) {
    const value = globalThis.crypto && globalThis.crypto.randomUUID
      ? globalThis.crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return `${prefix}:${value}`;
  }

  class OverviewJobLifecycle {
    constructor({ request, storage, onChange, onCompleted, sleep } = {}) {
      this.request = request;
      this.storage = storage;
      this.onChange = onChange || (() => {});
      this.onCompleted = onCompleted || (async () => {});
      this.sleep = sleep || (milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)));
      this.states = new Map();
      this.pollTokens = new Map();
    }

    state(articleId) {
      return this.states.get(articleId) || null;
    }

    isBusy(articleId) {
      const current = this.state(articleId);
      return Boolean(current && BUSY.has(current.status));
    }

    _set(articleId, next) {
      const value = { articleId, ...next };
      this.states.set(articleId, value);
      this.onChange(articleId, value);
      return value;
    }

    _clear(articleId) {
      this.states.delete(articleId);
      this.pollTokens.delete(articleId);
      this.onChange(articleId, null);
    }

    _storageKey(articleId, operation) {
      return `bloghub:overview:job-key:${articleId}:${operation}`;
    }

    _submissionKey(articleId, operation) {
      const key = this._storageKey(articleId, operation);
      let value = this.storage && this.storage.getItem(key);
      if (!value) {
        value = randomKey(`${articleId}:${operation}`);
        if (this.storage) this.storage.setItem(key, value);
      }
      return value;
    }

    _forgetSubmissionKey(articleId, operation) {
      if (this.storage) this.storage.removeItem(this._storageKey(articleId, operation));
    }

    _retryStorageKey(jobId) {
      return `bloghub:overview:retry-key:${jobId}`;
    }

    _retryKey(jobId) {
      const key = this._retryStorageKey(jobId);
      let value = this.storage && this.storage.getItem(key);
      if (!value) {
        value = randomKey(`retry:${jobId}`);
        if (this.storage) this.storage.setItem(key, value);
      }
      return value;
    }

    _forgetRetryKey(jobId) {
      if (this.storage) this.storage.removeItem(this._retryStorageKey(jobId));
    }

    async submit(articleId, operation, body = {}) {
      if (this.isBusy(articleId)) return this.state(articleId);
      const idempotencyKey = this._submissionKey(articleId, operation);
      this._set(articleId, { status: 'submitting', operation, idempotencyKey });
      try {
        const accepted = await this.request(`/api/articles/${encodeURIComponent(articleId)}/${operation}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
          body: JSON.stringify(body),
        });
        return this._attach(articleId, {
          ...accepted,
          operation,
          status: accepted.status || 'queued',
        });
      } catch (error) {
        return this._set(articleId, {
          status: 'failed', operation, idempotencyKey,
          error: error.message || 'The action could not be submitted.',
          retryable: true, retryMode: 'submit',
        });
      }
    }

    async recover(articleId) {
      if (this.isBusy(articleId)) return this.state(articleId);
      this._set(articleId, { status: 'recovering', operation: null });
      try {
        const payload = await this.request(
          `/api/jobs?article_id=${encodeURIComponent(articleId)}&active=true&limit=10`
        );
        const job = (payload.jobs || []).find(item => item.operation === 'push' || item.operation === 'inspect');
        if (job) return this._attach(articleId, job);
        await this.onCompleted(articleId, null);
        this._clear(articleId);
        return null;
      } catch (error) {
        return this._set(articleId, {
          status: 'recovery-error', operation: null,
          error: error.message || 'Could not restore job status.',
        });
      }
    }

    async retryRecovery(articleId) {
      this._clear(articleId);
      return this.recover(articleId);
    }

    async retry(articleId) {
      const current = this.state(articleId);
      if (!current || !current.retryable) return current;
      if (current.retryMode === 'submit') {
        this._clear(articleId);
        return this.submit(articleId, current.operation);
      }
      if (!current.jobId || this.isBusy(articleId)) return current;
      const retryKey = this._retryKey(current.jobId);
      this._set(articleId, { ...current, status: 'retrying', idempotencyKey: retryKey });
      try {
        const job = await this.request(`/api/jobs/${encodeURIComponent(current.jobId)}/retry`, {
          method: 'POST', headers: { 'Idempotency-Key': retryKey },
        });
        this._forgetRetryKey(current.jobId);
        return this._attach(articleId, job);
      } catch (error) {
        return this._set(articleId, {
          ...current, status: 'failed',
          error: error.message || 'The retry was rejected.',
        });
      }
    }

    async cancel(articleId) {
      const current = this.state(articleId);
      if (!current || !current.jobId || !['queued', 'running', 'retrying'].includes(current.status)) return current;
      this._set(articleId, { ...current, status: 'canceling' });
      try {
        const job = await this.request(`/api/jobs/${encodeURIComponent(current.jobId)}/cancel`, { method: 'POST' });
        return this._attach(articleId, job);
      } catch (error) {
        return this._set(articleId, {
          ...current, status: current.status,
          error: error.message || 'Cancellation could not be requested.',
        });
      }
    }

    _attach(articleId, job) {
      const normalized = {
        ...job,
        jobId: job.jobId || job.job_id,
        operation: job.operation || job.type,
        status: job.status === 'waiting' ? 'retrying' : job.status,
        pollUrl: job.pollUrl || `/api/jobs/${job.jobId || job.job_id}`,
        pollAfterMs: job.pollAfterMs || 2000,
      };
      this._set(articleId, normalized);
      if (!TERMINAL.has(normalized.status)) void this._poll(articleId, normalized.jobId);
      else void this._finish(articleId, normalized);
      return normalized;
    }

    async _poll(articleId, jobId) {
      const token = Symbol(jobId);
      this.pollTokens.set(articleId, token);
      while (this.pollTokens.get(articleId) === token) {
        const current = this.state(articleId);
        if (!current || current.jobId !== jobId || TERMINAL.has(current.status)) return;
        await this.sleep(current.pollAfterMs || 2000);
        if (this.pollTokens.get(articleId) !== token) return;
        try {
          const job = await this.request(current.pollUrl || `/api/jobs/${encodeURIComponent(jobId)}`);
          const normalized = {
            ...current, ...job,
            operation: job.operation || job.type || current.operation,
            status: job.status === 'waiting' ? 'retrying' : job.status,
          };
          this._set(articleId, normalized);
          if (TERMINAL.has(normalized.status)) {
            await this._finish(articleId, normalized);
            return;
          }
        } catch (error) {
          this._set(articleId, {
            ...current,
            error: error.message || 'Job status could not be refreshed. Retrying...',
          });
        }
      }
    }

    async _finish(articleId, job) {
      this.pollTokens.delete(articleId);
      if (job.status === 'completed' || job.status === 'done') {
        this._forgetSubmissionKey(articleId, job.operation);
        this._set(articleId, { ...job, status: 'completed' });
        await this.onCompleted(articleId, job);
        this._clear(articleId);
        return;
      }
      this._forgetSubmissionKey(articleId, job.operation);
      this._set(articleId, {
        ...job,
        status: job.status === 'expired' ? 'failed' : job.status,
        error: job.error || (job.status === 'canceled' ? 'The job was canceled.' : 'The job failed.'),
      });
    }
  }

  return { OverviewJobLifecycle };
});
