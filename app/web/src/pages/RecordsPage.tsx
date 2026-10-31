import { Database, FileDown, MessageSquare, Printer, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import type { StoredRecord } from '@shared/wire'
import { usePacks, useRecord, useRecords } from '../state/app-context'
import { useProfiles } from '../state/profile-context'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Card, CardHeader } from '../ui/card'
import { cn } from '../ui/cn'
import { EmptyState } from '../ui/empty'
import { Select } from '../ui/field'
import { Spinner } from '../ui/spinner'
import {
  formatFieldValue,
  recordTitle,
  recordTypeOptions,
  recordsFilename,
  recordsToCsv,
  type RecordTypeOption
} from './records'

/**
 * Records — what the assistant has actually recorded, read from the BFF and never through a run.
 *
 * This page is deliberately read-only. The manager is the conversation and the record tools: the
 * assistant extracts, the kernel validates, and the record is written once. A screen that wrote
 * here would be a second implementation of "make a record", which is the thing the kernel's
 * `RecordBook` exists to prevent (the records design §2). Export and print are the operator's ways
 * out of the store; the record itself stays where it was written.
 *
 * The page is generic over the packs: a custom cleaning log appears beside a spray application,
 * with the fields and columns its pack declares. No pack-specific code lives here.
 */
export function RecordsPage() {
  const navigate = useNavigate()
  const { profiles, active } = useProfiles()
  const business =
    profiles.find(profile => profile.name === active)?.display_name?.trim() || active || ''
  const packsQuery = usePacks()
  const packs = packsQuery.data ?? []
  const options = useMemo(() => recordTypeOptions(packs), [packs])

  // A capture card links here as `/records?type=capture&id=CAP-0001`. The first render takes
  // the requested type and id, so the detail opens in place instead of dumping the operator on
  // the default type and making them find the row again.
  const [searchParams] = useSearchParams()
  const requestedType = searchParams.get('type')
  const requestedId = searchParams.get('id')
  const [typeName, setTypeName] = useState<string | null>(requestedType)
  const [selectedId, setSelectedId] = useState<string | null>(requestedType ? requestedId : null)
  const [limit, setLimit] = useState(100)

  // The pack list can arrive after the first render, and a profile switch can replace it. Pick the
  // first type when there is none, or when the chosen one has gone away.
  useEffect(() => {
    if (options.length === 0) {
      if (typeName !== null) setTypeName(null)
      return
    }
    if (!typeName || !options.some(option => option.record.type === typeName)) {
      setTypeName(options[0].record.type)
      setSelectedId(null)
      setLimit(100)
    }
  }, [options, typeName])

  const selected = options.find(option => option.record.type === typeName)
  const recordsQuery = useRecords(typeName, limit)
  const detailQuery = useRecord(typeName, selectedId)

  const records = recordsQuery.data?.data ?? []
  const total = recordsQuery.data?.total ?? 0
  const error = packsQuery.error ?? recordsQuery.error ?? detailQuery.error
  const loading = packsQuery.isPending || recordsQuery.isPending

  const choose = (name: string) => {
    setTypeName(name)
    setSelectedId(null)
    setLimit(100)
  }

  const refresh = () => {
    void packsQuery.refetch()
    void recordsQuery.refetch()
    if (selectedId) void detailQuery.refetch()
  }

  const exportCsv = () => {
    if (!selected || records.length === 0) return
    download(recordsFilename(selected.record.type), recordsToCsv(selected.record, records))
  }

  return (
    <div className="records-scroll min-h-0 flex-1 overflow-y-auto">
      <div className="records-print mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 py-6">
        <header className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-display text-sm text-ink">Records</h2>
            <p className="mt-0.5 max-w-2xl text-xs leading-relaxed text-ink-3">
              Everything the assistant has recorded, in the store it was written to. This page only
              reads: ask in chat to add, correct or forget a record.
            </p>
            {business && <p className="mt-1 text-[0.68rem] text-ink-disabled">{business}</p>}
          </div>
          <div className="print-hide flex flex-wrap shrink-0 items-center gap-2">
            <Button variant="ghost" size="sm" onClick={refresh} disabled={recordsQuery.isFetching}>
              <RefreshCw className={cn('size-3.5', recordsQuery.isFetching && 'animate-spin')} />
              Refresh
            </Button>
            <Button variant="ghost" size="sm" onClick={() => navigate('/chat')}>
              <MessageSquare className="size-3.5" />
              Ask in chat
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={exportCsv}
              disabled={!selected || records.length === 0}
            >
              <FileDown className="size-3.5" />
              Export CSV
            </Button>
            <Button variant="secondary" size="sm" onClick={() => window.print()}>
              <Printer className="size-3.5" />
              Print
            </Button>
          </div>
        </header>

        {error && (
          <Card className="border-danger/40">
            <p className="text-sm text-danger">Could not read the records.</p>
            <p className="text-xs text-ink-3">
              {error instanceof Error ? error.message : String(error)}
            </p>
          </Card>
        )}

        {loading && <Spinner label="Reading the records…" />}

        {!loading && packs.length === 0 && (
          <Card>
            <EmptyState
              className="py-10"
              icon={<Database className="size-5" />}
              title="No record types installed"
              action={
                <Button variant="secondary" onClick={() => navigate('/chat')}>
                  <MessageSquare className="size-3.5" />
                  Ask in chat
                </Button>
              }
            >
              This installation has no packs, so there is nothing to show yet. The assistant can
              propose a record type for a new kind of log.
            </EmptyState>
          </Card>
        )}

        {!loading && options.length > 0 && (
          <div className="grid gap-5 lg:grid-cols-[15rem_minmax(0,1fr)]">
            <TypeRail options={options} selected={typeName} onSelect={choose} />

            <div className="print-hide lg:hidden">
              <Select
                aria-label="Record type"
                value={typeName ?? ''}
                onChange={event => choose(event.target.value)}
              >
                {options.map(option => (
                  <option key={option.record.type} value={option.record.type}>
                    {option.record.label} — {option.pack.name}
                  </option>
                ))}
              </Select>
            </div>

            {selected && (
              <section className="flex min-w-0 flex-col gap-4">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <h3 className="text-display text-base text-ink">{selected.record.plural ?? selected.record.label}</h3>
                  <span className="text-xs text-ink-3">
                    {total} {total === 1 ? 'record' : 'records'}
                  </span>
                  {selected.pack.custom && <Badge tone="accent">custom</Badge>}
                  <span className="text-xs text-ink-disabled">{selected.pack.name}</span>
                </div>
                <p className="hidden text-xs text-ink-3 print:block">
                  {business ? `${business} · ` : ''}
                  {selected.record.plural ?? selected.record.label} · printed{' '}
                  {new Date().toLocaleDateString()}
                </p>

                <RecordTable
                  option={selected}
                  records={records}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  onAsk={() => navigate('/chat')}
                  loading={recordsQuery.isPending}
                />

                {records.length > 0 && (
                  <div className="print-hide flex flex-wrap items-center gap-3 text-xs text-ink-3">
                    <span>
                      Showing {records.length} of {total}
                    </span>
                    {total > records.length && records.length < 500 && (
                      <Button
                        variant="quiet"
                        size="sm"
                        onClick={() => setLimit(value => Math.min(500, value + 100))}
                        disabled={recordsQuery.isFetching}
                      >
                        Load more
                      </Button>
                    )}
                  </div>
                )}

                {selectedId && (
                  <RecordDetail
                    option={selected}
                    record={detailQuery.data}
                    loading={detailQuery.isPending}
                    error={detailQuery.error}
                    onClose={() => setSelectedId(null)}
                  />
                )}
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function TypeRail({
  options,
  selected,
  onSelect
}: {
  options: RecordTypeOption[]
  selected: string | null
  onSelect: (name: string) => void
}) {
  return (
    <nav aria-label="Record types" className="print-hide hidden flex-col gap-1 lg:flex">
      {options.map(option => {
        const active = option.record.type === selected
        return (
          <button
            key={option.record.type}
            type="button"
            onClick={() => onSelect(option.record.type)}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'flex items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm transition-colors',
              active ? 'bg-hover font-medium text-ink' : 'text-ink-2 hover:bg-hover hover:text-ink'
            )}
          >
            <Database className="size-3.5 shrink-0" aria-hidden />
            <span className="min-w-0 flex-1">
              <span className="block truncate">{option.record.label}</span>
              <span className="block truncate text-[0.65rem] text-ink-disabled">
                {option.pack.name}
              </span>
            </span>
            {option.pack.custom && <Badge tone="accent">custom</Badge>}
          </button>
        )
      })}
    </nav>
  )
}

function RecordTable({
  option,
  records,
  selectedId,
  onSelect,
  onAsk,
  loading
}: {
  option: RecordTypeOption
  records: StoredRecord[]
  selectedId: string | null
  onSelect: (id: string) => void
  onAsk: () => void
  loading: boolean
}) {
  if (loading) return <Spinner label="Reading records…" />
  if (records.length === 0) {
    return (
      <Card>
        <EmptyState
          className="py-10"
          icon={<Database className="size-5" />}
          title="Nothing recorded yet"
          action={
            <Button variant="secondary" onClick={onAsk}>
              <MessageSquare className="size-3.5" />
              Ask in chat
            </Button>
          }
        >
          Ask the assistant to record one, and it will appear here with the id the store gave it.
        </EmptyState>
      </Card>
    )
  }

  return (
    <Card className="overflow-hidden p-0">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">
            {option.record.plural ?? option.record.label}, newest first
          </caption>
          <thead>
            <tr className="border-b border-line bg-surface/60 text-[0.65rem] text-ink-3">
              <th scope="col" className="px-3 py-2 font-medium">
                ID
              </th>
              {option.columns.map(column => (
                <th key={column.name} scope="col" className="px-3 py-2 font-medium">
                  {column.label}
                </th>
              ))}
              <th scope="col" className="px-3 py-2 font-medium">
                Updated
              </th>
            </tr>
          </thead>
          <tbody>
            {records.map(record => {
              const active = record.id === selectedId
              return (
                <tr
                  key={record.id}
                  className={cn(
                    'border-b border-line/70 last:border-0',
                    active ? 'bg-hover' : 'hover:bg-hover/60'
                  )}
                >
                  <td className="px-3 py-2 align-top">
                    <button
                      type="button"
                      onClick={() => onSelect(record.id)}
                      className="font-mono text-xs text-accent underline underline-offset-2 hover:brightness-110"
                      aria-pressed={active}
                    >
                      {record.id}
                    </button>
                  </td>
                  {option.columns.map(column => (
                    <td key={column.name} className="max-w-[18rem] px-3 py-2 align-top text-ink-2">
                      <span className="line-clamp-3 break-words whitespace-pre-wrap">
                        {formatFieldValue(column, record.data?.[column.name])}
                      </span>
                    </td>
                  ))}
                  <td className="px-3 py-2 align-top text-xs text-ink-3">
                    {record.updated_at ? formatStamp(record.updated_at) : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function RecordDetail({
  option,
  record,
  loading,
  error,
  onClose
}: {
  option: RecordTypeOption
  record?: StoredRecord
  loading: boolean
  error: unknown
  onClose: () => void
}) {
  if (loading) return <Spinner label="Reading that record…" />
  if (error) {
    return (
      <Card className="border-danger/40">
        <p className="text-sm text-danger">Could not read that record.</p>
        <p className="text-xs text-ink-3">
          {error instanceof Error ? error.message : String(error)}
        </p>
      </Card>
    )
  }
  if (!record) return null

  return (
    <Card>
      <CardHeader
        title={recordTitle(option, record)}
        aside={
          <Button variant="ghost" size="sm" onClick={onClose} className="print-hide">
            Close
          </Button>
        }
      />
      <p className="font-mono text-[0.7rem] text-ink-disabled">
        {record.id}
        {record.updated_at ? ` · ${formatStamp(record.updated_at)}` : ''}
      </p>
      <dl className="grid gap-x-5 gap-y-2 sm:grid-cols-2">
        {option.record.fields.map(field => (
          <div key={field.name} className="min-w-0">
            <dt className="text-[0.65rem] text-ink-3">{field.label}</dt>
            <dd className="whitespace-pre-wrap break-words text-sm text-ink">
              {formatFieldValue(field, record.data?.[field.name])}
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  )
}

function formatStamp(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function download(name: string, text: string): void {
  if (typeof URL.createObjectURL !== 'function') return
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(url)
}
