'use strict'

/*
 * Loopback coach for Claude Desktop: the relay. Started by index.js.
 *
 * Claude Desktop starts this as a local MCP server and talks to it over
 * stdin/stdout. It relays every message to the coach endpoint of a Loopback
 * server (streamable HTTP at /mcp) with the athlete's token, and writes the
 * answers back. The server address and the token come from the extension's
 * settings, as LOOPBACK_SERVER_URL and LOOPBACK_TOKEN.
 *
 * No dependencies, on purpose: the bundle is zipped by the Loopback server
 * from these files as they are, so there is no npm install, no node_modules
 * and no build step anywhere. It needs Node 18 or newer for fetch, which the
 * Node that ships inside Claude Desktop is.
 *
 * Only what the coach endpoint uses is implemented: requests and their
 * answers. The server never starts a conversation on its own, so no listening
 * stream is opened for one.
 */

const { StringDecoder } = require('node:string_decoder')

const NAME = 'loopback-coach'
const VERSION = readVersion()
const SETTINGS_HINT = 'Change it in Claude Desktop under Settings → Extensions → Loopback Coach.'

function readVersion() {
  try {
    return require('../manifest.json').version
  } catch {
    return '0.0.0'
  }
}

/**
 * The coach endpoint for whatever address was entered. People paste the
 * address their browser shows, so a dashboard page (https://host/settings) or
 * the bare origin both mean https://host/mcp. A path that already ends in
 * /mcp is kept, for a server behind a path prefix.
 */
function resolveEndpoint(raw) {
  const text = String(raw || '').trim()
  if (!text || text.startsWith('${')) {
    throw new Error(`No server address is set. ${SETTINGS_HINT}`)
  }
  let url
  try {
    url = new URL(text)
  } catch {
    url = null
  }
  if (!url || (url.protocol !== 'http:' && url.protocol !== 'https:') || !url.hostname) {
    throw new Error(
      `"${text}" is not a full address. Use the one you open the Loopback dashboard at, ` +
        `starting with http:// or https://. ${SETTINGS_HINT}`,
    )
  }
  const path = url.pathname.replace(/\/+$/, '')
  url.pathname = path.endsWith('/mcp') ? path : '/mcp'
  url.search = ''
  url.hash = ''
  url.username = ''
  url.password = ''
  return url.href
}

/** The token as entered, without a pasted "Bearer " in front. */
function resolveToken(raw) {
  const text = String(raw || '')
    .trim()
    .replace(/^bearer(\s+|$)/i, '')
  if (!text || text.startsWith('${')) {
    throw new Error(
      'No token is set. Create one in the Loopback dashboard under Settings → AI coach → Connect, ' +
        `and paste it in this extension's settings. ${SETTINGS_HINT}`,
    )
  }
  return text
}

/** A failure whose message already says what went wrong, in the user's terms. */
class Reported extends Error {}

/** Yields the data of each event in a text/event-stream body. */
async function* sseData(body) {
  const decoder = new TextDecoder()
  let buffer = ''
  let data = []
  for await (const chunk of body) {
    buffer += decoder.decode(chunk, { stream: true })
    let end
    while ((end = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, end).replace(/\r$/, '')
      buffer = buffer.slice(end + 1)
      if (line === '') {
        if (data.length) yield data.join('\n')
        data = []
      } else if (line.startsWith('data:')) {
        data.push(line.slice(5).replace(/^ /, ''))
      }
      // Comments (keep-alive pings) and the id/event/retry fields carry
      // nothing this relay uses.
    }
  }
  // A server that closes right after its last event, without the blank line
  // that ends it, or without even the line ending.
  const last = buffer.replace(/\r$/, '')
  if (last.startsWith('data:')) data.push(last.slice(5).replace(/^ /, ''))
  if (data.length) yield data.join('\n')
}

function createRelay({ env, write, log }) {
  let endpoint = null
  let token = null
  let configError = null
  try {
    endpoint = resolveEndpoint(env.LOOPBACK_SERVER_URL)
    token = resolveToken(env.LOOPBACK_TOKEN)
  } catch (err) {
    configError = err.message
  }

  // What the client sent to open the session, kept so the session can be
  // opened again without the client noticing (see renewSession).
  let initializeParams = null
  let sessionId = null
  let protocolVersion = null
  let renewing = null
  let renewals = 0

  function post(message, session) {
    const headers = {
      'Content-Type': 'application/json',
      Accept: 'application/json, text/event-stream',
      Authorization: `Bearer ${token}`,
      'User-Agent': `${NAME}/${VERSION}`,
    }
    if (session) headers['Mcp-Session-Id'] = session
    if (session && protocolVersion) headers['MCP-Protocol-Version'] = protocolVersion
    return fetch(endpoint, { method: 'POST', headers, body: JSON.stringify(message) })
  }

  /** Parses a response body into JSON-RPC messages, one call per message. */
  async function readMessages(res, each) {
    const type = (res.headers.get('content-type') || '').toLowerCase()
    if (res.status === 202 || res.status === 204) {
      // A notification was accepted. The server labels this empty answer as
      // JSON, so it must not reach the parser below.
      await res.arrayBuffer().catch(() => {})
    } else if (type.startsWith('text/event-stream') && res.body) {
      for await (const data of sseData(res.body)) {
        if (!data.trim()) continue
        let parsed
        try {
          parsed = JSON.parse(data)
        } catch {
          log('skipped an event that is not JSON')
          continue
        }
        for (const message of [].concat(parsed)) each(message)
      }
    } else if (type.startsWith('application/json')) {
      const text = await res.text()
      let parsed
      try {
        parsed = JSON.parse(text)
      } catch {
        throw new Reported('The Loopback server sent an answer that could not be read.')
      }
      for (const message of [].concat(parsed)) each(message)
    } else {
      await res.arrayBuffer().catch(() => {})
    }
  }

  function describeFailure(err) {
    const cause = (err && err.cause && (err.cause.code || err.cause.message)) || (err && err.message) || 'unknown error'
    return (
      `Could not reach the Loopback server at ${new URL(endpoint).origin} (${cause}). ` +
      'Check that this computer can open that address in a browser: it may be off the network ' +
      'or tailnet the server is on, or the server may be down.'
    )
  }

  async function describeStatus(res) {
    const body = (await res.text().catch(() => '')).slice(0, 300)
    if (res.status === 401 || res.status === 403) {
      return (
        `The Loopback server refused the token (HTTP ${res.status}). Create a new one in the dashboard under ` +
        `Settings → AI coach → Connect and paste it in this extension's settings. ${SETTINGS_HINT}`
      )
    }
    if (res.status === 404 || res.status === 405) {
      return (
        `There is no coach endpoint at ${endpoint} (HTTP ${res.status}). Check the server address, ` +
        `and that the server has not set MCP_ENABLED=false. ${SETTINGS_HINT}`
      )
    }
    return `The Loopback server answered HTTP ${res.status}${body ? `: ${body}` : ''}`
  }

  /**
   * The server forgets its sessions when it restarts (an upgrade, a reboot),
   * and answers a request for a forgotten one with 404. Claude Desktop cannot
   * be asked to start over, so the relay opens a new session itself with the
   * client's own initialize parameters and repeats the request. Requests that
   * fail together share one renewal.
   */
  function renewSession(stale) {
    if (sessionId !== stale) return Promise.resolve()
    if (!renewing) {
      renewing = (async () => {
        const id = `${NAME}-renew-${++renewals}`
        const res = await post({ jsonrpc: '2.0', id, method: 'initialize', params: initializeParams }, null)
        if (!res.ok) throw new Reported(await describeStatus(res))
        const session = res.headers.get('mcp-session-id')
        await readMessages(res, (message) => {
          if (message.id === id && message.result && message.result.protocolVersion) {
            protocolVersion = message.result.protocolVersion
          }
        })
        sessionId = session
        const ack = await post({ jsonrpc: '2.0', method: 'notifications/initialized' }, session)
        await ack.arrayBuffer().catch(() => {})
        log('the server had dropped the session; opened a new one')
      })().finally(() => {
        renewing = null
      })
    }
    return renewing
  }

  /** Answers a request with an error, or just logs it for a notification. */
  function fail(message, text) {
    log(text)
    if (message && message.id !== undefined && message.method !== undefined) {
      write({ jsonrpc: '2.0', id: message.id, error: { code: -32000, message: text } })
    }
  }

  async function forward(message) {
    if (configError) return fail(message, configError)

    const opening = message.method === 'initialize'
    if (opening) {
      initializeParams = message.params
      sessionId = null
      protocolVersion = null
    }
    const expectsAnswer = message.id !== undefined && message.method !== undefined
    let answered = !expectsAnswer

    try {
      const used = sessionId
      let res = await post(message, used)
      if (res.status === 404 && used && initializeParams && !opening) {
        await res.arrayBuffer().catch(() => {})
        await renewSession(used)
        res = await post(message, sessionId)
      }
      if (!res.ok) throw new Reported(await describeStatus(res))

      // Before the answer is written: the client replies to it at once, and
      // that reply has to carry the session.
      if (opening) sessionId = res.headers.get('mcp-session-id')

      await readMessages(res, (incoming) => {
        if (expectsAnswer && incoming.id === message.id && incoming.method === undefined) {
          answered = true
          if (opening && incoming.result && incoming.result.protocolVersion) {
            protocolVersion = incoming.result.protocolVersion
          }
        }
        write(incoming)
      })
      if (!answered) throw new Reported('The Loopback server closed the connection before it answered.')
    } catch (err) {
      const text = err instanceof Reported ? err.message : describeFailure(err)
      // A request that was already answered must not get a second answer.
      if (answered) log(text)
      else fail(message, text)
    }
  }

  /** Tells the server the session is over. Best effort, and brief. */
  async function close() {
    if (!sessionId || configError) return
    try {
      const res = await fetch(endpoint, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}`, 'Mcp-Session-Id': sessionId },
        signal: AbortSignal.timeout(2000),
      })
      await res.arrayBuffer().catch(() => {})
    } catch {
      /* the server forgets the session on its own */
    }
  }

  /**
   * Takes the client's messages in the order they were written. Requests run
   * side by side, but each waits until the notifications before it have been
   * delivered: every message is its own HTTP request, so without this a
   * request can overtake the "initialized" notification written just ahead
   * of it, which the protocol lets a server refuse. (The coach endpoint
   * answers anyway as of fastmcp 3.1.1; this keeps the relay correct if that
   * changes.) Notifications do not wait for requests, so a cancellation
   * reaches the server while the call it cancels is still running.
   */
  let delivered = Promise.resolve()
  function handle(message) {
    const isRequest = message.id !== undefined && message.method !== undefined
    const done = delivered.then(() => forward(message))
    if (!isRequest) delivered = done.catch(() => {})
    return done
  }

  return { handle, close }
}

function main() {
  const log = (text) => process.stderr.write(`[${NAME}] ${text}\n`)
  const write = (message) => process.stdout.write(`${JSON.stringify(message)}\n`)
  const relay = createRelay({ env: process.env, write, log })

  const pending = new Set()
  const track = (promise) => {
    // Never left to reject on its own: an unhandled rejection ends the
    // process, in plain Node and under Claude Desktop's host alike.
    const settled = promise.catch((err) => log(`unexpected: ${err && err.message}`))
    pending.add(settled)
    settled.finally(() => pending.delete(settled))
  }

  let exiting = false
  async function exit(waitForAnswers) {
    if (exiting) return
    exiting = true
    if (waitForAnswers) {
      // Requests already sent still get their answer written before leaving.
      const timeout = new Promise((resolve) => setTimeout(resolve, 10_000).unref())
      await Promise.race([Promise.allSettled([...pending]), timeout])
    }
    await relay.close()
    process.exit(0)
  }

  function onLine(line) {
    if (!line.trim()) return
    let parsed
    try {
      parsed = JSON.parse(line)
    } catch {
      write({ jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Parse error' } })
      return
    }
    for (const message of [].concat(parsed)) track(relay.handle(message))
  }

  // One JSON-RPC message per line, read from plain 'data' events and nothing
  // fancier. With its built-in Node, Claude Desktop gives the extension no
  // real stdin: its host swaps a handful of process.stdin's methods (on,
  // once, resume, ...) for those of a stream it feeds, and 'data' through
  // `on` is the one way of reading it is built for.
  const decoder = new StringDecoder('utf8')
  let buffered = ''
  process.stdin.on('data', (chunk) => {
    buffered += typeof chunk === 'string' ? chunk : decoder.write(chunk)
    let end
    while ((end = buffered.indexOf('\n')) !== -1) {
      const line = buffered.slice(0, end)
      buffered = buffered.slice(end + 1)
      onLine(line)
    }
  })
  // A client that talks over a real pipe closes it when it is done. Claude
  // Desktop's host never ends its stream; it stops the process instead, and
  // exits on SIGTERM by itself before the handlers below get a turn, so there
  // the session is left for the server to forget.
  process.stdin.on('end', () => void exit(true))
  process.on('SIGTERM', () => void exit(false))
  process.on('SIGINT', () => void exit(false))
  // The client went away mid-write; there is nobody left to tell.
  process.stdout.on('error', () => process.exit(0))
}

module.exports = { createRelay, main, resolveEndpoint, resolveToken, sseData }
