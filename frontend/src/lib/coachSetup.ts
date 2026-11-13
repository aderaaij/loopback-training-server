// Ready-to-paste setup for pointing an MCP client at this server's coach
// endpoint. Pure string building, so the dashboard can fill in the address the
// athlete is already using and a freshly minted token. Keep in step with the
// "Connect a client" section of the README, which is the long-form version.

export type CoachClientId = 'claude-desktop' | 'claude-code' | 'cursor' | 'vscode' | 'other'

export interface CoachClient {
  id: CoachClientId
  label: string
}

export const COACH_CLIENTS: CoachClient[] = [
  { id: 'claude-desktop', label: 'Claude Desktop' },
  { id: 'claude-code', label: 'Claude Code' },
  { id: 'cursor', label: 'Cursor' },
  { id: 'vscode', label: 'VS Code' },
  { id: 'other', label: 'Other' },
]

export interface CoachSetup {
  steps: string[]
  snippet: string
  // False when the snippet deliberately leaves the token out (VS Code prompts
  // for it), so the token has to be shown and copied on its own.
  snippetHasToken: boolean
}

const SERVER_NAME = 'training'

/** The coach endpoint lives on the same origin as the dashboard. */
export function coachUrl(origin: string): string {
  return `${origin.replace(/\/+$/, '')}/mcp`
}

/**
 * mcp-remote refuses plain http unless told otherwise. It exempts only the
 * names `localhost` and `127.0.0.1` (not `[::1]`), and the flag is harmless
 * there, so every http address gets it rather than mirroring that list.
 */
export function needsAllowHttp(url: string): boolean {
  try {
    return new URL(url).protocol === 'http:'
  } catch {
    return false
  }
}

function json(value: unknown): string {
  return JSON.stringify(value, null, 2)
}

export function buildCoachSetup(client: CoachClientId, url: string, token: string): CoachSetup {
  const bearer = `Bearer ${token}`

  switch (client) {
    case 'claude-desktop': {
      // The header value goes through an env var because Claude Desktop on
      // Windows mishandles spaces inside args.
      const args = ['-y', 'mcp-remote', url, '--header', 'Authorization:${AUTH_HEADER}']
      if (needsAllowHttp(url)) args.push('--allow-http')
      return {
        steps: [
          'Install Node.js 20 or newer from nodejs.org if you don’t have it.',
          'In Claude Desktop, open Settings → Developer → Edit config.',
          'Paste the block below. If the file already has "mcpServers", add only the "training" entry inside it.',
          'Quit Claude Desktop completely and reopen it. Settings → Developer should show "training" as Running.',
        ],
        snippet: json({
          mcpServers: {
            [SERVER_NAME]: { command: 'npx', args, env: { AUTH_HEADER: bearer } },
          },
        }),
        snippetHasToken: true,
      }
    }
    case 'claude-code':
      return {
        steps: ['Run this in a terminal.', 'Start Claude Code in any folder and ask “What did I run this week?”'],
        // One line, no continuations: a trailing backslash only means "next
        // line" in bash and zsh, and this is pasted into PowerShell and cmd
        // too. --scope user, because the default registers the server for the
        // current folder only.
        snippet: `claude mcp add ${SERVER_NAME} --scope user --transport http ${url} --header "Authorization: ${bearer}"`,
        snippetHasToken: true,
      }
    case 'cursor':
      return {
        steps: [
          'Open ~/.cursor/mcp.json (create it if it doesn’t exist).',
          'Paste the block below. If the file already has "mcpServers", add only the "training" entry inside it.',
          'Restart Cursor.',
        ],
        snippet: json({
          mcpServers: { [SERVER_NAME]: { url, headers: { Authorization: bearer } } },
        }),
        snippetHasToken: true,
      }
    case 'vscode':
      return {
        steps: [
          'Create .vscode/mcp.json in your workspace and paste the block below.',
          'VS Code asks for the token the first time the server starts. Paste the token shown underneath.',
        ],
        snippet: json({
          inputs: [
            { type: 'promptString', id: 'training-token', description: 'Training API token', password: true },
          ],
          servers: {
            [SERVER_NAME]: {
              type: 'http',
              url,
              headers: { Authorization: 'Bearer ${input:training-token}' },
            },
          },
        }),
        snippetHasToken: false,
      }
    case 'other':
      return {
        steps: [
          'Add a streamable-HTTP MCP server in your client with this address and header.',
          'Clients that run in the cloud can’t reach a server that is only on your private network.',
        ],
        snippet: `URL:     ${url}\nHeader:  Authorization: ${bearer}`,
        snippetHasToken: true,
      }
  }
}
