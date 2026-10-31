import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import type { EngineSettings, SkillProvenance, ToolsetEntry } from '@shared/wire'
import {
  qk,
  useApp,
  useEngineSettings,
  useLearning,
  useToolsets
} from '../state/app-context'
import { Card } from '../ui/card'
import { Switch } from '../ui/switch'
import { Tabs } from '../ui/tabs'
import { CapabilityRegistrySection } from './CapabilityRegistrySection'
import { ConnectorsSection } from './ConnectorsSection'
import { isSwitchable, setNamesDisabled, toolsetStatus } from './capabilities'

/** The three questions this page answers, one per tab. */
type CapabilityTab = 'skills' | 'connectors' | 'advanced'

const TABS: { id: CapabilityTab; label: string }[] = [
  { id: 'skills', label: 'Skills & plugins' },
  { id: 'connectors', label: 'Connectors' },
  { id: 'advanced', label: 'Advanced' }
]

/**
 * Capabilities — what the assistant can do, split into three tabs.
 *
 * The page used to be one scroll: the whole registry, then the connector tiles, then the engine's
 * toolsets. Three questions were stacked on top of each other, and the connectors alone were ten
 * large cards. The tabs keep each question separate — what the assistant knows, what it can
 * reach, and the engine's own switches — and the connector tab is a compact grouped list.
 *
 * The registry is still the authority: `GET /api/capabilities` composes it from the profile's
 * files, and a row with `toggleable: false` says why it has no switch. The tabs only decide
 * which rows belong together; they do not invent state. The connectors are an account surface,
 * not a capability switch, so their tab has no switches at all.
 *
 * Panels stay mounted and are hidden when inactive, so a pending connector sign-in link (or a
 * half-typed search) survives a tab switch.
 */
export function CapabilitiesPage() {
  const [tab, setTab] = useState<CapabilityTab>('skills')
  const toolsets = useToolsetWriter()
  // The provenance the skills index does not carry: which of these the assistant wrote itself,
  // and how much it has used each one. Read separately because it is a different question — the
  // registry decides what is *offered*, that one records what has been *learned*.
  const { data: learning } = useLearning()
  const provenance = useMemo(() => {
    const map = new Map<string, SkillProvenance>()
    for (const skill of learning?.skills ?? []) map.set(skill.name, skill)
    return map
  }, [learning])

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-4 py-6">
        <header className="flex flex-col gap-1">
          <p className="text-sm text-ink-2">
            What the assistant knows, the apps it can reach, and the engine’s own switches. Each
            tab says what it needs and when a change lands.
          </p>
        </header>

        <Tabs
          items={TABS}
          value={tab}
          onChange={next => setTab(next as CapabilityTab)}
          label="Capabilities sections"
        />

        <div
          role="tabpanel"
          id="panel-skills"
          aria-labelledby="tab-skills"
          hidden={tab !== 'skills'}
          className="flex flex-col gap-4"
        >
          <CapabilityRegistrySection
            provenance={provenance}
            only={['skill', 'plugin']}
            description="The skills the assistant knows and the plugins that give it tools. A row with no switch cannot be switched; it says why."
          />
        </div>

        <div
          role="tabpanel"
          id="panel-connectors"
          aria-labelledby="tab-connectors"
          hidden={tab !== 'connectors'}
          className="flex flex-col gap-4"
        >
          <ConnectorsSection />
        </div>

        <div
          role="tabpanel"
          id="panel-advanced"
          aria-labelledby="tab-advanced"
          hidden={tab !== 'advanced'}
          className="flex flex-col gap-5"
        >
          <WriterNotice writer={toolsets} />
          <CapabilityRegistrySection
            provenance={provenance}
            exclude={['skill', 'plugin', 'connector']}
            title="MCP servers"
            description="Servers this profile can reach. These are not the connectors above; each row is a server the engine knows."
          />
          <AdvancedSection writer={toolsets} />
        </div>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------- writing

/**
 * One switch list, backed by an engine config key.
 *
 * The same shape serves `agent.disabled_toolsets` and (until the registry took it over)
 * `skills.disabled`: both are the engine's own suppression lists, both are re-read when an agent
 * is built, and both are written by replacing the list wholesale through the BFF. Only the key,
 * the valid names, and what has to be invalidated afterwards differ.
 */
interface ToggleWriter {
  /** The engine's list, with an in-flight write shown rather than the stale value. */
  disabled: string[]
  /** Names the engine actually reports; nothing else is ever written. */
  known: string[]
  /** Whether a write can be attempted at all. */
  writable: boolean
  pending: boolean
  error: string | null
  set: (names: string[], on: boolean) => void
}

function useToggleWriter({
  saved,
  known,
  writable,
  save,
  onSaved
}: {
  saved: string[]
  known: string[]
  writable: boolean
  save: (next: string[]) => Promise<string[]>
  onSaved: (next: string[]) => void
}): ToggleWriter {
  const mutation = useMutation({
    mutationFn: (next: string[]) => save(next),
    onSuccess: onSaved
  })

  return {
    // While a write is in flight, show what was asked for rather than the value on disk.
    disabled: mutation.isPending ? (mutation.variables ?? saved) : saved,
    known,
    writable,
    pending: mutation.isPending,
    error: mutation.error instanceof Error ? mutation.error.message : null,
    set: (names, on) => {
      if (!writable || mutation.isPending) return
      mutation.mutate(setNamesDisabled(names, on, saved, known))
    }
  }
}

function useToolsetWriter(): ToggleWriter {
  const { bff } = useApp()
  const queryClient = useQueryClient()
  const { data: settings } = useEngineSettings()
  const { data: toolsets } = useToolsets()

  return useToggleWriter({
    saved: settings?.disabled_toolsets ?? [],
    known: (toolsets ?? []).map(toolset => toolset.name),
    writable: settings?.available === true && settings.profile?.agent_editable !== false,
    save: next => bff.saveDisabledToolsets(next).then(response => response.disabled_toolsets),
    onSaved: next => {
      // Put the written list in the cache before the refetch lands, so a switch does not
      // flick back to its old position for a frame.
      queryClient.setQueryData<EngineSettings>(qk.settings, previous =>
        previous ? { ...previous, disabled_toolsets: next } : previous
      )
      void queryClient.invalidateQueries({ queryKey: qk.toolsets })
      void queryClient.invalidateQueries({ queryKey: qk.settings })
    }
  })
}

/**
 * What to say when a setting is read-only or a write was refused.
 *
 * The registry's own switches have their own notice beside their list; this one is about the
 * engine's files, which both halves ultimately write. `skills.disabled` is still named here
 * because the registry writes it too, through the same guard, and a refusal there reads the same.
 */
function WriterNotice({ writer }: { writer: ToggleWriter }) {
  const { data: settings } = useEngineSettings()
  if (!settings) return null

  if (writer.error) {
    return (
      <Card className="border-danger/40">
        <p className="text-sm text-danger">That change was not saved. {writer.error}</p>
      </Card>
    )
  }

  if (settings.available === false) {
    return (
      <Card className="border-warning/40 bg-warning/5">
        <p className="text-sm text-warning">These switches are read-only right now.</p>
        <p className="text-xs text-ink-2">
          {settings.reason ?? 'No engine profile is configured for this server.'}
        </p>
        <p className="text-xs text-ink-3">
          The engine has no settings API, so switching something off means writing its own
          config file. That needs the server started with the profile:
        </p>
        <p className="font-mono text-[0.68rem] text-ink-disabled">
          python app/server/pantler_server.py --port 8650 --profile-dir &lt;…/profiles/NAME&gt;
        </p>
      </Card>
    )
  }

  const unwritable = [
    settings.profile?.agent_editable === false ? 'agent.disabled_toolsets' : null,
    settings.profile?.skills_editable === false ? 'skills.disabled' : null
  ].filter(Boolean)

  if (unwritable.length > 0) {
    return (
      <Card className="border-warning/40 bg-warning/5">
        <p className="text-sm text-warning">
          This app will not rewrite part of your engine's settings.
        </p>
        <p className="text-xs text-ink-2">
          {unwritable.map((key, index) => (
            <span key={key}>
              {index > 0 && ' and '}
              <code className="font-mono">{key}</code>
            </span>
          ))}{' '}
          in <code className="font-mono">config.yaml</code> holds something other than a plain
          list of names, and guessing at it could break your agent. Edit that by hand.
        </p>
      </Card>
    )
  }

  return null
}

// ------------------------------------------------------------------ advanced

/**
 * The engine's own toolsets, behind a disclosure.
 *
 * They are here rather than in the registry list because the registry reads this profile's files
 * and the toolset list is the engine's, on the far side of the seam. The names, the labels and the
 * state are the engine's own; nothing on this page maps operator words onto toolset strings any
 * more.
 */
function AdvancedSection({ writer }: { writer: ToggleWriter }) {
  const { data: toolsets } = useToolsets()
  const all = toolsets ?? []

  if (all.length === 0) return null
  return <EngineTools toolsets={all} writer={writer} />
}

function EngineTools({ toolsets, writer }: { toolsets: ToolsetEntry[]; writer: ToggleWriter }) {
  return (
    <section className="flex flex-col gap-2">
      <header className="flex flex-col gap-0.5">
        <h3 className="text-display text-xs text-ink-3">Engine tools</h3>
        <p className="text-xs text-ink-3">
          Switch one off and it is written to <code className="font-mono">agent.disabled_toolsets</code>
          , so the tools are genuinely absent from the next conversation. It is reversible, but
          there is rarely a reason to.
        </p>
      </header>

      <Card className="gap-0 py-2">
        {toolsets.map(toolset => (
          <ToolsetRow key={toolset.name} toolset={toolset} writer={writer} />
        ))}
      </Card>
    </section>
  )
}

function ToolsetRow({ toolset, writer }: { toolset: ToolsetEntry; writer: ToggleWriter }) {
  const status = toolsetStatus(toolset, writer.disabled)
  const switchable = isSwitchable(status) && writer.writable
  const count = toolset.tools?.length ?? 0

  return (
    <div className="flex items-center gap-3 border-b border-line/50 py-1.5 last:border-0">
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs text-ink-2">{toolset.label ?? toolset.name}</p>
        <p className="font-mono text-[0.65rem] text-ink-disabled">
          {toolset.name}
          {count > 0 ? ` · ${count} tool${count === 1 ? '' : 's'}` : ''}
        </p>
      </div>
      {status.state === 'unavailable' && (
        <span className="text-[0.65rem] text-ink-disabled">not offered</span>
      )}
      <Switch
        checked={status.state === 'on'}
        disabled={!switchable || writer.pending}
        label={`${toolset.label ?? toolset.name}: ${status.state === 'on' ? 'on' : 'off'}`}
        onCheckedChange={next => writer.set([toolset.name], next)}
      />
    </div>
  )
}
