/**
 * UI Contract — Overview screen
 *
 * Describes every piece of data the Overview screen reads from the backend,
 * the REST endpoints that supply it, and the write operations it triggers.
 *
 * Convention:
 *   - All timestamps are ISO-8601 strings (UTC).
 *   - Nullable fields are marked `| null`.
 *   - Fields marked `// derived` are computed on the client; no backend call needed.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Shared enums
// ─────────────────────────────────────────────────────────────────────────────

/** Status of an article on a single publishing platform. */
export type PlatformStatus =
    | 'none'        // not yet linked / never pushed
    | 'draft'       // pushed but not published
    | 'review'      // needs human review before publishing
    | 'ready'       // validated, queued to publish
    | 'pending'     // push in-flight
    | 'error'       // last push attempt failed
    | 'published';  // live on the platform

/** Result of the automated gate / inspection check. */
export type GateStatus = 'pass' | 'warn' | 'fail' | 'pending';

/** Supported publishing destinations. */
export type Platform = 'medium' | 'hashnode' | 'devto';

// ─────────────────────────────────────────────────────────────────────────────
// Read models (backend → UI)
// ─────────────────────────────────────────────────────────────────────────────

/** One row in the per-platform status grid. */
export interface PlatformSummary {
    status: PlatformStatus;
    /** Human-readable short label ("Draft v2", "Published", "Error", …). */
    label: string;
    /** Live URL when status === 'published', otherwise null. */
    url: string | null;
    /** Short error message when status === 'error', otherwise null. */
    error: string | null;
}

/** A single entry in the article's activity timeline. */
export interface TimelineEvent {
    /** ISO-8601 timestamp. */
    timestamp: string;
    /** Human-readable description ("Draft pushed to Medium", "Gate passed", …). */
    event: string;
}

/**
 * Article summary — one row in the overview table.
 * Lightweight: does NOT include full markdown content.
 */
export interface ArticleSummary {
    id: string;                       // e.g. "art_7g2kf"
    title: string;
    /** ISO-8601 of last edit to the article content or destinations. */
    updatedAt: string;
    wordCount: number;                // character count is derived client-side
    gate: GateStatus;
    /** Authenticated local cover URL, or null to use the deterministic fallback. */
    previewImageUrl: string | null;
    destinations: Record<Platform, PlatformSummary>;
    /** Last 5 timeline events, newest first. Full history on article-detail. */
    recentTimeline: TimelineEvent[];
}

/**
 * Response for the article list endpoint.
 * Supports pagination so the overview can load incrementally.
 */
export interface ArticleListResponse {
    items: ArticleSummary[];
    total: number;
    page: number;
    pageSize: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Query parameters
// ─────────────────────────────────────────────────────────────────────────────

export interface ArticleListQuery {
    /** Full-text search on title and body. */
    q?: string;
    /** Filter by gate status. */
    gate?: GateStatus;
    /** Filter by platform status on any platform. */
    status?: PlatformStatus;
    /** Filter to articles with any destination on this platform. */
    platform?: Platform;
    page?: number;        // default: 1
    pageSize?: number;    // default: 20, max: 100
    /** Field to sort by. */
    sortBy?: 'updatedAt' | 'createdAt' | 'title';
    sortDir?: 'asc' | 'desc';  // default: 'desc'
}

// ─────────────────────────────────────────────────────────────────────────────
// Write operations (UI → backend)
// ─────────────────────────────────────────────────────────────────────────────

/** Payload for creating a new article from the overview "+ New article" button. */
export interface CreateArticleRequest {
    title: string;
}

export interface CreateArticleResponse {
    id: string;
    title: string;
    createdAt: string;
}

/** Payload for deleting an article (bulk action from overview). */
export interface DeleteArticleRequest {
    ids: string[];
}

// ─────────────────────────────────────────────────────────────────────────────
// REST endpoints
// ─────────────────────────────────────────────────────────────────────────────

/**
 * GET /api/articles
 *   Query:    ArticleListQuery
 *   Response: ArticleListResponse
 *   Used by:  Overview table, search bar, filter chips
 *
 * POST /api/articles
 *   Body:     CreateArticleRequest
 *   Response: CreateArticleResponse
 *   Used by:  "New article" button → navigates to /editor/:id
 *
 * DELETE /api/articles
 *   Body:     DeleteArticleRequest
 *   Response: 204 No Content
 *   Used by:  Bulk delete action (future)
 */

// ─────────────────────────────────────────────────────────────────────────────
// Client-derived values (no backend call)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * The following are computed on the client from ArticleSummary fields:
 *
 *   readTime     — Math.ceil(wordCount / 200) + ' min read'
 *   updatedLabel — relative label ("2h ago", "3d ago") from updatedAt
 *   overallStatus — worst PlatformStatus across all destinations:
 *                   error > pending > review > ready > draft > none > published
 */
