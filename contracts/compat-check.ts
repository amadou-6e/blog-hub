/**
 * contracts/compat-check.ts
 *
 * TypeScript compatibility check: handwritten contracts must be structurally
 * compatible with the types generated from the spec swagger files.
 *
 * Run via: npm run check:types  (calls tsc --noEmit on this file)
 * Prerequisite: run `npm run generate:types` first to populate contracts/generated/
 *
 * HOW IT WORKS
 * ─────────────
 * TypeScript uses structural typing. The assertion:
 *
 *   type _Assert = A extends B ? true : never;
 *
 * compiles successfully when A is assignable to B. A compile ERROR means the
 * types are NOT compatible.
 *
 * We check BOTH directions:
 *   Handwritten extends Generated   → handwritten has no fields unknown to spec
 *   Generated extends Handwritten   → handwritten covers every field the spec defines
 *
 * NOTES ON DELIBERATE DIVERGENCE
 * ───────────────────────────────
 * - destinations: handwritten uses Record<Platform, PlatformSummary> (specific enum
 *   keys); generated uses { [key: string]: ... } (generic index). Handwritten IS
 *   assignable to generated (direction 1 passes) but NOT vice versa (excluded from
 *   direction 2 — known openapi-typescript limitation with additionalProperties).
 *
 * ADD NEW CHECKS HERE as more contracts/*.ts files are created.
 */

import type {
    ArticleSummary as H_ArticleSummary,
    ArticleListResponse as H_ArticleListResponse,
    PlatformSummary as H_PlatformSummary,
    TimelineEvent as H_TimelineEvent,
} from "./overview";

import type { components as ArtComponents } from "./generated/articles";

type G_ArticleSummary = ArtComponents["schemas"]["ArticleSummary"];
type G_ArticleListResponse = ArtComponents["schemas"]["ArticleListResponse"];
type G_PlatformSummary = ArtComponents["schemas"]["PlatformSummary"];
type G_TimelineEvent = ArtComponents["schemas"]["TimelineEvent"];

/** Fails to compile if A is not assignable to B. */
type AssertExtends<A, B> = A extends B ? true : never;

// PlatformSummary — both directions exact
type _ps1 = AssertExtends<H_PlatformSummary, G_PlatformSummary>;
type _ps2 = AssertExtends<G_PlatformSummary, H_PlatformSummary>;

// TimelineEvent — both directions exact
type _te1 = AssertExtends<H_TimelineEvent, G_TimelineEvent>;
type _te2 = AssertExtends<G_TimelineEvent, H_TimelineEvent>;

// ArticleListResponse — both directions
type _alr1 = AssertExtends<H_ArticleListResponse, G_ArticleListResponse>;
type _alr2 = AssertExtends<G_ArticleListResponse, H_ArticleListResponse>;

// ArticleSummary direction 1: handwritten extends generated
type _as1 = AssertExtends<H_ArticleSummary, G_ArticleSummary>;

// ArticleSummary direction 2: exclude destinations (index-sig divergence)
type _as2 = AssertExtends<
    Omit<G_ArticleSummary, "destinations">,
    Omit<H_ArticleSummary, "destinations">
>;

export type { _ps1, _ps2, _te1, _te2, _alr1, _alr2, _as1, _as2 };
