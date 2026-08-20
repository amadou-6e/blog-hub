export type RemoteSyncStatus = "succeeded" | "partial" | "failed";

export interface RemoteArticleIdentity {
  articleId: string;
  platform: string;
  remoteId: string;
  remoteContentFingerprint: string | null;
  subtitle: string | null;
  coverAssetId: number | null;
  lastSyncStatus: RemoteSyncStatus | null;
  lastSyncResult: Record<string, unknown> | null;
  lastSyncError: string | null;
  remoteCreatedAt: string | null;
  remoteUpdatedAt: string | null;
  lastSyncStartedAt: string | null;
  lastSyncedAt: string | null;
  createdAt: string;
  updatedAt: string;
}
