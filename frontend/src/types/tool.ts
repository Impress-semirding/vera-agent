/** Tool / MCP types — references Reasonix src/tools.ts, src/types.ts */

export interface JSONSchema {
  type?: string;
  properties?: Record<string, JSONSchema>;
  items?: JSONSchema;
  required?: string[];
  description?: string;
  enum?: unknown[];
  [k: string]: unknown;
}

export interface ToolDefinition {
  name: string;
  description?: string;
  parameters?: JSONSchema;
  readOnly?: boolean;
  parallelSafe?: boolean;
  stormExempt?: boolean;
  enabled: boolean;
  mcpServer?: string;
}
