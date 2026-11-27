'use strict'

/*
 * A stand-in for the way Claude Desktop runs a Node extension while "Use
 * built-in Node.js for MCP" is on, which is its default. That is not
 * `node server/index.js` with pipes. Claude Desktop starts its own host
 * script in a helper process, and the host
 *
 *   - loads the extension's entry point with import(), so the entry point is
 *     never the main module (`require.main === module` is false in it);
 *   - has no real stdin: it swaps the reading methods of process.stdin for
 *     those of a stream it pushes each incoming message into, one per line;
 *   - replaces process.stdout.write and passes what is written on as messages;
 *   - exits at once on SIGTERM, before the extension can do anything.
 *
 * Written from reading the host in Claude Desktop 6.28899
 * (app.asar/.vite/build/mcp-runtime/nodeHost.js). There the messages travel
 * over a MessagePort; here they travel over Node's IPC channel, which is what
 * a test can drive:
 *
 *   child_process.fork(thisFile, [entryPoint], { stdio: ['ignore', 'pipe', 'pipe', 'ipc'] })
 *   child.send({ type: 'stdin', data: '<one JSON-RPC message>' })
 *   child.on('message', ({ type, content }) => ...)   // type: 'stdout' | 'fatal'
 */

const path = require('node:path')
const { Readable } = require('node:stream')
const { pathToFileURL } = require('node:url')

const entryPoint = process.argv[2]

process.on('SIGTERM', () => process.exit(0))

process.stdout.write = (chunk, encoding, callback) => {
  const content = typeof chunk === 'string' ? chunk : Buffer.from(chunk).toString('utf8')
  if (content) process.send({ type: 'stdout', content })
  const done = typeof encoding === 'function' ? encoding : callback
  if (done) process.nextTick(done)
  return true
}

const fed = new Readable({ read() {} })
for (const name of [
  'read',
  'push',
  'unshift',
  'pause',
  'resume',
  'pipe',
  'unpipe',
  'on',
  'once',
  'removeListener',
  'removeAllListeners',
  'setEncoding',
  'destroy',
  'isPaused',
]) {
  process.stdin[name] = fed[name].bind(fed)
}
process.on('message', (message) => {
  if (message && message.type === 'stdin') fed.push(`${message.data}\n`)
})

process.argv = ['node', entryPoint]
import(pathToFileURL(path.resolve(entryPoint)).toString()).catch((err) => {
  process.send({ type: 'fatal', content: String((err && err.stack) || err) })
  process.exit(1)
})
