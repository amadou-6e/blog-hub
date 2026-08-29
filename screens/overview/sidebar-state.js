(function initOverviewSidebarState(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.OverviewSidebarState = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function createOverviewSidebarState() {
  const PLATFORMS = ['medium', 'hashnode', 'devto'];
  const KNOWN_STATUSES = new Set([
    'none', 'draft', 'review', 'ready', 'pending', 'error', 'published',
  ]);

  function normalizeDestination(value) {
    const destination = value && typeof value === 'object' ? value : {};
    const status = KNOWN_STATUSES.has(destination.status) ? destination.status : 'none';
    const suppliedLabel = typeof destination.label === 'string'
      ? destination.label.trim()
      : '';
    return {
      ...destination,
      status,
      label: status === 'none'
        ? 'Unavailable'
        : suppliedLabel || `${status.charAt(0).toUpperCase()}${status.slice(1)}`,
      url: typeof destination.url === 'string' && destination.url ? destination.url : null,
    };
  }

  function normalizeDestinations(value) {
    const destinations = value && typeof value === 'object' ? value : {};
    return Object.fromEntries(
      PLATFORMS.map(platform => [platform, normalizeDestination(destinations[platform])]),
    );
  }

  function normalizeTimeline(value, formatTime) {
    if (!Array.isArray(value)) return [];
    return value
      .filter(item => item && typeof item === 'object')
      .map(item => ({
        time: formatTime(item.timestamp),
        event: typeof item.event === 'string' ? item.event : '',
      }));
  }

  function selectedArticle(articles, selectedId) {
    if (!selectedId || !Array.isArray(articles)) return null;
    return articles.find(article => article.id === selectedId) || null;
  }

  function panelModel(article, activeJob) {
    if (!article) return null;
    const action = article.action || {
      kind: 'push', label: 'Push drafts \u2192', color: '#fff', bg: '#6366f1', border: '#6366f1',
    };
    const busyLabel = activeJob === 'inspect' ? 'Inspecting\u2026' : 'Pushing\u2026';
    return {
      title: typeof article.title === 'string' && article.title.trim()
        ? article.title
        : 'Untitled article',
      destinations: PLATFORMS.map(platform => ({
        platform,
        ...normalizeDestination(article.destinations && article.destinations[platform]),
      })),
      timeline: Array.isArray(article.timeline) ? article.timeline : [],
      primaryAction: activeJob ? { ...action, label: busyLabel, disabled: true } : action,
      inspectDisabled: Boolean(activeJob),
    };
  }

  return {
    PLATFORMS,
    normalizeDestination,
    normalizeDestinations,
    normalizeTimeline,
    selectedArticle,
    panelModel,
  };
}));
