import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronRight } from 'lucide-react'
import { useState } from 'react'
import type {
  Capability,
  CapabilityKind,
  CapabilityRegistry,
  CapabilityWriteResponse,
  SkillProvenance
} from '@shared/wire'
import { qk, useApp, useCapabilityRegistry } from '../state/app-context'
import { Badge } from '../ui/badge'
import { Card } from '../ui/card'
import { cn } from '../ui/cn'
import { Input } from '../ui/field'
import { Spinner } from '../ui/spinner'
import { Switch } from '../ui/switch'
import {
  DISTRIBUTION_GROUP,
  capabilityRow,
  capabilityWriteFailure,
  capabilityWriteMessage,
  groupCapabilities,
  type CapabilityGroup
} from './capability-rows'

/** Long lists get a filter, as the skills list did. */
const LONG_LIST = 12

/** A group longer than this starts folded; a search opens everything. */
const FOLD_AFTER = 8

/**
 * The registry — every capability this profile can read, in one list.
 *
 * `GET /api/capabilities` composes this from the files the profile already owns: its skills, the
 * plugin manifests, `mcp_servers`, and the connector flag. A row therefore cannot drift from the
 * thing it describes, and a capability that had no card before — the soil plugin, a skill the
 * operator wrote — is simply there (the internal capability plan §3 A6).
 *
 * Toolsets are the one thing it does not carry: their names and their state live on the engine's
 * `GET /v1/toolsets`, so they stay in the Advanced disclosure below rather than being invented
 * here. Everything this section draws comes from the registry, including the two decisions that
 * matter: a row with `toggleable: false` gets its reason and never a switch, and a row whose write
 * waits for a restart says so beside the switch. Those rules live in `capability-rows.ts`, where
 * they are tested without rendering this file.
 */
export function CapabilityRegistrySection({
  provenance,
  only,
  exclude,
  title,
  description
}: {
  provenance: Map<string, SkillProvenance>
  /** Draw only these kinds. The Capabilities tabs use this to split the one registry in two. */
  only?: readonly CapabilityKind[]
  /** Or draw everything except these. The connector row lives in its own tab now. */
  exclude?: readonly CapabilityKind[]
  /** The tab already names the group; a title is only drawn when the block needs one. */
  title?: string
  description?: string
}) {
  const { data, isPending, error } = useCapabilityRegistry()
  const writer = useCapabilityWriter()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<Record<string, boolean>>({})

  const rows = (data?.data ?? []).filter(
    row =>
      (!only || only.includes(row.kind)) &&
      (!exclude || !exclude.includes(row.kind))
  )
  const needle = query.trim().toLowerCase()
  const shown = needle
    ? rows.filter(row =>
        [row.label, row.name, row.description, row.group]
          .filter(Boolean)
          .some(value => value.toLowerCase().includes(needle))
      )
    : rows
  const blocks = groupCapabilities(shown)

  return (
    <section className="flex flex-col gap-3">
      {(title || description) && (
        <header className="flex flex-col gap-0.5">
          {title && <h2 className="text-display text-sm text-ink">{title}</h2>}
          {description && <p className="text-xs text-ink-3">{description}</p>}
        </header>
      )}

      {isPending && <Spinner label="Reading what this profile offers…" />}

      {error && (
        <Card className="border-danger/40">
          <p className="text-sm text-danger">Could not read the capability registry.</p>
        </Card>
      )}

      {data && !data.available && (
        <Card className="border-warning/40 bg-warning/5">
          <p className="text-xs text-ink-2">
            {data.reason ?? 'The capability registry is not readable right now.'}
          </p>
        </Card>
      )}

      {writer.error && (
        <Card className="border-danger/40">
          <p className="text-sm text-danger">That change was not saved. {writer.error}</p>
        </Card>
      )}

      {data?.available && rows.length === 0 && (
        <Card>
          <p className="text-sm text-ink-3">This profile holds no capabilities yet.</p>
        </Card>
      )}

      {data?.available && rows.length > 0 && (
        <>
          {rows.length > LONG_LIST && (
            <Input
              value={query}
              onChange={event => setQuery(event.target.value)}
              placeholder={`Search ${rows.length} capabilities`}
              aria-label="Search capabilities"
              className="h-8 max-w-xs text-xs"
            />
          )}

          {blocks.length === 0 && (
            <p className="px-1 text-xs text-ink-3">Nothing matches “{query}”.</p>
          )}

          {blocks.map(block => (
            <section key={block.kind} className="flex flex-col gap-2">
              <h3 className="text-display text-xs text-ink-3">{block.label}</h3>

              {block.groups.map(group => {
                // `Plugins` under `Plugins` says the same word twice, so a kind whose single
                // group is named after it needs no group header — and nothing to fold away.
                const labelled = block.groups.length > 1 || group.group !== block.label
                const key = `${block.kind}:${group.group}`
                const expanded = needle
                  ? true
                  : (open[key] ??
                    (group.rows.length <= FOLD_AFTER || group.group === DISTRIBUTION_GROUP))

                return labelled ? (
                  <Card key={group.group} className="gap-0 py-0">
                    <button
                      type="button"
                      onClick={() => setOpen(previous => ({ ...previous, [key]: !expanded }))}
                      aria-expanded={expanded}
                      className="flex w-full items-center gap-2.5 py-2.5 text-left"
                    >
                      <ChevronRight
                        className={cn(
                          'size-4 shrink-0 text-ink-3 transition-transform',
                          expanded && 'rotate-90'
                        )}
                      />
                      <span className="min-w-0 flex-1 truncate text-sm text-ink-2">
                        {group.group}
                      </span>
                      {offCount(group) > 0 && (
                        <span className="text-[0.65rem] text-ink-disabled">
                          {offCount(group)} off
                        </span>
                      )}
                      <Badge>{group.rows.length}</Badge>
                    </button>

                    {expanded && <RegistryRows group={group} provenance={provenance} writer={writer} divided />}
                  </Card>
                ) : (
                  <Card key={group.group} className="gap-0 py-2">
                    <RegistryRows group={group} provenance={provenance} writer={writer} />
                  </Card>
                )
              })}
            </section>
          ))}
        </>
      )}
    </section>
  )
}

const offCount = (group: CapabilityGroup) => group.rows.filter(row => !row.enabled).length

// -------------------------------------------------------------------- writing

interface RegistryWriter {
  /** The change in flight, if one is: its id, and what it asked for. */
  pending: { id: string; enabled: boolean } | null
  /** What to tell the operator when the last write was refused, already in words. */
  error: string | null
  write: (id: string, enabled: boolean) => void
}

/**
 * One write path for the whole list, because the registry has one.
 *
 * `PUT /api/capabilities/{id}` dispatches on the id's kind into the writer that already owns that
 * switch, so this screen never has to know which file a change lands in. It does have to know
 * *when* it lands — the answer says so, and the row repeats it. One write at a time: each one
 * rewrites a file the engine reads, and a second in flight would race the first.
 */
function useCapabilityWriter(): RegistryWriter {
  const { bff } = useApp()
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: (change: { id: string; enabled: boolean }) =>
      bff.setCapability(change.id, change.enabled),
    onSuccess: (response: CapabilityWriteResponse) => {
      // The server's answer is the state; put it in the cache before the refetch lands, so the
      // switch does not flick back to its old position for a frame.
      queryClient.setQueryData<CapabilityRegistry>(qk.capabilityRegistry, previous =>
        previous
          ? {
              ...previous,
              data: previous.data.map(row =>
                row.id === response.id ? { ...row, enabled: response.enabled } : row
              )
            }
          : previous
      )
      // The write also moved the engine's own lists, which the settings screen reads.
      void queryClient.invalidateQueries({ queryKey: qk.capabilityRegistry })
      void queryClient.invalidateQueries({ queryKey: qk.settings })
    }
  })

  return {
    pending: mutation.isPending ? (mutation.variables ?? null) : null,
    error: mutation.error ? capabilityWriteMessage(capabilityWriteFailure(mutation.error)) : null,
    write: (id, enabled) => {
      if (mutation.isPending) return
      mutation.mutate({ id, enabled })
    }
  }
}

// ----------------------------------------------------------------------- rows

function RegistryRows({
  group,
  provenance,
  writer,
  divided
}: {
  group: CapabilityGroup
  provenance: Map<string, SkillProvenance>
  writer: RegistryWriter
  divided?: boolean
}) {
  return (
    <ul
      className={cn(
        'flex flex-col gap-2.5',
        divided && 'border-t border-line pb-2.5 pt-2.5'
      )}
    >
      {group.rows.map(capability => (
        <RegistryRow
          key={capability.id}
          capability={capability}
          provenance={provenance.get(capability.name)}
          writer={writer}
        />
      ))}
    </ul>
  )
}

/**
 * One row: what it is, what it needs, when it applies, and the only switch it is allowed.
 *
 * The reading order is the argument. Needs come before the switch so they are known before it is
 * used; the timing comes with them, so a restart is never mistaken for a live change; and a row
 * the registry says is not toggleable gets its reason in the switch's place, because a switch that
 * cannot work is worse than none (the design notes invariant 4).
 */
function RegistryRow({
  capability,
  provenance,
  writer
}: {
  capability: Capability
  provenance?: SkillProvenance
  writer: RegistryWriter
}) {
  const row = capabilityRow(capability)
  const checked = writer.pending?.id === capability.id ? writer.pending.enabled : row.on

  return (
    <li className="flex items-start gap-3">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex flex-wrap items-center gap-1.5 text-sm text-ink">
          {capability.label}
          {capability.kind === 'skill' && provenance?.origin === 'learned' && (
            <Badge tone="accent" title="The assistant wrote this skill itself">
              learned
            </Badge>
          )}
          {(provenance?.uses ?? 0) > 0 && (
            <span className="text-[0.65rem] text-ink-disabled">used {provenance?.uses}×</span>
          )}
        </span>

        {capability.description && (
          <span className="line-clamp-2 text-xs leading-relaxed text-ink-3">
            {capability.description}
          </span>
        )}

        {row.needs.length > 0 && (
          <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[0.68rem] text-ink-2">
            {row.needs.map(need => (
              <span key={need}>{need}</span>
            ))}
          </span>
        )}

        {row.switchable ? (
          <span
            className={cn(
              'text-[0.66rem]',
              row.restartRequired ? 'text-warning' : 'text-ink-disabled'
            )}
          >
            {row.applies}
          </span>
        ) : (
          <span className="text-[0.68rem] leading-relaxed text-ink-disabled">{row.reason}</span>
        )}
      </div>

      {row.switchable ? (
        <Switch
          checked={checked}
          disabled={writer.pending !== null}
          label={`${capability.label}: ${checked ? 'on' : 'off'}`}
          onCheckedChange={next => writer.write(capability.id, next)}
          className="mt-0.5"
        />
      ) : (
        // The state is still the registry's own answer, but it is not a control: no switch is
        // drawn, and the reason above says why.
        <Badge className="mt-0.5" title="This row has no switch; on and off are what the registry reports.">
          {row.on ? 'on' : 'off'}
        </Badge>
      )}
    </li>
  )
}
