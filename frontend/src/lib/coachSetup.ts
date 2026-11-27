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
  // Config or command to paste. Null when the client needs no pasting beyond
  // the token itself.
  snippet: string | null
  // False when the snippet deliberately leaves the token out (VS Code prompts
  // for it), so the token has to be shown and copied on its own.
  snippetHasToken: boolean
  // The client is set up by installing the extension the server hands out
  // (GET /api/coach/claude-desktop.mcpb), offered as a download.
  extension?: boolean
  // Something the client shows during setup that looks alarming and is not.
  note?: string
}

const SERVER_NAME = 'training'

/** The coach endpoint lives on the same origin as the dashboard. */
export function coachUrl(origin: string): string {
  return `${origin.replace(/\/+$/, '')}/mcp`
}

function json(value: unknown): string {
  return JSON.stringify(value, null, 2)
}

export function buildCoachSetup(client: CoachClientId, url: string, token: string): CoachSetup {
  const bearer = `Bearer ${token}`

  switch (client) {
    case 'claude-desktop':
      // An extension rather than a config file: Claude Desktop runs it with
      // the Node it ships and asks for the settings in a form, so there is
      // nothing to install or edit by hand. The server address is filled in
      // by the download; the token is not, because the file gets left in a
      // downloads folder. The by-hand mcp-remote setup stays in the README.
      return {
        steps: [
          'Download the extension and open the file. Claude Desktop shows it with an Install button.',
          'Install it. When it asks for settings, the server address is already filled in: paste the token below into Token.',
          'Start a new chat and ask “What did I run this week?”',
        ],
        snippet: null,
        snippetHasToken: false,
        extension: true,
        // Claude Desktop shows both for any extension that comes from a file
        // rather than its directory and is not signed. Signing needs a paid
        // certificate and one fixed file per release, which would cost the
        // filled-in server address, so the dialog says what to expect instead.
        note:
          'Claude Desktop warns that an extension can access your computer, and lists the developer as unknown. ' +
          'That is expected for an extension installed from a file. This one reads no files: it only passes ' +
          'messages between Claude Desktop and this server.',
      }
    case 'claude-code':
      return {
        steps: [
          'Run this in a terminal.',
          'If it says "training" already exists, run "claude mcp remove training --scope user" and try again.',
          'Start Claude Code in any folder and ask “What did I run this week?”',
        ],
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
