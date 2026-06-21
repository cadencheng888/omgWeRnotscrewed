// Parse a server "action" string into a structured card.
// Server encodes: emoji prefix + summary + " [app/action]" + " ⟦key⟧"

const APP_ACCENT = {
  amazon: '#f59e0b', messages: '#34d399', email: '#22d3ee', reminders: '#818cf8',
  spotify: '#22c55e', maps: '#fb7185', phone: '#34d399', notes: '#fbbf24',
  web: '#22d3ee', food: '#fb923c', smart_home: '#a78bfa',
}
const CAL = new Set(['create_calendar_event', 'reschedule_event', 'cancel_event'])
const REMOVAL = /remov|delet|cancel|undo|unsend|turn_?off|stop|clear/i
const QUOTE = /['‘’“”]([^'‘’“”]+)['‘’“”]/

export function classifyAction(raw) {
  let key = null
  let text = raw
  const km = text.match(/⟦([^⟧]+)⟧/) // ⟦key⟧
  if (km) { key = km[1]; text = text.replace(/\s*⟦[^⟧]+⟧/, '').trim() }
  const q = text.match(QUOTE)
  const title = q ? q[1] : null

  const finish = (o) => {
    o.key = key
    if (o.cancelled) o.source = CAL.has(o.tool) ? 'cancelled' : 'removed'
    return o
  }

  if (text.startsWith('📅')) {
    const body = text.replace(/^📅\s*/, '')
    const eTitle = (body.match(QUOTE) || [])[1] || 'Event'
    const dash = body.indexOf('—')
    const detail = dash !== -1 ? body.slice(dash + 1).trim() : body.replace(QUOTE, '').trim()
    return finish({ tool: 'create_calendar_event', accent: '#34d399', title: eTitle, detail, source: 'Calendar' })
  }
  if (text.startsWith('🔁')) {
    const body = text.replace(/^🔁\s*/, '')
    const eTitle = (body.match(QUOTE) || [])[1] || 'Rescheduled'
    const dash = body.indexOf('—')
    const detail = dash !== -1 ? body.slice(dash + 1).trim() : body.replace(QUOTE, '').trim()
    return finish({ tool: 'reschedule_event', accent: '#818cf8', title: eTitle, detail, source: 'Calendar' })
  }
  if (text.startsWith('🗑️') || text.startsWith('🗑')) {
    const body = text.replace(/^🗑️?\s*/, '')
    const eTitle = (body.match(QUOTE) || [])[1] || 'Cancelled'
    const dash = body.indexOf('—')
    const detail = dash !== -1 ? body.slice(dash + 1).trim() : body.replace(QUOTE, '').trim()
    return finish({ tool: 'cancel_event', accent: '#fbbf24', title: eTitle, detail, cancelled: true, source: 'Calendar' })
  }
  if (text.startsWith('🧩')) {
    const m = text.match(/\[([^/\]]+)\/([^\]]+)\]/)
    const app = m ? m[1] : 'action'
    const act = m ? m[2] : ''
    const removal = REMOVAL.test(act)
    const body = text.replace(/^🧩\s*/, '').split('·')[0].trim()
    const source = app.charAt(0).toUpperCase() + app.slice(1).replace(/_/g, ' ')
    return finish({ tool: app, accent: removal ? '#fbbf24' : (APP_ACCENT[app] || '#22d3ee'), title: body, detail: m ? `${m[1]} · ${m[2]}` : text, cancelled: removal, source })
  }
  if (text.startsWith('💬')) return finish({ tool: 'no_action', muted: true })
  if (text.startsWith('⚠️')) return finish({ tool: 'error', muted: true, detail: text.replace(/^⚠️\s*/, '') })
  return finish({ tool: 'create_calendar_event', accent: '#34d399', title: title || 'Event', detail: text, source: 'Calendar' })
}
