(function () {
  'use strict';

  function requestKey(action, articleId) {
    if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
      return `${action}:${articleId}:${globalThis.crypto.randomUUID()}`;
    }
    return `${action}:${articleId}:${Date.now()}:${Math.random().toString(16).slice(2)}`;
  }

  async function responseError(response) {
    let payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      return { status: response.status, message: `Request failed (${response.status}).` };
    }
    const detail = payload.detail || payload;
    return {
      status: response.status,
      code: detail.error || detail.code || null,
      message: detail.message || (typeof detail === 'string' ? detail : `Request failed (${response.status}).`),
    };
  }

  class OverviewCardActions {
    constructor(options) {
      this.options = options;
      this.open = null;
      this.errors = new Map();
      this.pending = new Set();
      this.keys = new Map();
      this.handlePointerDown = this.handlePointerDown.bind(this);
      this.handleKeyDown = this.handleKeyDown.bind(this);
      document.addEventListener('pointerdown', this.handlePointerDown);
      document.addEventListener('keydown', this.handleKeyDown);
    }

    mount(card, article, tabs) {
      const controls = document.createElement('div');
      controls.className = 'card-state-controls';

      controls.appendChild(this.createGate(article));

      const context = document.createElement('div');
      context.className = 'card-context';
      const trigger = document.createElement('button');
      trigger.type = 'button';
      trigger.className = 'card-context-trigger';
      trigger.setAttribute('aria-label', `Actions for ${article.title}`);
      trigger.setAttribute('aria-haspopup', 'menu');
      trigger.setAttribute('aria-expanded', 'false');
      trigger.textContent = '...';
      trigger.addEventListener('click', event => {
        event.stopPropagation();
        this.toggle(article, context, trigger);
      });
      context.appendChild(trigger);
      controls.appendChild(context);
      tabs.appendChild(controls);

      const savedError = this.errors.get(article.id);
      if (savedError) this.showError(article, context, trigger, savedError);

      card.addEventListener('click', event => {
        if (event.target.closest('.card-state-controls')) event.stopPropagation();
      });
    }

    createGate(article) {
      const result = ['pass', 'warn', 'fail'].includes(article.gate) ? article.gate : 'pending';
      const interactive = result !== 'pending';
      const gate = document.createElement(interactive ? 'button' : 'span');
      gate.className = 'card-gate';
      gate.dataset.state = result;
      gate.textContent = result.toUpperCase();
      if (!interactive) {
        gate.setAttribute('aria-label', 'Inspection pending');
        return gate;
      }
      gate.type = 'button';
      gate.setAttribute('aria-label', `${result} inspection report for ${article.title}`);
      gate.addEventListener('click', event => {
        event.stopPropagation();
        this.options.onInspect(article.id);
      });
      return gate;
    }

    toggle(article, context, trigger) {
      if (this.open && this.open.articleId === article.id) {
        if (!this.open.persistent) {
          this.close(true);
          return;
        }
        this.removePopover(this.open.context);
        this.open = null;
      }
      this.close(false);
      this.errors.delete(article.id);
      this.open = { articleId: article.id, context, trigger };
      trigger.setAttribute('aria-expanded', 'true');
      this.showMenu(article, context, trigger);
    }

    showMenu(article, context, trigger) {
      this.removePopover(context);
      const menu = document.createElement('div');
      menu.className = 'ctx-menu';
      menu.setAttribute('role', 'menu');
      menu.setAttribute('aria-label', `Actions for ${article.title}`);
      [
        ['Edit', 'edit'],
        ['Duplicate', 'duplicate'],
        ['Archive', 'archive'],
        ['Delete', 'delete'],
      ].forEach(([label, action]) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `ctx-item${action === 'delete' ? ' danger' : ''}`;
        button.dataset.action = action;
        button.setAttribute('role', 'menuitem');
        button.textContent = label;
        button.disabled = this.pending.has(article.id);
        button.addEventListener('click', event => {
          event.stopPropagation();
          if (action === 'edit') {
            this.options.onEdit(article.id);
            return;
          }
          if (action === 'delete') {
            this.showDeleteConfirmation(article, context, trigger);
            return;
          }
          void this.mutate(article, action, context, trigger);
        });
        menu.appendChild(button);
      });
      context.appendChild(menu);
      const items = Array.from(menu.querySelectorAll('.ctx-item'));
      menu.addEventListener('keydown', event => {
        const current = items.indexOf(document.activeElement);
        let next = null;
        if (event.key === 'ArrowDown') next = (current + 1) % items.length;
        if (event.key === 'ArrowUp') next = (current - 1 + items.length) % items.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = items.length - 1;
        if (next === null) return;
        event.preventDefault();
        items[next].focus();
      });
      items[0].focus();
    }

    showDeleteConfirmation(article, context, trigger) {
      this.removePopover(context);
      const confirmation = document.createElement('div');
      confirmation.className = 'ctx-menu card-delete-confirmation';
      confirmation.setAttribute('role', 'group');
      confirmation.setAttribute('aria-label', `Delete ${article.title}`);
      confirmation.innerHTML = `
        <strong>Delete this article?</strong>
        <span>Published copies are not removed.</span>
        <div class="card-confirm-actions">
          <button type="button" class="ctx-item card-delete-cancel">Cancel</button>
          <button type="button" class="ctx-item danger card-delete-confirm">Delete</button>
        </div>`;
      confirmation.querySelector('.card-delete-cancel').addEventListener('click', event => {
        event.stopPropagation();
        this.showMenu(article, context, trigger);
      });
      confirmation.querySelector('.card-delete-confirm').addEventListener('click', event => {
        event.stopPropagation();
        void this.mutate(article, 'delete', context, trigger);
      });
      context.appendChild(confirmation);
      confirmation.querySelector('.card-delete-cancel').focus();
    }

    async mutate(article, action, context, trigger) {
      if (this.pending.has(article.id)) return;
      this.pending.add(article.id);
      this.errors.delete(article.id);
      const keyName = `${article.id}:${action}`;
      const idempotencyKey = this.keys.get(keyName) || requestKey(action, article.id);
      this.keys.set(keyName, idempotencyKey);
      this.showPending(article, action, context);

      try {
        const headers = { 'Idempotency-Key': idempotencyKey };
        const response = await fetch(
          `/api/articles/${encodeURIComponent(article.id)}/${action === 'delete' ? '' : action}`.replace(/\/$/, ''),
          { method: action === 'delete' ? 'DELETE' : 'POST', headers },
        );
        if (!response.ok) throw await responseError(response);
        let payload = null;
        if (response.status !== 204) payload = await response.json();
        this.keys.delete(keyName);
        this.close(false);
        await this.options.onSuccess(action, article.id, payload);
      } catch (error) {
        const normalized = error && typeof error.status === 'number'
          ? error
          : { status: 0, message: error.message || 'The action could not be completed.' };
        this.errors.set(article.id, normalized);
        this.showError(article, context, trigger, normalized);
      } finally {
        this.pending.delete(article.id);
      }
    }

    showPending(article, action, context) {
      this.removePopover(context);
      const status = document.createElement('div');
      status.className = 'ctx-menu card-mutation-message';
      status.setAttribute('role', 'status');
      status.textContent = `${action[0].toUpperCase()}${action.slice(1)} in progress...`;
      context.appendChild(status);
    }

    showError(article, context, trigger, error) {
      this.removePopover(context);
      const panel = document.createElement('div');
      panel.className = 'ctx-menu card-mutation-message error';
      panel.setAttribute('role', 'alert');
      const title = error.status === 404
        ? 'Article not found'
        : error.status === 409
          ? 'Cannot delete published article'
          : 'Action failed';
      panel.innerHTML = '<strong></strong><span></span>';
      panel.querySelector('strong').textContent = title;
      panel.querySelector('span').textContent = error.message;
      context.appendChild(panel);
      trigger.setAttribute('aria-expanded', 'true');
      this.open = { articleId: article.id, context, trigger, persistent: true };
    }

    removePopover(context) {
      context.querySelectorAll('.ctx-menu').forEach(element => element.remove());
    }

    close(restoreFocus) {
      if (!this.open) return;
      const { context, trigger, persistent } = this.open;
      if (!persistent) this.removePopover(context);
      trigger.setAttribute('aria-expanded', persistent ? 'true' : 'false');
      this.open = persistent ? this.open : null;
      if (restoreFocus && !persistent && trigger.isConnected) trigger.focus();
    }

    handlePointerDown(event) {
      if (!this.open || this.open.persistent || this.open.context.contains(event.target)) return;
      this.close(false);
    }

    handleKeyDown(event) {
      if (event.key !== 'Escape' || !this.open || this.open.persistent) return;
      event.preventDefault();
      this.close(true);
    }

    clearErrors() {
      this.errors.clear();
      if (this.open && this.open.persistent) {
        this.removePopover(this.open.context);
        this.open.trigger.setAttribute('aria-expanded', 'false');
        this.open = null;
      }
    }
  }

  globalThis.OverviewCardActions = OverviewCardActions;
})();
