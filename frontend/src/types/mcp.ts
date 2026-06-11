/** MCP server types — references Reasonix src/config.ts McpServerConfig */

export type McpTransport = 'stdio' | 'sse' | 'streamable-http';

export interface McpServerConfig {
  name: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  transport: McpTransport;
  url?: string;
  headers?: Record<string, string>;
  disabled: boolean;
}

export interface McpServerWithTools extends McpServerConfig {
  tools: McpTool[];
}

export interface McpTool {
  name: string;
  description: string;
  enabled: boolean;
}
