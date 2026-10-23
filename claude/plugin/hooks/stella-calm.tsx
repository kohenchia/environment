/**
 * Stella's /calm: a Claude Code function-hooks module that changes only what her session draws.
 *
 * With calm on (the default in her store; `/calm` toggles it, remembered in calm.flag there) her session hides tool
 * rows, turn timings ("Sautéed for 29s"), the short notes she writes between tool calls, the row a `stella-check` wake
 * leaves ("stella-check wake") and a bare "Quiet." reply, so a wake that needed nothing leaves nothing, and a turn
 * where she did work reads as what she said. Her other replies, Kohen's messages, failed tool calls, long text and
 * dialogs stay; nothing hidden leaves her context or the transcript. Rows Claude Code draws itself ("Running
 * scheduled task", recaps) cannot be reached from here; stella-check and her settings remove those at the source.
 *
 * Active only when CLAUDE_CODE_ENABLE_FUNCTION_HOOKS is "1" AND the session's project root is Stella's store (or a
 * folder that holds a calm.flag reading "on", which is how it is tested), so every other session is untouched.
 * Render only: it runs no process and sends no message. It writes calm.flag (on a toggle), calm.status (one line at
 * each session start, so a session that does not draw it can be diagnosed) and, only while a calm.debug file exists
 * beside them, calm.trace (what it decided).
 */
import type { Register } from 'claude-code'

const NOTE_MAX = 240 // a working note is one line shorter than this
const WAKE_SUMMARY = 'stella-check wake' // the rewakeSummary stella writes into her hooks
const SILENT = /^quiet[.!]?$/i // her reply to a turn that needed nothing

type Where = { dir: string; stella: boolean } | null

// Per-load memory only; a hot reload starts it again.
let gate: Promise<Where> | null = null
let calm: boolean | null = null
const notes = new Set<string>() // text of steps that ended in a tool call: one short line
const finals = new Set<string>() // text of steps that ended the turn
const counted = new Map<string, number>()
let tail: Promise<void> = Promise.resolve() // trace lines are written one after another

async function realPath($: any, p: string): Promise<string> {
  try { return (await $.fs.stat(p, { resolve: true })).realPath ?? p } catch { return p }
}

async function append($: any, path: string, line: string): Promise<void> {
  let old = ''
  try { old = await $.fs.read(path) } catch { /* first line */ }
  await $.fs.write(path, (old + line + '\n').split('\n').slice(-300).join('\n'))
}

async function resolveWhere($: any): Promise<Where> {
  const flag = (await $.env.get('CLAUDE_CODE_ENABLE_FUNCTION_HOOKS')) ?? 'unset'
  const home = ((await $.env.get('HOME')) ?? '').replace(/\/+$/, '')
  const root = await realPath($, (await $.session.root()).replace(/\/+$/, ''))
  const stella = home ? await realPath($, `${home}/.local/share/stella`) : ''
  const isStella = !!stella && root === stella
  let why = flag !== '1' ? `function hooks flag is ${flag}` : !home ? 'no HOME' : ''
  let found: Where = null
  if (!why) {
    if (isStella) found = { dir: root, stella: true }
    else if (await $.fs.exists(`${root}/calm.flag`)) found = { dir: root, stella: false }
    else why = 'not Stella\'s store and no calm.flag'
  }
  if (isStella || (await $.fs.exists(`${root}/calm.flag`))) { // one line per session start, whatever the outcome: the evidence that this module loaded and ran
    try { await $.fs.write(`${root}/calm.status`, `${new Date().toISOString()} loaded; active=${!!found}${why ? `; ${why}` : ''}; root=${root}\n`) } catch { /* diagnostics only */ }
  }
  return found
}

// Never throws: this module loads in every session.
function locate($: any): Promise<Where> {
  gate ??= resolveWhere($).catch(() => null)
  return gate
}

async function isCalm($: any, w: NonNullable<Where>): Promise<boolean> {
  if (calm === null) {
    let flag = ''
    try { flag = await $.fs.read(`${w.dir}/calm.flag`) } catch { /* no flag file */ }
    calm = w.stella ? flag.trim() !== 'off' : flag.trim() === 'on' // Stella's store: on unless turned off
  }
  return calm
}

async function trace($: any, w: NonNullable<Where>, what: string, hid: boolean): Promise<void> {
  try {
    const key = `${what}:${hid}`
    const n = (counted.get(key) ?? 0) + 1
    counted.set(key, n)
    if (n > 3 || !(await $.fs.exists(`${w.dir}/calm.debug`))) return
    const line = `${new Date().toISOString()} ${what} hidden=${hid}`
    tail = tail.then(() => append($, `${w.dir}/calm.trace`, line)).catch(() => {})
    await tail
  } catch { /* diagnostics only */ }
}

// Whether a row of this kind is drawn as nothing: calm on, not an expanded view, not a failure.
async function hides($: any, e: any, what: string, extra = true): Promise<boolean> {
  const w = await locate($)
  const props = e.props as any
  const hid = !!w && extra && !props.isExpanded && !props.isErrored && (await isCalm($, w))
  if (w) await trace($, w, what, hid)
  return hid
}

// A row drawn as nothing. Helpers that take `$` are declared at the top of the file: the engine's check refuses a
// module that hands `$` to a function declared anywhere else (inside `register`, say), and then the module never loads.
function none($: any, e: any) {
  const { Box } = $.ui.resolve(e)
  return <Box display="none" />
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    gate = null; calm = null
    const w = await locate($)
    if (w) {
      await isCalm($, w)
      await $.command.register({ name: 'calm', description: 'Hide tool rows, timings, wake rows and "Quiet."; toggles' })
    }
    return next(e)
  })

  on('command.run', { command: 'calm' }, async ($, e, next) => {
    const w = await locate($)
    if (!w) return next(e)
    try {
      calm = !(await isCalm($, w))
      await $.fs.write(`${w.dir}/calm.flag`, calm ? 'on\n' : 'off\n')
      $.ui.invalidate('ui.render')
      $.ui.toast(calm ? 'Calm on' : 'Calm off: everything shows')
    } catch {
      $.ui.toast('Calm unchanged: could not save the setting')
    }
    return {}
  }).catch(($, e, next) => (next.called ? next(e) : {}))

  // Learn which text is a working note: a step that ended in a tool call and wrote one short line.
  on('turn.step', async function* ($, e, next) {
    const result = yield* next(e)
    if (e.agentId || !(await locate($))) return result
    const text = result.answer.trim()
    if (text) {
      if (result.toolUses.length === 0) finals.add(text)
      else if (!text.includes('\n') && text.length < NOTE_MAX) notes.add(text)
    }
    if (notes.size + finals.size > 2000) { notes.clear(); finals.clear() }
    return result
  })

  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => ((await hides($, e, 'ToolUse')) ? none($, e) : next(e)))
  on('ui.render', { component: 'ToolResult' }, async ($, e, next) => ((await hides($, e, 'ToolResult')) ? none($, e) : next(e)))
  on('ui.render', { component: 'ToolGroup' }, async ($, e, next) => ((await hides($, e, 'ToolGroup')) ? none($, e) : next(e)))
  on('ui.render', { component: 'TurnDuration' }, async ($, e, next) => ((await hides($, e, 'TurnDuration')) ? none($, e) : next(e)))

  // The row a stella-check wake leaves behind (the hook's rewakeSummary), and only that one.
  on('ui.render', { component: 'UserMessage' }, async ($, e, next) => {
    const p = e.props
    const wake = p.origin.kind === 'task-notification' && p.text.trim() === WAKE_SUMMARY
    return (await hides($, e, 'UserMessage', wake)) ? none($, e) : next(e)
  })

  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    const text = e.props.text.trim()
    const note = !finals.has(text) && notes.has(text)
    return (await hides($, e, 'AssistantMessage', note || SILENT.test(text))) ? none($, e) : next(e)
  })
}
