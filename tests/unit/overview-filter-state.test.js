const test = require('node:test');
const assert = require('node:assert/strict');

const {
  createDebouncedFilter,
  matchesOverviewFilters,
  normalizeSearch,
} = require('../../screens/overview/filter-state.js');

function article(title, medium, hashnode, devto) {
  return {
    title,
    destinations: {
      medium: { status: medium },
      hashnode: { status: hashnode },
      devto: { status: devto },
    },
  };
}

test('normalizes search without changing the raw input', () => {
  assert.equal(normalizeSearch('  Vector DB  '), 'vector db');
});

test('matches search and the single selected status', () => {
  const draft = article('Building a Vector DB', 'draft', 'none', 'none');
  const published = article('Published vectors', 'published', 'published', 'published');

  assert.equal(matchesOverviewFilters(draft, {
    search: 'VECTOR', status: 'drafting', platforms: [],
  }), true);
  assert.equal(matchesOverviewFilters(draft, {
    search: '', status: 'published', platforms: [],
  }), false);
  assert.equal(matchesOverviewFilters(published, {
    search: '', status: 'published', platforms: [],
  }), true);
});

test('combines selected platforms with OR semantics', () => {
  const hashnodeOnly = article('Hashnode article', 'none', 'draft', 'none');

  assert.equal(matchesOverviewFilters(hashnodeOnly, {
    search: '', status: 'all', platforms: ['medium', 'hashnode'],
  }), true);
  assert.equal(matchesOverviewFilters(hashnodeOnly, {
    search: '', status: 'all', platforms: ['medium', 'devto'],
  }), false);
});

test('debounce settles only the latest rapid value', async () => {
  const settled = [];
  const debounce = createDebouncedFilter(value => settled.push(value), 20);

  debounce.schedule('v');
  debounce.schedule('ve');
  debounce.schedule('vector');
  await new Promise(resolve => setTimeout(resolve, 35));

  assert.deepEqual(settled, ['vector']);
});

test('flush cancels pending work and settles immediately', async () => {
  const settled = [];
  const debounce = createDebouncedFilter(value => settled.push(value), 20);

  debounce.schedule('stale');
  debounce.flush('');
  await new Promise(resolve => setTimeout(resolve, 35));

  assert.deepEqual(settled, ['']);
});
