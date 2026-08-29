(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.OverviewFilters = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const DRAFTING_STATUSES = new Set(['draft', 'pending', 'review']);

  function normalizeSearch(value) {
    return String(value || '').trim().toLowerCase();
  }

  function matchesOverviewFilters(article, filters) {
    const query = normalizeSearch(filters.search);
    if (query && !String(article.title || '').toLowerCase().includes(query)) return false;

    const destinations = Object.values(article.destinations || {});
    const statuses = destinations.map(destination => destination.status);
    if (filters.status === 'error' && !statuses.includes('error')) return false;
    if (filters.status === 'ready' && !statuses.includes('ready')) return false;
    if (filters.status === 'published' && !statuses.every(status => status === 'published')) return false;
    if (filters.status === 'drafting' && !statuses.some(status => DRAFTING_STATUSES.has(status))) return false;

    const platforms = filters.platforms || [];
    if (platforms.length > 0) {
      const hasSelectedPlatform = platforms.some(platform => {
        const destination = article.destinations && article.destinations[platform];
        return destination && destination.status !== 'none';
      });
      if (!hasSelectedPlatform) return false;
    }
    return true;
  }

  function createDebouncedFilter(onSettle, delay = 250) {
    let timer = null;

    function cancel() {
      if (timer !== null) clearTimeout(timer);
      timer = null;
    }

    function schedule(value) {
      cancel();
      timer = setTimeout(() => {
        timer = null;
        onSettle(value);
      }, delay);
    }

    function flush(value) {
      cancel();
      onSettle(value);
    }

    return { schedule, flush, cancel };
  }

  return { createDebouncedFilter, matchesOverviewFilters, normalizeSearch };
}));
