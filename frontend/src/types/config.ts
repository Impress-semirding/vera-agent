/** Agent configuration — references Reasonix src/config.ts */

export type PresetName = 'auto' | 'flash' | 'pro';
export type EditMode = 'review' | 'auto' | 'yolo';
export type ReasoningEffort = 'high' | 'max';

export interface SessionSettings {
  allowUpload: boolean;
  allowEffortCustomization: boolean;
  allowManualContextClear: boolean;
}

export interface AgentConfig {
  preset?: PresetName;
  editMode?: EditMode;
  reasoningEffort?: ReasoningEffort;
  workspaceDir?: string;
  mcpServers?: Record<string, import('./mcp').McpServerConfig>;
  skills?: { paths?: string[] };
  sessionSettings?: SessionSettings;
}

export interface ConfigFile {
  name: string;
  path: string;
  type: 'file' | 'folder';
  children?: ConfigFile[];
}

export interface ConfigFileVersion {
  id: string;
  content: string;
  author: string;
  timestamp: string;
}
