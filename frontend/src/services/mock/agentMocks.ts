import type { Agent } from '@/types/agent';

export const mockAgents: Agent[] = [
  {
    id: 'agent-003',
    name: '数据简报助手',
    description: '自动生成每日数据简报推送到企微',
    type: 'system',
    mode: 'normal',
    model: 'glm-5-1',
    avatarUrl: '',
    visibility: true,
    starred: false,
    createdBy: '张三',
    updatedBy: '李四',
    updatedAt: '2026-06-10T08:00:00Z',
    createdAt: '2026-04-15T11:00:00Z',
  },
];
