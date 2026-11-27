'use strict'

/*
 * The relay inside the Claude Desktop extension, driven the way Claude
 * Desktop drives it: started as a process, JSON-RPC lines on stdin, answers
 * read from stdout, with a small HTTP server standing in for the coach
 * endpoint.
 *
 *   node --test backend/tests/desktop_extension/relay.test.js
 *
 * No dependencies; needs Node 18 or newer, like the relay.
 */

const assert = require('node:assert/strict')
const { fork, spawn } = require('node:child_process')
const http = require('node:http')
const path = require('node:path')
const readline = require('node:readline')
const { test } = require('node:test')

const SERVER_DIR = path.join(__dirname, '..', '..', 'app', 'desktop_extension', 'server')
// What the manifest names as the entry point, and what Claude Desktop loads.
const SCRIPT = path.join(SERVER_DIR, 'index.js')
// How Claude Desktop loads it with its built-in Node; see the file.
const CLAUDE_HOST = path.join(__dirname, 'claude_host.js')
const { resolveEndpoint, resolveToken, sseData } = require(path.join(SERVER_DIR, 'relay.js'))

const TOKEN = 'tapi_test'
const INITIALIZE = {
  jsonrpc: '2.0',
  id: 1,
  method: 'initialize',
  params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'test', version: '0' } },
}

/** An HTTP server on a free port. `requests` lists what it got, in order of arrival. */
async function startServer(t, handler) {
  const requests = []
  let busy = 0
  const server = http.createServer(async (req, res) => {
    busy++
    res.on('close', () => busy--)
    let raw = ''
    for await (const chunk of req) raw += chunk
    const entry = { method: req.method, headers: req.headers, body: raw ? JSON.parse(raw) : null }
    requests.push(entry)
    await handler(entry, res)
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const close = () =>
    new Promise((resolve) => {
      server.closeAllConnections()
      server.close(resolve)
    })
  // Also after a failed assertion, or the open port keeps the run from ending.
  t.after(close)
  return {
    url: `http://127.0.0.1:${server.address().port}`,
    requests,
    close,
    /** Resolves once `count` requests have arrived and all have been answered. */
    async answered(count) {
      while (requests.length < count || busy > 0) await new Promise((resolve) => setTimeout(resolve, 5))
    },
  }
}

function sendJson(res, message, headers = {}) {
  res.writeHead(200, { 'Content-Type': 'application/json', ...headers })
  res.end(JSON.stringify(message))
}

/**
 * A stand-in for the coach endpoint: sessions, and an echo for everything
 * else. Like the real one it answers 404 for a session it does not know.
 * Stricter than the real one, it refuses a request on a session whose
 * "initialized" notification has not arrived yet, as the protocol allows.
 */
function coach() {
  const state = { live: new Set(), ready: new Set(), issued: 0 }
  const handler = (entry, res) => {
    const { body, headers } = entry
    if (entry.method === 'DELETE') {
      state.live.delete(headers['mcp-session-id'])
      res.writeHead(200).end()
      return
    }
    if (body.method === 'initialize') {
      const session = `session-${++state.issued}`
      state.live.add(session)
      sendJson(
        res,
        { jsonrpc: '2.0', id: body.id, result: { protocolVersion: '2025-06-18', capabilities: {}, serverInfo: { name: 'fake' } } },
        { 'Mcp-Session-Id': session },
      )
      return
    }
    const session = headers['mcp-session-id']
    if (!state.live.has(session)) {
      res.writeHead(404, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ jsonrpc: '2.0', id: null, error: { code: -32600, message: 'Session not found' } }))
      return
    }
    if (body.id === undefined || body.method === undefined) {
      if (body.method === 'notifications/initialized') state.ready.add(session)
      // What the real server sends for a notification: 202, labelled JSON, empty.
      res.writeHead(202, { 'Content-Type': 'application/json' }).end()
      return
    }
    if (!state.ready.has(session)) {
      sendJson(res, { jsonrpc: '2.0', id: body.id, error: { code: -32602, message: 'Received request before initialization was complete' } })
      return
    }
    sendJson(res, { jsonrpc: '2.0', id: body.id, result: { echo: body.method, session } })
  }
  return { state, handler }
}

/**
 * The relay started the way Claude Desktop starts it with its built-in Node:
 * loaded by a host script instead of run as the program, with a stand-in for
 * stdin and stdout. Same handle as startRelay, minus `end`.
 */
function startHostedRelay(t, serverUrl, token = TOKEN) {
  const child = fork(CLAUDE_HOST, [SCRIPT], {
    env: { PATH: process.env.PATH, LOOPBACK_SERVER_URL: serverUrl, LOOPBACK_TOKEN: token },
    stdio: ['ignore', 'pipe', 'pipe', 'ipc'],
  })
  t.after(() => child.kill('SIGKILL'))
  const received = []
  const waiters = []
  let stderr = ''
  let written = ''
  child.stderr.on('data', (data) => (stderr += data))
  child.on('message', (message) => {
    if (message.type === 'fatal') stderr += message.content
    if (message.type !== 'stdout') return
    written += message.content
    let end
    while ((end = written.indexOf('\n')) !== -1) {
      received.push(JSON.parse(written.slice(0, end)))
      written = written.slice(end + 1)
    }
    for (const waiter of [...waiters]) waiter()
  })
  return {
    received,
    stderr: () => stderr,
    send: (message) => child.send({ type: 'stdin', data: JSON.stringify(message) }),
    answer: (id) => awaitAnswer(id, received, waiters, () => stderr),
    /** Claude Desktop stops the helper process; the host exits on the signal. */
    stop: () =>
      new Promise((resolve) => {
        child.on('exit', resolve)
        child.kill('SIGTERM')
      }),
  }
}

/** The answer to the request with this id, once it is among `received`. */
function awaitAnswer(id, received, waiters, stderr) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`no answer to ${id}; stderr: ${stderr()}`)), 5000)
    const check = () => {
      const found = received.find((m) => m.id === id && m.method === undefined)
      if (!found) return
      clearTimeout(timer)
      waiters.splice(waiters.indexOf(check), 1)
      resolve(found)
    }
    waiters.push(check)
    check()
  })
}

function startRelay(t, serverUrl, token = TOKEN) {
  const child = spawn(process.execPath, [SCRIPT], {
    env: { PATH: process.env.PATH, LOOPBACK_SERVER_URL: serverUrl, LOOPBACK_TOKEN: token },
    stdio: ['pipe', 'pipe', 'pipe'],
  })
  t.after(() => child.kill('SIGKILL'))
  const received = []
  const waiters = []
  let stderr = ''
  child.stderr.on('data', (data) => (stderr += data))
  readline.createInterface({ input: child.stdout }).on('line', (line) => {
    received.push(JSON.parse(line))
    for (const waiter of [...waiters]) waiter()
  })
  const exited = new Promise((resolve) => child.on('exit', resolve))

  return {
    received,
    stderr: () => stderr,
    send: (message) => child.stdin.write(`${JSON.stringify(message)}\n`),
    answer: (id) => awaitAnswer(id, received, waiters, () => stderr),
    /** Closes stdin, as Claude Desktop does on quit, and waits for the exit. */
    async end() {
      child.stdin.end()
      return exited
    },
  }
}

/** A relay with its session open: initialize answered, "initialized" delivered. */
async function opened(t, server, { address = server.url, token = TOKEN } = {}) {
  const relay = startRelay(t, address, token)
  relay.send(INITIALIZE)
  const answer = await relay.answer(1)
  relay.send({ jsonrpc: '2.0', method: 'notifications/initialized' })
  await server.answered(2)
  return { relay, answer }
}

test('relays a request and its answer, carrying the token and the session', async (t) => {
  const { handler } = coach()
  const server = await startServer(t, handler)
  const { relay, answer } = await opened(t, server)
  assert.equal(answer.result.serverInfo.name, 'fake')

  relay.send({ jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} })
  assert.deepEqual((await relay.answer(2)).result, { echo: 'tools/list', session: 'session-1' })

  const [first, , third] = server.requests
  assert.equal(first.headers.authorization, `Bearer ${TOKEN}`)
  assert.equal(first.headers['mcp-session-id'], undefined)
  assert.equal(third.body.method, 'tools/list')
  assert.equal(third.headers['mcp-session-id'], 'session-1')
  assert.equal(third.headers['mcp-protocol-version'], '2025-06-18')

  assert.equal(await relay.end(), 0)
  await server.close()
})

test('runs the way Claude Desktop runs it with its built-in Node', async (t) => {
  // Loaded by a host script rather than started as the program, and fed
  // through a stand-in for stdin. A relay that only starts when it is the
  // main module, or that reads stdin some other way than 'data' events,
  // stays silent here, and Claude Desktop gives up after two minutes.
  const { state, handler } = coach()
  const server = await startServer(t, handler)
  const relay = startHostedRelay(t, server.url)

  relay.send({ ...INITIALIZE, id: 0 })
  assert.equal((await relay.answer(0)).result.serverInfo.name, 'fake')
  relay.send({ jsonrpc: '2.0', method: 'notifications/initialized' })
  relay.send({ jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} })
  assert.deepEqual((await relay.answer(2)).result, { echo: 'tools/list', session: 'session-1' })
  assert.equal(relay.stderr(), '')

  // The host exits on the signal before the relay can end the session, so
  // the server is left to forget it. Nothing to assert but a clean stop.
  await relay.stop()
  assert.equal(state.live.size, 1)
})

test('a request before initialize is answered, not left hanging', async (t) => {
  // Claude Desktop first starts a second copy and asks it "server/discover"
  // to see which generation of the protocol the server speaks, giving it
  // four seconds. The coach endpoint refuses a request without a session;
  // what matters is that the refusal comes back as an answer.
  const { handler } = coach()
  const server = await startServer(t, handler)
  const relay = startHostedRelay(t, server.url)
  relay.send({ jsonrpc: '2.0', id: 0, method: 'server/discover' })
  const answer = await relay.answer(0)
  assert.equal(typeof answer.error.message, 'string')
  await relay.stop()
})

test('the address may be the dashboard address; /mcp is added', async (t) => {
  const { handler } = coach()
  const server = await startServer(t, handler)
  const { relay } = await opened(t, server, { address: `${server.url}/settings?tab=coach`, token: `Bearer ${TOKEN}` })
  assert.equal(server.requests[0].headers.authorization, `Bearer ${TOKEN}`)
  await relay.end()
  await server.close()
})

test('a notification gets no answer and no complaint', async (t) => {
  const { handler } = coach()
  const server = await startServer(t, handler)
  const { relay } = await opened(t, server)
  relay.send({ jsonrpc: '2.0', id: 2, method: 'ping' })
  await relay.answer(2)
  // initialize and ping answered; notifications/initialized was not.
  assert.deepEqual(
    relay.received.map((m) => m.id),
    [1, 2],
  )
  assert.equal(relay.stderr(), '')
  await relay.end()
  await server.close()
})

test('reads an answer sent as an event stream, in pieces', async (t) => {
  const { handler } = coach()
  const progress = { jsonrpc: '2.0', method: 'notifications/progress', params: { progress: 1 } }
  const result = { jsonrpc: '2.0', id: 2, result: { content: [{ type: 'text', text: 'done\nand more' }] } }
  const server = await startServer(t, async (entry, res) => {
    if (entry.body && entry.body.method === 'tools/call') {
      const stream = `: ping\r\n\r\nevent: message\r\ndata: ${JSON.stringify(progress)}\r\n\r\nid: 7\r\ndata: ${JSON.stringify(result)}\r\n\r\n`
      res.writeHead(200, { 'Content-Type': 'text/event-stream' })
      // Cut where a line, and the \r\n that ends one, are split across chunks.
      for (const end of [9, 40, stream.length - 3, stream.length]) {
        res.write(stream.slice(res.sent || 0, end))
        res.sent = end
        await new Promise((resolve) => setTimeout(resolve, 15))
      }
      res.end()
      return
    }
    handler(entry, res)
  })
  const { relay } = await opened(t, server)
  relay.send({ jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'x' } })
  assert.deepEqual(await relay.answer(2), result)
  assert.deepEqual(relay.received[1], progress)
  await relay.end()
  await server.close()
})

test('opens a new session when the server has forgotten the old one', async (t) => {
  const { state, handler } = coach()
  const server = await startServer(t, handler)
  const { relay } = await opened(t, server)

  state.live.clear() // the server restarted
  relay.send({ jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} })
  assert.deepEqual((await relay.answer(2)).result, { echo: 'tools/list', session: 'session-2' })

  // Refused, then the relay's own initialize and initialized, then the retry.
  const after = server.requests.slice(2).map((r) => [r.body.method, r.headers['mcp-session-id']])
  assert.deepEqual(after, [
    ['tools/list', 'session-1'],
    ['initialize', undefined],
    ['notifications/initialized', 'session-2'],
    ['tools/list', 'session-2'],
  ])
  // The renewal reuses what the client sent, and its answer stays inside the relay.
  assert.deepEqual(server.requests[3].body.params, INITIALIZE.params)
  assert.deepEqual(
    relay.received.map((m) => m.id),
    [1, 2],
  )
  await relay.end()
  await server.close()
})

test('requests that fail together share one new session', async (t) => {
  const { state, handler } = coach()
  const server = await startServer(t, handler)
  const { relay } = await opened(t, server)

  state.live.clear()
  for (const id of [2, 3, 4]) relay.send({ jsonrpc: '2.0', id, method: 'tools/list', params: {} })
  const answers = await Promise.all([2, 3, 4].map((id) => relay.answer(id)))
  assert.deepEqual(
    answers.map((a) => a.result.session),
    ['session-2', 'session-2', 'session-2'],
  )
  assert.equal(server.requests.filter((r) => r.body.method === 'initialize').length, 2)
  await relay.end()
  await server.close()
})

test('says so when the token is refused', async (t) => {
  const server = await startServer(t, (entry, res) => res.writeHead(401, { 'Content-Type': 'application/json' }).end('{"detail":"no"}'))
  const relay = startRelay(t, server.url)
  relay.send(INITIALIZE)
  const answer = await relay.answer(1)
  assert.match(answer.error.message, /refused the token/)
  assert.match(answer.error.message, /Settings → AI coach → Connect/)
  await relay.end()
  await server.close()
})

test('says so when the server cannot be reached', async (t) => {
  const server = await startServer(t, () => {})
  await server.close() // the port is now closed
  const relay = startRelay(t, server.url)
  relay.send(INITIALIZE)
  const answer = await relay.answer(1)
  assert.match(answer.error.message, /Could not reach the Loopback server at http:\/\/127\.0\.0\.1:\d+ \(ECONNREFUSED\)/)
  await relay.end()
})

test('says so when the address or the token is missing', async (t) => {
  for (const [url, token, expected] of [
    ['', TOKEN, /No server address is set/],
    ['my-server:8001', TOKEN, /not a full address/],
    ['http://127.0.0.1:1', '', /No token is set/],
  ]) {
    const relay = startRelay(t, url, token)
    relay.send(INITIALIZE)
    assert.match((await relay.answer(1)).error.message, expected)
    await relay.end()
  }
})

test('answers with an error when the stream ends without the answer', async (t) => {
  const { handler } = coach()
  const server = await startServer(t, (entry, res) => {
    if (entry.body && entry.body.method === 'tools/call') {
      res.writeHead(200, { 'Content-Type': 'text/event-stream' }).end(': nothing\n\n')
      return
    }
    handler(entry, res)
  })
  const { relay } = await opened(t, server)
  relay.send({ jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'x' } })
  assert.match((await relay.answer(2)).error.message, /closed the connection before it answered/)
  await relay.end()
  await server.close()
})

test('ends the session when the client goes away', async (t) => {
  const { state, handler } = coach()
  const server = await startServer(t, handler)
  const { relay } = await opened(t, server)
  relay.send({ jsonrpc: '2.0', id: 2, method: 'ping' })
  await relay.answer(2)
  assert.equal(await relay.end(), 0)

  const last = server.requests.at(-1)
  assert.equal(last.method, 'DELETE')
  assert.equal(last.headers['mcp-session-id'], 'session-1')
  assert.equal(last.headers.authorization, `Bearer ${TOKEN}`)
  assert.equal(state.live.size, 0)
  await server.close()
})

test('a request sent just before stdin closes is still answered', async (t) => {
  const { handler } = coach()
  const server = await startServer(t, async (entry, res) => {
    if (entry.body && entry.body.method === 'tools/list') await new Promise((resolve) => setTimeout(resolve, 150))
    handler(entry, res)
  })
  const { relay } = await opened(t, server)
  relay.send({ jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} })
  await relay.end()
  assert.ok(relay.received.some((m) => m.id === 2 && m.result))
  await server.close()
})

test('a request waits for the notification written before it', async (t) => {
  // Claude Desktop writes "initialized" and its first requests back to back.
  // Each is its own HTTP request, so a slow notification must hold them up.
  const { handler } = coach()
  const server = await startServer(t, async (entry, res) => {
    if (entry.body && entry.body.method === 'notifications/initialized') await new Promise((resolve) => setTimeout(resolve, 80))
    handler(entry, res)
  })
  const relay = startRelay(t, server.url)
  relay.send(INITIALIZE)
  await relay.answer(1)
  relay.send({ jsonrpc: '2.0', method: 'notifications/initialized' })
  relay.send({ jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} })
  relay.send({ jsonrpc: '2.0', id: 3, method: 'prompts/list', params: {} })
  const [tools, prompts] = await Promise.all([relay.answer(2), relay.answer(3)])
  assert.equal(tools.error, undefined)
  assert.equal(prompts.error, undefined)
  await relay.end()
})

test('a cancellation is delivered while the call it cancels is still running', async (t) => {
  const { handler } = coach()
  let cancelledDuringCall = false
  let callRunning = false
  const server = await startServer(t, async (entry, res) => {
    const method = entry.body && entry.body.method
    if (method === 'tools/call') {
      callRunning = true
      await new Promise((resolve) => setTimeout(resolve, 200))
      callRunning = false
    }
    if (method === 'notifications/cancelled') cancelledDuringCall = callRunning
    handler(entry, res)
  })
  const { relay } = await opened(t, server)
  relay.send({ jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'slow' } })
  await new Promise((resolve) => setTimeout(resolve, 50))
  relay.send({ jsonrpc: '2.0', method: 'notifications/cancelled', params: { requestId: 2 } })
  await relay.answer(2)
  assert.equal(cancelledDuringCall, true)
  await relay.end()
})

test('resolveEndpoint', () => {
  for (const [entered, endpoint] of [
    ['https://loopback.example.com', 'https://loopback.example.com/mcp'],
    ['https://loopback.example.com/', 'https://loopback.example.com/mcp'],
    ['  http://my-server:8001  ', 'http://my-server:8001/mcp'],
    ['http://my-server:8001/mcp/', 'http://my-server:8001/mcp'],
    ['https://host:8443/workouts/123?x=1#top', 'https://host:8443/mcp'],
    ['https://host/loopback/mcp', 'https://host/loopback/mcp'],
    ['https://user:pw@host/', 'https://host/mcp'],
  ]) {
    assert.equal(resolveEndpoint(entered), endpoint, entered)
  }
  for (const entered of ['', '   ', 'my-server:8001', 'ftp://host', 'not an address', '${user_config.server_url}']) {
    assert.throws(() => resolveEndpoint(entered), entered)
  }
})

test('resolveToken', () => {
  assert.equal(resolveToken('  tapi_abc \n'), 'tapi_abc')
  assert.equal(resolveToken('Bearer tapi_abc'), 'tapi_abc')
  assert.equal(resolveToken('bearer   tapi_abc'), 'tapi_abc')
  for (const entered of ['', '  ', 'Bearer ', '${user_config.token}']) assert.throws(() => resolveToken(entered))
})

test('sseData', async () => {
  const encode = (text) => new TextEncoder().encode(text)
  async function* chunks(...parts) {
    for (const part of parts) yield encode(part)
  }
  const collect = async (...parts) => {
    const events = []
    for await (const data of sseData(chunks(...parts))) events.push(data)
    return events
  }
  assert.deepEqual(await collect('data: one\n\ndata: two\n\n'), ['one', 'two'])
  // Several data lines are one event; a comment and other fields are skipped.
  assert.deepEqual(await collect(': hi\nid: 1\nevent: message\ndata: a\ndata: b\n\n'), ['a\nb'])
  // A multi-byte character and a line ending split across chunks.
  const bytes = encode('data: café\r\n\r\n')
  async function* split() {
    yield bytes.slice(0, 10)
    yield bytes.slice(10, 12)
    yield bytes.slice(12)
  }
  const events = []
  for await (const data of sseData(split())) events.push(data)
  assert.deepEqual(events, ['café'])
  // The last event of a stream that ends without the closing blank line,
  // or in the middle of its line.
  assert.deepEqual(await collect('data: last\n'), ['last'])
  assert.deepEqual(await collect('data: one\n\ndata: la', 'st'), ['one', 'last'])
})
