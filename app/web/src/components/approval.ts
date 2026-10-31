/**
 * Reading an approval — the engine's rule name, said in words.
 *
 * The engine stops the run and hands us a `description` that is one of **117** pattern names
 * from `tools/approval_detection.py`: "script execution via -e/-c flag", "recursive delete of
 * home directory", "pipe remote content to shell". They are precise, and they are written for
 * whoever maintains the detector. Printing one as the body of a card asks an operator to approve
 * a rule name, which is how a safety feature becomes a thing people click through.
 *
 * So the pattern name is *translated*, in one place, into the sentence an operator needs. The
 * families below are not a lookup of 117 strings — they are nine things that can actually
 * happen to someone's business, matched by the phrases the engine's names share.
 *
 * Three rules hold this together, and they are safety rules rather than style ones:
 *
 *   1. **Translation may only raise the alarm, never lower it.** A pattern that matches
 *      nothing is shown as unexplained, not as harmless. The failure mode of a wrong match
 *      must be a card that says too much, never one that says too little.
 *   2. **The command is never paraphrased away.** Whatever the sentence says, the command
 *      itself is on the card, because it is the only ground truth about what will happen.
 *      This is the one place the "no code in the chat" rule is deliberately broken — a
 *      decision needs its evidence in a way that a web search does not.
 *   3. **Tone follows irreversibility, not scariness.** Inline code is opaque, so the engine
 *      asks; that is worth explaining, not worth a red banner. Deleting files, changing the
 *      machine, or sending data out is worth a red banner.
 */

import type { ApprovalChoice } from '@shared/wire'

export type ApprovalKind = 'command' | 'action'

/**
 * `normal` asks a question. `high` is for the patterns that can destroy something or send
 * something out, and it changes the weight of the buttons rather than only the colour.
 */
export type ApprovalTone = 'normal' | 'high'

export interface ApprovalReading {
  kind: ApprovalKind
  tone: ApprovalTone
  /** One plain sentence: what this would actually do. */
  what: string
  /** A guardian already refused and this is a one-operation override. */
  override: boolean
}

interface Family {
  tone: ApprovalTone
  /** Phrases the engine's own pattern names share. */
  match: RegExp
  what: string
}

/**
 * Most consequential first — the first match wins, so `git force push` is read as history
 * rather than as the word "push".
 *
 * The regexes are written against the engine's vocabulary, which is the one thing here that
 * can move. When it does, the fallback catches it: an unmatched pattern says so.
 */
const FAMILIES: readonly Family[] = [
  {
    tone: 'high',
    match: /connected app change/i,
    what: 'This would change something in one of your connected apps.'
  },
  {
    tone: 'high',
    match: /exfiltration|upload a secret|cloud metadata|credential file into a curl/i,
    what: 'This could send data off this computer.'
  },
  {
    tone: 'high',
    match: /SSH keys|Hermes secrets|sensitive credential|shell-rc|Hermes config\/env|project env\/config|in-place edit of/i,
    what: 'This would read or change your saved keys, passwords or settings.'
  },
  {
    tone: 'high',
    match: /recursive delete|delete in root path|destructive delete|Remove-Item|delete volume shadow copies|delete backups|registry (value )?delete|SQL (DROP|DELETE|TRUNCATE)|find -delete|find -exec|xargs with rm|git clean with force|package manager uninstall/i,
    what: 'This would delete files or data. Deleted things cannot be brought back.'
  },
  {
    tone: 'high',
    match: /mkfs|block device|format filesystem|Format-Volume|Clear-Disk|diskpart|format drive|wipe free space|disk copy|fork bomb|shutdown|reboot|init 0\/6|telinit|systemctl|Stop-Service|stop\/delete service|force stop service|boot configuration|Everyone access|ACLs|world\/other-writable|chown to root|system config|system service|sudo/i,
    what: 'This would change how the computer itself is set up.'
  },
  {
    tone: 'high',
    match: /pipe remote content|Invoke-Expression|execute remote|pipe decoded content|pipe xxd|pipe tr-|pipe openssl|PowerShell encoded|obfuscation|bidirectional Unicode|process substitution|command substitution/i,
    what: 'This would fetch something from the internet and run it.'
  },
  {
    tone: 'high',
    match: /force kill|kill processes|killall|kill process via|taskkill|Stop-Process|stop\/restart hermes|hermes update|kill hermes|launchd|container lifecycle|docker (restart|stop|kill|down)|daemon redirect|docker context|start gateway outside systemd/i,
    what: 'This would stop or restart something that is running.'
  },
  {
    tone: 'high',
    match: /git reset --hard|git force push|git branch force delete/i,
    what: 'This would rewrite saved history in your project.'
  },
  {
    tone: 'normal',
    match: /script execution via|heredoc|shell command via|arbitrary program execution|chmod \+x/i,
    what: 'This runs a small program written on the spot rather than a saved one, so it cannot be checked in advance — the engine asks every time.'
  },
  {
    tone: 'normal',
    match: /./,
    what: 'The engine flagged this one and it does not have plain words for it. What it would run is below.'
  }
]

/** The engine's own label, kept for the disclosure. Never the headline. */
export function flaggedAs(description: string): string {
  return description.trim() || 'unnamed pattern'
}

export function readApproval(input: {
  description: string
  command?: string
  smartDenied?: boolean
}): ApprovalReading {
  const family =
    FAMILIES.find(candidate => candidate.match.test(input.description)) ??
    FAMILIES[FAMILIES.length - 1]
  const override = input.smartDenied === true

  return {
    kind: input.command ? 'command' : 'action',
    // An override is always high: something already refused it, and a person is being asked
    // to overrule that. Nothing about the copy should make that feel routine.
    tone: override ? 'high' : family.tone,
    what: override
      ? 'Something already checked this and said no. You can still allow it once, for this one time only.'
      : family.what,
    override
  }
}

/**
 * What each button does, in the operator's words.
 *
 * The retired money gate wrote these, so they said "send" — which is nonsense for a command
 * and told an operator something untrue about a decision that is not outbound. `kind` keeps the
 * command case honest without pretending the card is only ever about commands.
 */
export function choiceLabel(choice: ApprovalChoice, kind: ApprovalKind): string {
  const command = kind === 'command'
  switch (choice) {
    case 'once':
      return command ? 'Run it once' : 'Do it once'
    case 'session':
      return command ? 'Allow this kind for now' : 'Allow this for now'
    case 'always':
      return 'Always allow — won’t ask again'
    default:
      return command ? 'No, don’t run it' : 'No, don’t do it'
  }
}

/** The consequence of the sticky choice, stated plainly. It outlives the session. */
export const ALWAYS_WARNING =
  'This stops the asking for this kind of command from now on — including after a restart, ' +
  'and including when you are not watching. Only do this for something you would be happy ' +
  'to see run unattended.'

/** Said before the answer is given, so a parked run is never a mystery. */
export const NO_ANSWER =
  'If you don’t answer, it won’t run — the assistant carries on without it.'

/** What a resolved approval says. The engine's own words for the three grants. */
export function resolvedLabel(choice: ApprovalChoice): string {
  switch (choice) {
    case 'once':
      return 'Allowed once'
    case 'session':
      return 'Allowed for this session'
    case 'always':
      return 'Allowed permanently'
    default:
      return 'Denied'
  }
}
