/** Skill types — references Reasonix src/skills.ts */
export type SkillScope = 'project' | 'custom' | 'global' | 'builtin';
export type SkillRunAs = 'inline' | 'subagent';

export interface Skill {
  id: string;
  name: string;
  description: string;
  body: string;
  scope: SkillScope;
  path: string;
  allowedTools?: string[];
  runAs: SkillRunAs;
  model?: string;
  version: string;
  enabled: boolean;
  updatedBy: string;
  updatedAt: string;
  files?: SkillFile[];
  /** Whether the original .zip package is stored and downloadable. */
  hasZip?: boolean;
}

export interface SkillFile {
  name: string;
  type: 'markdown' | 'code' | 'config';
}

export interface SkillVersion {
  id: string;
  version: string;
  content: string;
  author: string;
  timestamp: string;
}
