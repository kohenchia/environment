/**
 * Stella's /calm: a Claude Code function-hooks module that changes only what her session draws.
 *
 * With calm on (the default; `/calm` toggles it, remembered in ~/.local/share/stella/calm.flag) her session hides
 * tool rows, turn timings ("Cogitated for 57s") and the short notes she writes between tool calls, so a turn reads
 * as what she said. Her replies, Kohen's messages, failed tool calls, long text and dialogs stay; `/calm` again shows everything, and
 * nothing hidden leaves her context or the transcript. Rows Claude Code draws itself ("Running scheduled task",
 * recaps) cannot be reached from here; stella-check and her settings remove those at the source.
 *
 * Inert unless CLAUDE_CODE_ENABLE_FUNCTION_HOOKS is "1" AND the session's project root is Stella's store, so every
 * other session is untouched. Render only: it runs no process, no network and sends no message; it writes calm.flag.
 */
import type { Register } from 'claude-code'

const NOTE_MAX = 240 // a working note is one line shorter than this

// Per-load memory only; a hot reload starts it again.
let gate: Promise<string | null> | null = null
let calm: boolean | null = null
const notes = new Set<string>() // text of steps that ended in a tool call: one short line
const finals = new Set<string>() // text of steps that ended the turn

async function realPath($: any, p: string): Promise<string> {
  try { return (await $.fs.stat(p, { resolve: true })).realPath ?? p } catch { return p }
}

// Stella's store when enabled and this is her session, else null (and every hook passes through). The project root,
// not the shell's directory: she cd's into her store's subfolders, and the root does not move.
async function resolveStore($: any): Promise<string | null> {
  if ((await $.env.get('CLAUDE_CODE_ENABLE_FUNCTION_HOOKS')) !== '1') return null
  const home = ((await $.env.get('HOME')) ?? '').replace(/\/+$/, '')
  if (!home) return null
  const store = `${home}/.local/share/stella`
  return (await realPath($, await $.session.root())) === (await realPath($, store)) ? store : null
}

// Never throws: this module loads in every session.
function stella($: any): Promise<string | null> {
  gate ??= resolveStore($).catch(() => null)
  return gate
}

async function isCalm($: any, store: string): Promise<boolean> {
  if (calm === null) {
    let flag = ''
    try { flag = await $.fs.read(`${store}/calm.flag`) } catch { /* no flag file: calm is on */ }
    calm = flag.trim() !== 'off'
  }
  return calm
}

async function hidden($: any, e: any): Promise<boolean> {
  const store = await stella($)
  // A failed tool call always shows: calm hides routine work, never an error.
  return !!store && !(e.props as any).isExpanded && !(e.props as any).isErrored && (await isCalm($, store))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    gate = null; calm = null
    const store = await stella($)
    if (store) {
      await isCalm($, store)
      await $.command.register({ name: 'calm', description: 'Hide tool rows, timings and working notes; toggles' })
    }
    return next(e)
  })

  on('command.run', { command: 'calm' }, async ($, e, next) => {
    const store = await stella($)
    if (!store) return next(e)
    try {
      calm = !(await isCalm($, store))
      await $.fs.write(`${store}/calm.flag`, calm ? 'on\n' : 'off\n')
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
    if (e.agentId || !(await stella($))) return result
    const text = result.answer.trim()
    if (text) {
      if (result.toolUses.length === 0) finals.add(text)
      else if (!text.includes('\n') && text.length < NOTE_MAX) notes.add(text)
    }
    if (notes.size + finals.size > 2000) { notes.clear(); finals.clear() }
    return result
  })

  const none = ($: any, e: any) => { const { Box } = $.ui.resolve(e); return <Box display="none" /> }
  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => ((await hidden($, e)) ? none($, e) : next(e)))
  on('ui.render', { component: 'ToolResult' }, async ($, e, next) => ((await hidden($, e)) ? none($, e) : next(e)))
  on('ui.render', { component: 'ToolGroup' }, async ($, e, next) => ((await hidden($, e)) ? none($, e) : next(e)))
  on('ui.render', { component: 'TurnDuration' }, async ($, e, next) => ((await hidden($, e)) ? none($, e) : next(e)))

  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    const text = e.props.text.trim()
    if (finals.has(text) || !notes.has(text) || !(await hidden($, e))) return next(e)
    return none($, e)
  })
}
