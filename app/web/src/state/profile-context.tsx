/**
 * The profile registry, as one app-wide fact.
 *
 * Every screen needs the same answer — which businesses exist and which one is selected — and
 * changing it invalidates every cached read on the page (sessions, records, settings, learned
 * skills all belong to a profile). Keeping that in a provider is what stops each screen from
 * inventing its own notion of "current".
 *
 * The provider's own client deliberately has **no** profile header: the registry routes must
 * see the server's answer, not the answer the browser is about to replace.
 */

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useMemo, type ReactNode } from 'react'
import { BffClient, type ProfileGateway, type ProfileSummary, type ProfileWriteResponse } from '../seam/bff'

export const PROFILES_KEY = ['profiles'] as const

const admin = new BffClient()

export interface ProfileScope {
  profiles: ProfileSummary[]
  /** The selected profile's id, or null before the registry has answered. */
  active: string | null
  /** The profile the installation was started with — the one that cannot be deleted. */
  install: string | null
  available: boolean
  reason: string | null
  gateway: ProfileGateway | null
  /** The engine is serving one profile; a second one needs a host restart. */
  restartRequired: boolean
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  activate: (name: string) => Promise<void>
  /** Create a business. The answer says whether the engine can serve it yet. */
  create: (input: {
    name: string
    display_name?: string
    description?: string
    clone_from?: string
  }) => Promise<ProfileWriteResponse>
  update: (
    name: string,
    patch: { new_name?: string; display_name?: string; description?: string }
  ) => Promise<void>
  remove: (name: string) => Promise<void>
}

const ProfileContext = createContext<ProfileScope | null>(null)

export function ProfileProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: PROFILES_KEY,
    queryFn: ({ signal }) => admin.profiles(signal),
    // The registry changes only when this app (or the operator's CLI) changes it. A short
    // freshness window keeps a navigation from re-asking without hiding a real change for long.
    staleTime: 10_000,
    retry: false
  })

  const refresh = useCallback(async () => {
    await query.refetch()
  }, [query])

  const afterWrite = useCallback(async () => {
    await queryClient.invalidateQueries()
    await query.refetch()
  }, [queryClient, query])

  const activate = useCallback(
    async (name: string) => {
      await admin.setActiveProfile(name)
      await afterWrite()
    },
    [afterWrite]
  )

  const create = useCallback(
    async (input: Parameters<ProfileScope['create']>[0]) => {
      const written = await admin.createProfile(input)
      await afterWrite()
      return written
    },
    [afterWrite]
  )

  const update = useCallback(
    async (name: string, patch: Parameters<ProfileScope['update']>[1]) => {
      await admin.updateProfile(name, patch)
      await afterWrite()
    },
    [afterWrite]
  )

  const remove = useCallback(
    async (name: string) => {
      await admin.deleteProfile(name)
      await afterWrite()
    },
    [afterWrite]
  )

  const value = useMemo<ProfileScope>(() => {
    const data = query.data
    return {
      profiles: data?.profiles ?? [],
      active: data?.active ?? null,
      install: data?.install ?? null,
      available: data?.available ?? false,
      reason: data?.reason ?? null,
      gateway: data?.gateway ?? null,
      restartRequired: data?.restart_required ?? false,
      loading: query.isPending,
      error: query.error instanceof Error ? query.error.message : null,
      refresh,
      activate,
      create,
      update,
      remove
    }
  }, [query.data, query.isPending, query.error, refresh, activate, create, update, remove])

  return <ProfileContext.Provider value={value}>{children}</ProfileContext.Provider>
}

export function useProfiles(): ProfileScope {
  const value = useContext(ProfileContext)
  if (!value) throw new Error('useProfiles must be used inside <ProfileProvider>')
  return value
}
