/**
 * Stella's calm mode and crew band: a Claude Code function-hooks module (render only).
 *
 * Calm (/calm toggles, on by default, remembered in ~/.local/share/stella/calm.flag) hides tool rows and
 * short mid-turn working notes so Stella's session reads as a conversation; the final message of each turn
 * (with its status block), user messages, long text and dialogs stay. One dim stub per turn says how many
 * steps are hidden. The crew band above the prompt lists the crew that has not landed, from files only.
 *
 * Inert unless CLAUDE_CODE_ENABLE_FUNCTION_HOOKS is "1" AND the session's directory is Stella's home, so
 * every other session is untouched. It runs no process, no network and sends no message: it reads
 * crew/<name>/record.json and ~/.claude/jobs/<id>/state.json and writes calm.flag, nothing else.
 */
import type { Register } from 'claude-code'

type Json = Record<string, unknown>
type Where = { stella: string; home: string } | null
const NOTE_MAX = 240 // a working note is one line shorter than this
const BAND_MAX = 6 // lines in the crew band
const TICK_MS = 5000

// Per-load memory only; rebuilt by session.start and by the turns themselves after a hot reload.
let gate: Promise<Where> | null = null
let calm: boolean | null = null
let band: string[] | null = null
let turnId = ''
const notes = new Set<string>() // mid-turn text (step ended in a tool call), short, one line
const finals = new Set<string>() // text of steps that ended the turn
const turnOf = new Map<string, string>() // tool_use_id -> turn
const first = new Map<string, string>() // turn -> its first tool_use_id
const count = new Map<string, number>() // turn -> tool calls so far

async function realPath($: any, p: string): Promise<string> {
  try { return (await $.fs.stat(p, { resolve: true })).realPath ?? p } catch { return p }
}

async function resolveWhere($: any): Promise<Where> {
  if ((await $.env.get('CLAUDE_CODE_ENABLE_FUNCTION_HOOKS')) !== '1') return null
  const home = ((await $.env.get('HOME')) ?? '').replace(/\/+$/, '')
  if (!home) return null
  const stella = `${home}/.local/share/stella`
  const cwd = (await $.session.cwd()).replace(/\/+$/, '')
  return (await realPath($, cwd)) === (await realPath($, stella)) ? { stella, home } : null
}

// Stella's home when enabled and in her directory, else null (and every handler passes through).
// Never throws: this module loads in every session, and a gating hook that threw would block tool calls.
async function where($: any): Promise<Where> {
  gate ??= resolveWhere($).catch(() => null)
  return gate
}

async function readJson($: any, path: string): Promise<Json | null> {
  try { return JSON.parse(await $.fs.read(path)) } catch { return null }
}

async function isCalm($: any, stella: string): Promise<boolean> {
  if (calm === null) {
    let flag = ''
    try { flag = await $.fs.read(`${stella}/calm.flag`) } catch { /* no flag file: default on */ }
    calm = flag.trim() !== 'off'
  }
  return calm
}

// The band's lines, from the files alone: teams collapse into one line, the rest are one per crewmate.
async function crewLines($: any, stella: string, home: string, columns: number): Promise<string[]> {
  let dirs: { name: string; kind: string }[] = []
  try { dirs = await $.fs.list(`${stella}/crew`) } catch { return [] }
  const teams = new Map<string, string[]>()
  const singles: string[] = []
  for (const d of dirs.filter(d => d.kind === 'dir').sort((a, b) => a.name.localeCompare(b.name))) {
    const rec = await readJson($, `${stella}/crew/${d.name}/record.json`)
    if (!rec || rec.state === 'landed') continue
    const job = rec.id ? await readJson($, `${home}/.claude/jobs/${rec.id}/state.json`) : null
    const state = String(job?.state ?? rec.state ?? 'queued')
    const needs = typeof job?.needs === 'string' ? job.needs : ''
    const name = String(rec.name ?? d.name)
    if (typeof rec.team === 'string' && rec.team) {
      teams.set(rec.team, [...(teams.get(rec.team) ?? []), needs && state !== 'done' ? 'blocked' : state])
    } else {
      const head = `${name} · ${state}`
      singles.push(needs ? `${head} · ${needs}`.slice(0, columns - 1) : head)
    }
  }
  const lines = [...teams].map(([team, s]) => {
    const n = (k: string) => s.filter(x => x === k).length
    const queued = s.length - n('done') - n('working') - n('blocked')
    return `${team} · ${n('done')}/${s.length} done · ${n('working')} working · ${queued} queued · ${n('blocked')} needs you`
  })
  const all = [...lines, ...singles]
  return all.length > BAND_MAX ? [...all.slice(0, BAND_MAX - 1), `… ${all.length - BAND_MAX + 1} more`] : all
}

// Hidden row, or the turn's one stub in place of the row that is the first hidden one of its turn.
async function toolRow($: any, e: any, next: any, ids: (string | undefined)[]) {
  const w = await where($)
  if (!w || !(await isCalm($, w.stella))) return next(e)
  const { Box, Text } = $.ui.resolve(e)
  for (const id of ids) {
    const t = id ? turnOf.get(id) : undefined
    if (t !== undefined && first.get(t) === id) {
      const n = count.get(t) ?? 1
      return <Box><Text dimColor>· {n} {n === 1 ? 'step' : 'steps'} hidden (/calm off)</Text></Box>
    }
  }
  return <Box display="none" />
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    gate = null; calm = null; band = null
    const w = await where($)
    if (w) {
      await isCalm($, w.stella)
      await $.command.register({ name: 'calm', description: 'Hide tool rows and working notes (calm mode); toggles' })
      $.clock.every(TICK_MS, async () => {
        const lines = await crewLines($, w.stella, w.home, 80)
        if (JSON.stringify(lines) !== JSON.stringify(band)) { band = lines; $.ui.invalidate('ui.render') }
      })
    }
    return next(e)
  })

  on('command.run', { command: 'calm' }, async ($, e, next) => {
    const w = await where($)
    if (!w) return next(e)
    try {
      calm = !(await isCalm($, w.stella))
      await $.fs.write(`${w.stella}/calm.flag`, calm ? 'on\n' : 'off\n')
      $.ui.invalidate('ui.render')
      $.ui.toast(calm ? 'Calm on' : 'Calm off')
    } catch {
      $.ui.toast('Calm unchanged: could not save the setting')
    }
    return {}
  }).catch(($, e, next) => (next.called ? next(e) : {}))

  // Learn which text is a working note: a step that ended in a tool call and wrote one short line.
  on('turn.step', async function* ($, e, next) {
    const w = await where($)
    const result = yield* next(e)
    if (!w || e.agentId) return result
    turnId = e.turnId
    const text = result.answer.trim()
    if (text) {
      if (result.toolUses.length === 0) finals.add(text)
      else if (!text.includes('\n') && text.length < NOTE_MAX) notes.add(text)
    }
    if (notes.size + finals.size > 2000) { notes.clear(); finals.clear() }
    return result
  })

  on('tool.call', async ($, e, next) => {
    try {
      if (!e.agentId && (await where($))) {
        turnOf.set(e.tool_use_id, turnId)
        if (!first.has(turnId)) first.set(turnId, e.tool_use_id)
        count.set(turnId, (count.get(turnId) ?? 0) + 1)
      }
    } catch { /* bookkeeping only: never stand between a session and its tools */ }
    return next(e)
  }).catch(($, e, next) => next(e))

  // The counts of a turn are final once it completes: redraw so the stub shows the total.
  on('turn.complete', async ($, e, next) => {
    if (await where($)) $.ui.invalidate('ui.render')
    return next(e)
  })

  on('ui.render', { component: 'ToolUse' }, ($, e, next) => toolRow($, e, next, [e.props.tool_use_id]))
  on('ui.render', { component: 'ToolResult' }, ($, e, next) => toolRow($, e, next, [e.props.tool_use_id]))
  on('ui.render', { component: 'ToolGroup' }, ($, e, next) => toolRow($, e, next, e.props.calls.map(c => c.tool_use_id)))

  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    const w = await where($)
    const text = e.props.text.trim()
    if (!w || !(await isCalm($, w.stella)) || finals.has(text) || !notes.has(text)) return next(e)
    const { Box } = $.ui.resolve(e)
    return <Box display="none" />
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const w = await where($)
    if (!w || e.props.hasSurvey) return next(e)
    const lines = band ?? (await crewLines($, w.stella, w.home, e.props.bodyColumns))
    if (lines.length === 0) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        {lines.map(l => <Text key={l} dimColor>{l.slice(0, e.props.bodyColumns)}</Text>)}
      </Box>
    )
  })
}
