#!/usr/bin/env node
'use strict'

/*
 * The extension's entry point (manifest.json: server.entry_point).
 *
 * It starts the relay, always. Do not put this behind
 * `require.main === module`: with its built-in Node, Claude Desktop does not
 * run this file as the main program. Its own host script loads it with
 * import(), so that test is never true there, the server never starts, and
 * Claude Desktop waits two minutes for an answer to "initialize" before
 * giving up. That is why the relay lives in a file of its own: the tests can
 * load relay.js without starting anything.
 */
require('./relay').main()
