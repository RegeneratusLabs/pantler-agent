import { createContext, useContext, useMemo, type ReactNode } from 'react'
import type {
  Capabilities,
  CapabilityRegistry,
  ConnectorsResponse,
  CronJob,
  EngineSettings,
  HealthResponse,
  LearningIndex,
  Pack,
  RecordListResponse,
  SessionLearning,
  SessionListResponse,
  SessionMessage,
  SessionMessagesResponse,
  SessionSummary,
  StoredRecord,
  ToolsetEntry
} from '@shared/wire'
import { QueryClient, useQuery } from '@tanstack/react-query'
import { BffClient } from '../seam/bff'
import { SeamClient, SeamError } from '../seam/client'
import type { SeamSettings } from '../seam/settings'

interface AppContextValue {
  client: SeamClient
  bff: BffClient
  settings: SeamSettings
  /** The profile this provider's clients speak for, when the registry has one. */
  profile: string | null
  /** Point the app at a different engine without a reload. */
  updateSettings: (next: SeamSettings) => void
}

const AppContext = createContext<AppContextValue | null>(null)

export function AppProvider({
  settings,
  updateSettings,
  profile = null,
  children
}: {
  settings: SeamSettings
  updateSettings: (next: SeamSettings) => void
  profile?: string | null
  children: ReactNode
}) {
  const value = useMemo<AppContextValue>(
    () => ({
      // Rebuilt when the profile changes, so every request — including the SSE stream — is
      // addressed to the profile the operator is looking at. The BFF gets the same fact as a
      // header because it is one origin behind `/api`.
      client: new SeamClient({ ...settings, profile }),
      bff: new BffClient('/api', profile),
      settings,
      profile,
      updateSettings
    }),
    [settings, updateSettings, profile]
  )
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp(): AppContextValue {
  const value = useContext(AppContext)
  if (!value) throw new Error('useApp must be used inside <AppProvider>')
  return value
}

/**
 * One query client for the whole app.
 *
 * Queries retry; mutations do not. That is the same rule the seam client encodes for
 * HTTP verbs, restated one level up, and it matters most for `startRun` — a retried
 * non-idempotent write is a double submission, not a convenience.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        staleTime: 5_000,
        refetchOnWindowFocus: false
      },
      mutations: { retry: 0 }
    }
  })
}

// ---------------------------------------------------------------------- keys

export const qk = {
  sessions: ['sessions'] as const,
  session: (id: string) => ['session', id] as const,
  messages: (id: string) => ['session', id, 'messages'] as const,
  jobs: ['jobs'] as const,
  jobRuns: (jobId: string) => ['job-runs', jobId] as const,
  jobRun: (jobId: string, runId: string) => ['job-runs', jobId, runId] as const,
  packs: ['packs'] as const,
  settings: ['settings'] as const,
  bffHealth: ['bff', 'health'] as const,
  health: ['health'] as const,
  capabilities: ['capabilities'] as const,
  capabilityRegistry: ['capability-registry'] as const,
  connectors: ['connectors'] as const,
  toolsets: ['toolsets'] as const,
  learning: ['learning'] as const,
  sessionLearning: (id: string) => ['learning', 'session', id] as const,
  records: (type: string, limit = 100) => ['records', type, limit] as const,
  record: (type: string, id: string) => ['records', type, id] as const
}

// -------------------------------------------------------------------- queries

/**
 * The rail's conversations, and whether the engine is holding any back.
 *
 * The engine windows this route (50 by default) and reports `has_more`; the rail used to model
 * only `data`, so an operator with more than a window of conversations saw the newest fifty
 * presented as the whole list (the internal audit CON-1). The window asked for is larger
 * than the default, and the answer says when it is still not everything.
 */
export interface SessionsWindow {
  sessions: SessionSummary[]
  /** True when the engine held conversations back, so the rail can say so. */
  hasMore: boolean
  /** How many the engine was asked for. */
  limit: number
}

/**
 * The rail's conversations, and whether the engine is holding any back.
 *
 * The engine windows this route (50 by default) and reports `has_more`; the rail used to model
 * only `data`, so an operator with more than a window of conversations saw the newest fifty
 * presented as the whole list (the internal audit CON-1). The window asked for is larger
 * than the default, and the answer says when it is still not everything.
 */
export function useSessions() {
  const { client } = useApp()
  return useQuery<SessionsWindow>({
    queryKey: qk.sessions,
    // The rail stays live while a turn is running elsewhere: a session the engine just
    // created for a new conversation should appear without a manual refresh.
    refetchInterval: 20_000,
    queryFn: async ({ signal }) =>
      readSessionsWindow(await client.listSessions({ limit: SESSION_WINDOW }, signal))
  })
}

/**
 * What a session-list response says about its own window.
 *
 * The engine's `has_more` is the answer, and a full page with no flag is the same fact one step
 * weaker — pinned sessions are excluded from the engine's count, so a page of exactly `limit`
 * rows is the only evidence available without it.
 */
export function readSessionsWindow(response: SessionListResponse): SessionsWindow {
  const sessions = response.data ?? []
  const limit = response.limit ?? SESSION_WINDOW
  return { sessions, limit, hasMore: response.has_more ?? sessions.length >= limit }
}

/**
 * Whether a transcript response was a full page, which is the engine's only way of saying that
 * older messages exist and were not sent: it returns `pagination.returned` rather than a boolean
 * (`api_server.py:3251-3254`).
 */
export function transcriptMayBeIncomplete(response: SessionMessagesResponse): boolean {
  const page = response.pagination
  if (!page || typeof page.returned !== 'number' || typeof page.limit !== 'number') return false
  return page.returned >= page.limit
}

/** How many conversations the rail asks for. The engine caps at 500 and defaults to 50. */
export const SESSION_WINDOW = 100

/**
 * A session's transcript. A brand-new session does not exist in the engine until its first
 * run, so a 404 means "no messages yet", not "something is broken" — anything else is a
 * real error and is rethrown.
 */
export function useSessionMessages(sessionId: string | null) {
  const { client } = useApp()
  return useQuery<SessionMessage[]>({
    queryKey: qk.messages(sessionId ?? ''),
    enabled: Boolean(sessionId),
    retry: false,
    // A transcript is the conversation. A five-second stale window meant that leaving a session
    // and coming back inside it served the cached "no messages yet" answer from before the first
    // turn — and the screen drew an empty conversation over a real one
    // (the internal audit WEB-5). Fresh on mount, and invalidated on send.
    staleTime: 0,
    queryFn: async ({ signal }) => {
      try {
        const response = await client.sessionMessages(sessionId as string, signal)
        return response.data ?? []
      } catch (error) {
        if (error instanceof SeamError && error.status === 404) return []
        throw error
      }
    }
  })
}

/**
 * The same query, plus whether the engine sent a full page — in which case the transcript on
 * screen is the newest `pagination.limit` messages and not the whole conversation
 * (the internal audit CON-2).
 */
export function useSessionTranscript(sessionId: string | null) {
  const { client } = useApp()
  return useQuery<{ messages: SessionMessage[]; incomplete: boolean }>({
    queryKey: qk.messages(sessionId ?? ''),
    enabled: Boolean(sessionId),
    retry: false,
    staleTime: 0,
    queryFn: async ({ signal }) => {
      try {
        const response = await client.sessionMessages(sessionId as string, signal)
        return {
          messages: response.data ?? [],
          incomplete: transcriptMayBeIncomplete(response)
        }
      } catch (error) {
        if (error instanceof SeamError && error.status === 404) {
          return { messages: [], incomplete: false }
        }
        throw error
      }
    }
  })
}

export function useJobs() {
  const { client } = useApp()
  return useQuery<CronJob[]>({
    queryKey: qk.jobs,
    queryFn: ({ signal }) => client.listJobs(true, signal)
  })
}

/** The installed packs and their record types/screens. Read-only; the Records page renders it. */
export function usePacks() {
  const { bff } = useApp()
  return useQuery<Pack[]>({
    queryKey: qk.packs,
    queryFn: ({ signal }) => bff.packs(signal)
  })
}

/**
 * One record type's records, newest first. `type` is null until the page has chosen one, so the
 * query stays idle rather than asking the BFF for a type it does not know.
 */
export function useRecords(type: string | null, limit = 100) {
  const { bff } = useApp()
  return useQuery<RecordListResponse>({
    queryKey: qk.records(type ?? '', limit),
    enabled: Boolean(type),
    staleTime: 0,
    queryFn: ({ signal }) => bff.records(type as string, { limit }, signal)
  })
}

/** One record's detail. A missing id is idle, not an error. */
export function useRecord(type: string | null, id: string | null) {
  const { bff } = useApp()
  return useQuery<StoredRecord>({
    queryKey: qk.record(type ?? '', id ?? ''),
    enabled: Boolean(type && id),
    staleTime: 0,
    queryFn: ({ signal }) => bff.record(type as string, id as string, signal)
  })
}


/**
 * The engine's local settings. Read from the BFF because the engine exposes no settings API;
 * `available: false` is a normal answer, not a failure — it means the server was started
 * without a profile directory, so settings are read-only here.
 */
export function useEngineSettings() {
  const { bff } = useApp()
  return useQuery<EngineSettings>({
    queryKey: qk.settings,
    queryFn: ({ signal }) => bff.settings(signal)
  })
}

/*
 * The model catalogue (`client.modelOptions`, the one settings-shaped route the gateway serves)
 * has no hook here any more: the Settings screen no longer offers model selection, so nothing on
 * this side reads it. The seam method stays — it is the gateway's protocol, not page furniture.
 */


/**
 * The engine's own description of itself, for the rail's footer: `/v1/capabilities` on the far
 * side of the seam. Not the capability registry below — that one is our BFF's read model over
 * the profile's files, and the two answer different questions.
 */
export function useCapabilities() {
  const { client } = useApp()
  return useQuery<Capabilities>({
    queryKey: qk.capabilities,
    queryFn: ({ signal }) => client.capabilities(signal)
  })
}

/** The rail footer's liveness badge: the engine's own health line. */
export function useHealth() {
  const { client } = useApp()
  return useQuery<HealthResponse>({
    queryKey: qk.health,
    refetchInterval: 30_000,
    queryFn: ({ signal }) => client.health(signal)
  })
}

export function useToolsets() {
  const { client } = useApp()
  return useQuery<ToolsetEntry[]>({
    queryKey: qk.toolsets,
    queryFn: ({ signal }) => client.toolsets(signal).then(r => r.data ?? [])
  })
}

/**
 * The capability registry, from the BFF: every switchable thing this profile's own files hold —
 * skills, plugins, MCP servers, and the connector surface, which is listed but not switchable.
 *
 * Not to be confused with `useCapabilities` above, which asks the engine to describe itself. This
 * one is the page's list, and `available: false` is a normal answer (no profile configured), not
 * an error to retry — the same contract as `/api/skills`.
 */
export function useCapabilityRegistry() {
  const { bff } = useApp()
  return useQuery<CapabilityRegistry>({
    queryKey: qk.capabilityRegistry,
    retry: false,
    queryFn: ({ signal }) => bff.capabilities(signal)
  })
}

/**
 * The live connector state, read from Composio through the BFF.
 *
 * While any tile is waiting for the operator to finish a sign-in, the query polls. It stops on
 * its own the moment the last pending account becomes terminal, so a screen left open does not
 * call Composio for ever. A configured-but-broken service answers 200 with an `error` field
 * rather than throwing, which is what lets the card show the sentence and keep the tiles.
 */
export function useConnectors() {
  const { bff } = useApp()
  return useQuery<ConnectorsResponse>({
    queryKey: qk.connectors,
    retry: false,
    queryFn: ({ signal }) => bff.connectors(signal),
    refetchInterval: query => {
      const data = query.state.data as ConnectorsResponse | undefined
      return data?.connectors.some(connector => connector.state === 'pending') ? 2500 : false
    }
  })
}

/**
 * What the assistant has learned, from the BFF.
 *
 * The page is a *record*, not a live view: everything in it is written to the profile's files by
 * the engine, and the engine pushes no notification when it happens — there is no memory, skill
 * or self-improvement event on the seam at all (`app/server/learning.py`). So this polls,
 * slowly, and refetches on demand. `available: false` is a normal answer, not an error.
 */
export function useLearning() {
  const { bff } = useApp()
  return useQuery<LearningIndex>({
    queryKey: qk.learning,
    retry: false,
    staleTime: 15_000,
    refetchInterval: 60_000,
    queryFn: ({ signal }) => bff.learning(signal)
  })
}

/**
 * What one conversation taught it — the engine's own attribution, from the curator's ledger.
 *
 * Fetched only once the conversation has something to attribute: the caller enables it after a
 * run lands, because most conversations teach it nothing and a request per turn would be noise.
 */
export function useSessionLearning(sessionId: string | null, enabled: boolean) {
  const { bff } = useApp()
  return useQuery<SessionLearning>({
    queryKey: qk.sessionLearning(sessionId ?? ''),
    enabled: Boolean(sessionId) && enabled,
    retry: false,
    queryFn: ({ signal }) => bff.sessionLearning(sessionId as string, signal)
  })
}
