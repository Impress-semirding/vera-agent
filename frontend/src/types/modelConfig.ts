/** Model provider configuration types. */

/** Provider identifiers for built-in providers. */
export type ModelProvider = 'deepseek' | 'glm' | 'kimi' | 'mimo' | 'minimax';

/** Full model config record from the backend. */
export interface ModelConfig {
  id: string;
  provider: ModelProvider;
  name: string;
  modelId: string;
  baseUrl: string;
  apiKey: string;
  enabled: boolean;
  updatedAt: string;
  createdAt: string;
}

/** Payload for creating a model config. */
export interface ModelConfigCreate {
  provider: ModelProvider;
  name: string;
  modelId: string;
  baseUrl: string;
  apiKey: string;
  enabled?: boolean;
}

/** Payload for updating a model config. */
export interface ModelConfigUpdate {
  name?: string;
  modelId?: string;
  baseUrl?: string;
  apiKey?: string;
  enabled?: boolean;
}

/** Lightweight model option for agent dropdowns. */
export interface ModelOption {
  label: string;
  value: string;       // modelId — used as the `model` param in API calls
  provider: ModelProvider;
  baseUrl: string;
}

/** Built-in provider presets. `defaultModelId` is the exact value passed as `model` in API calls.
 *  All base URLs point to the Anthropic-compatible endpoint for each provider. */
export const PROVIDER_PRESETS: Record<ModelProvider, { label: string; defaultModelId: string; defaultBaseUrl: string }> = {
  deepseek: { label: 'DeepSeek', defaultModelId: 'deepseek-v4-pro', defaultBaseUrl: 'https://api.deepseek.com/anthropic' },
  glm:      { label: 'GLM',      defaultModelId: 'glm-5.1',         defaultBaseUrl: 'https://open.bigmodel.cn/api/anthropic' },
  kimi:     { label: 'Kimi',     defaultModelId: 'kimi-k2.6',       defaultBaseUrl: 'https://platform.moonshot.cn/anthropic' },
  mimo:     { label: 'MiMo',     defaultModelId: 'mimo-v2-pro',     defaultBaseUrl: 'https://platform.xiaomimimo.com/anthropic' },
  minimax:  { label: 'MiniMax',  defaultModelId: 'MiniMax-M2.7',    defaultBaseUrl: 'https://api.minimaxi.com/anthropic' },
};
