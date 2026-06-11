import api from './api';
import type { ApiResponse } from '@/types/api';
import type { Skill } from '@/types/skill';

/** Parsed name + description returned by inspecting an uploaded zip. */
export interface SkillInspect {
  name: string;
  description: string;
}

/** Partial payload for updating skill metadata. */
export type SkillUpdateData = Partial<Pick<Skill, 'description' | 'model' | 'version' | 'enabled'>>;

function triggerBlobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export const skillService = {
  list: (agentId: string) =>
    api.get<any, ApiResponse<Skill[]>>(`/agents/${agentId}/skills`),

  /** Parse an uploaded zip for a client-side preview (name + description). */
  inspect: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api.post<any, ApiResponse<SkillInspect>>(`/skills/inspect`, form);
  },

  /** Upload a skill .zip; name + description are parsed server-side from SKILL.md. */
  upload: (
    agentId: string,
    file: File,
    version: string,
    opts?: { runAs?: Skill['runAs']; model?: string },
  ) => {
    const form = new FormData();
    form.append('file', file);
    form.append('version', version);
    if (opts?.runAs) form.append('run_as', opts.runAs);
    if (opts?.model) form.append('model', opts.model);
    return api.post<any, ApiResponse<Skill>>(`/agents/${agentId}/skills`, form);
  },

  /** Download the original skill .zip and save it locally. */
  download: async (skillId: string, filename: string) => {
    const blob = await api.get<unknown, Blob>(`/skills/${skillId}/download`, { responseType: 'blob' });
    triggerBlobDownload(blob, filename);
  },

  update: (skillId: string, data: SkillUpdateData) =>
    api.put<any, ApiResponse<Skill>>(`/skills/${skillId}`, data),

  remove: (skillId: string) =>
    api.delete<any, ApiResponse<void>>(`/skills/${skillId}`),

  toggle: (skillId: string, enabled: boolean) =>
    api.patch<any, ApiResponse<{ id: string; enabled: boolean }>>(
      `/skills/${skillId}/enabled`,
      { enabled },
    ),
};
