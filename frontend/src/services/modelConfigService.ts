import api from './api';
import type { ApiResponse } from '@/types/api';
import type { ModelConfig, ModelConfigCreate, ModelConfigUpdate, ModelOption } from '@/types/modelConfig';

const BASE = '/model-configs';

export const modelConfigService = {
  /** List all model configs. */
  list(): Promise<ApiResponse<ModelConfig[]>> {
    return api.get<unknown, ApiResponse<ModelConfig[]>>(BASE);
  },

  /** Create a model config. */
  create(data: ModelConfigCreate): Promise<ApiResponse<ModelConfig>> {
    return api.post<unknown, ApiResponse<ModelConfig>>(BASE, data);
  },

  /** Update a model config. */
  update(id: string, data: ModelConfigUpdate): Promise<ApiResponse<ModelConfig>> {
    return api.put<unknown, ApiResponse<ModelConfig>>(`${BASE}/${id}`, data);
  },

  /** Delete a model config. */
  remove(id: string): Promise<ApiResponse<void>> {
    return api.delete<unknown, ApiResponse<void>>(`${BASE}/${id}`);
  },

  /** Toggle enabled. */
  toggleEnabled(id: string, enabled: boolean): Promise<ApiResponse<{ id: string; enabled: boolean }>> {
    return api.patch<unknown, ApiResponse<{ id: string; enabled: boolean }>>(`${BASE}/${id}/enabled`, { enabled });
  },

  /** Get enabled models as dropdown options for agent forms. */
  listModels(): Promise<ApiResponse<ModelOption[]>> {
    return api.get<unknown, ApiResponse<ModelOption[]>>(`${BASE}/models`);
  },
};
