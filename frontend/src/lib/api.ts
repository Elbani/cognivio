
export type User = {
  id: string;
  email: string;
  name: string;
  emailVerified?: boolean;
  isAdmin?: boolean;
};

// --- Appearance (platform-wide, set from the admin console) ---

export type UserTheme = "terminal" | "editorial";

export type Appearance = {
  userTheme: UserTheme;
  /** True when the server runs without plans, so plan labels and controls are hidden. */
  selfHosted?: boolean;
  /** Contact address for the Teams plan on a hosted install. */
  contactEmail?: string | null;
  updatedAt?: string | null;
  updatedBy?: string | null;
};

export const DEFAULT_APPEARANCE: Appearance = { userTheme: "editorial" };

// --- Admin console ---

export type AdminOverview = {
  days: number;
  totals: {
    users: number;
    verifiedUsers: number;
    suspendedUsers: number;
    orgs: number;
    teams: number;
    memories: number;
    apiKeys: number;
  };
  plans: Record<string, number>;
  storage: {
    dataSize: number;
    storageSize: number;
    indexSize: number;
    totalSize: number;
    freeStorageSize: number;
    fsTotalSize: number | null;
    fsUsedSize: number | null;
    fsFreeSize: number | null;
  } | null;
  signups: Record<string, number>;
  signupTrend: { date: string; count: number }[];
  agentActivity: { byAction: Record<string, number>; totalEvents: number; activeKeys: number; activeOrgs: number };
  retrieval: { lookups: number; hits: number; hitRate: number | null };
  security: { byType: Record<string, number>; totalEvents: number };
};

export type AdminOrgDetail = {
  id: string;
  name: string;
  slug: string | null;
  plan: string;
  createdAt: string | null;
  members: { userId: string; email: string | null; name: string; role: Role; suspended: boolean }[];
  teams: { id: string; name: string; memories: number }[];
  keys: {
    id: string;
    name: string | null;
    prefix: string | null;
    scopes: string[];
    teamId: string | null;
    lastUsedAt: string | null;
    revokedAt: string | null;
    createdAt: string | null;
  }[];
  activity30d: number;
};

export type AdminOrgSso = {
  configured: boolean;
  enabled: boolean;
  required: boolean;
  issuer: string;
  clientId: string;
  hasSecret: boolean;
  domains: string[];
  defaultRole: Role;
  redirectUri: string;
};

export type AdminUser = {
  id: string;
  email: string;
  name: string;
  isAdmin: boolean;
  emailVerified: boolean;
  suspendedAt: string | null;
  suspendedReason: string | null;
  orgCount: number;
  createdAt: string | null;
};

export type AdminOrg = {
  id: string;
  name: string;
  slug: string | null;
  plan: string;
  ownerEmail: string | null;
  members: number;
  teams: number;
  memories: number;
  apiKeys: number;
  createdAt: string | null;
};

export type SecurityEvent = {
  id: string;
  type: string;
  severity: string;
  email: string | null;
  userId: string | null;
  orgId: string | null;
  ip: string | null;
  detail: Record<string, unknown> | null;
  at: string | null;
};

export type AdminAction = {
  id: string;
  action: string;
  adminEmail: string | null;
  targetEmail: string | null;
  targetUserId: string | null;
  targetOrgId: string | null;
  targetOrgName: string | null;
  reason: string | null;
  removed: Record<string, number> | null;
  at: string | null;
};

export type UsageTrendPoint = { date: string; count: number };
export type UsageRetrieval = { lookups: number; hits: number; hitRate: number | null };

export type AdminUsage = {
  days: number;
  totals: { actions: number; activeOrgs: number; activeKeys: number; activeUsers: number };
  byAction: Record<string, number>;
  trend: UsageTrendPoint[];
  retrieval: UsageRetrieval;
  topOrgs: { orgId: string; name: string | null; plan: string | null; actions: number }[];
  topKeys: { keyId: string; keyName: string | null; orgId: string | null; orgName: string | null; actions: number }[];
};

export type AdminUserUsage = {
  userId: string;
  email: string;
  name: string;
  days: number;
  totals: { actions: number; activeKeys: number; lastActiveAt: string | null };
  byAction: Record<string, number>;
  trend: UsageTrendPoint[];
  retrieval: UsageRetrieval;
  perOrg: { orgId: string; name: string | null; plan: string | null; role: string | null; actions: number }[];
  perKey: {
    keyId: string;
    keyName: string | null;
    prefix: string | null;
    orgId: string | null;
    orgName: string | null;
    actions: number;
    lastUsedAt: string | null;
    revoked: boolean;
  }[];
};

export type Role = "owner" | "admin" | "editor" | "viewer";

export type Org = {
  id: string;
  name: string;
  slug: string;
  role: Role;
  plan?: string;
  ssoEnabled?: boolean;
  ssoRequired?: boolean;
  ssoDomains?: string[];
  createdAt: string;
  updatedAt: string;
};

export type Team = {
  id: string;
  orgId: string;
  name: string;
  slug: string;
  agentWriteReview?: boolean;
  createdAt: string;
  updatedAt: string;
};

export type Member = {
  userId: string;
  email: string;
  name: string;
  role: Role;
  teamId: string | null;
};

export type Folder = {
  id: string;
  teamId: string;
  name: string;
  parentId: string | null;
  createdAt: string;
  updatedAt: string;
};

export type MemoryType =
  | "map"
  | "architecture"
  | "playbook"
  | "incident"
  | "decision"
  | "lesson"
  | "note";

export type MemoryStatus = "active" | "draft" | "deprecated";
export type MemorySource = "manual" | "agent" | "ingested";

export type Memory = {
  id: string;
  orgId: string;
  teamId: string;
  folderId: string | null;
  type: MemoryType;
  status: MemoryStatus;
  title: string;
  content: string;
  tags: string[];
  linkedMemoryIds: string[];
  unresolvedLinks: string[];
  source: MemorySource;
  sourceRef?: Record<string, unknown> | null;
  helpfulCount: number;
  notHelpfulCount: number;
  lastVerifiedAt: string | null;
  verifiedBy: string | null;
  createdBy: string | null;
  updatedBy: string | null;
  createdAt: string;
  updatedAt: string;
  lastOpenedAt: string | null;
  deletedAt: string | null;
};

export type MemoryListItem = Omit<Memory, "content"> & { content?: string };

export type ApiScope = "memory:read" | "memory:write" | "map:read";

export type ApiKey = {
  id: string;
  orgId: string;
  teamId: string | null;
  name: string;
  prefix: string;
  scopes: ApiScope[];
  createdAt: string;
  lastUsedAt: string | null;
  expiresAt: string | null;
  revokedAt: string | null;
};

export type ApiKeyCreated = ApiKey & { key: string };

export type MapNode = {
  id: string;
  title: string;
  type: MemoryType;
  status: MemoryStatus;
  tags: string[];
};

export type MapEdge = { source: string; target: string };

export type MapResponse = {
  teamId: string;
  mapMemory: Memory | null;
  nodes: MapNode[];
  edges: MapEdge[];
};

export type AuditEntry = {
  id: string;
  action: string;
  actor: string;
  keyName: string | null;
  teamId: string | null;
  memoryId: string | null;
  memoryTitle?: string | null;
  memoryDeleted?: boolean;
  query: string | null;
  at: string;
};

export type AuthResponse = {
  accessToken: string;
  user: User;
};

export type Insights = {
  coverage: {
    docs: number;
    teams: number;
    teamsWithMap: number;
    stale: number;
    byType: Record<string, number>;
  };
  gaps: { query: string; missCount: number; examples: string[]; lastAt: string | null }[];
  activity: {
    days: number;
    totalEvents: number;
    byAction: Record<string, number>;
    activeKeys: number;
    reads: number;
    writes: number;
  };
  retrieval: {
    lookups: number;
    hits: number;
    hitRate: number | null;
  };
  usefulness: {
    helpful: number;
    notHelpful: number;
    ratedDocs: number;
    lowSignal: { id: string; title: string; type: MemoryType; helpful: number; notHelpful: number }[];
  };
  docs: {
    topRead: { id: string; title: string; type: MemoryType; reads: number; deleted: boolean }[];
    neverRead: { id: string; title: string; type: MemoryType }[];
    neverReadCount: number;
  };
};

// --- Project documentation (human-facing dev handbook; separate from agent memories) ---

export type ProjectDocSection = { slug: string; title: string; order: number; content?: string };

export type ProjectDocsVersion = {
  id: string;
  version: number;
  status: "current" | "archived";
  summary: string;
  source: string | null;
  sourceRef?: Record<string, unknown> | null;
  sectionCount: number;
  createdAt: string | null;
  sections: ProjectDocSection[];
};

export type ProjectDocsCurrent = {
  teamId: string;
  hasDocs: boolean;
  current: ProjectDocsVersion | null;
  versionCount: number;
};

export type ProjectDocsVersionList = { teamId: string; versions: ProjectDocsVersion[] };

export type ProjectDocsDiff = {
  from: number;
  to: number;
  sections: {
    slug: string;
    title: string | null;
    status: "added" | "removed" | "changed" | "unchanged";
    diff: string;
  }[];
};

export const MEMORY_TYPES: MemoryType[] = [
  "map",
  "architecture",
  "playbook",
  "incident",
  "decision",
  "lesson",
  "note"
];

export const MEMORY_TYPE_LABELS: Record<MemoryType, string> = {
  map: "Project Map",
  architecture: "How It Works",
  playbook: "Guide",
  incident: "Incident",
  decision: "Decision",
  lesson: "Lesson",
  note: "Note"
};

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  token?: string | null;
};

// The app registers a handler here so a 401 mid-session (expired access token) clears
// auth and routes back to login, instead of every call silently failing. Auth endpoints
// are exempt, a 401 from /api/auth/* is an expected "not signed in", not a dropped session.
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export async function apiRequest<T>(
  path: string,
  { body, token, headers, ...options }: RequestOptions = {}
): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers
    },
    body: body !== undefined ? JSON.stringify(body) : undefined
  });

  if (response.status === 401 && !path.startsWith("/api/auth/")) {
    onUnauthorized?.();
  }

  if (!response.ok) {
    let message = "Request failed";
    try {
      const payload = await response.json();
      message = payload.detail ?? message;
    } catch {
      message = response.statusText || message;
    }
    throw new Error(message);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}
