/** Push task types */

export type PushType = 'wecom-app' | 'webhook-group' | 'longconn-group' | 'longconn-single';
export type PushFormStyle = 'url' | 'msg';
export type PushStatus = 'active' | 'draft' | 'stopped';

export interface PushTask {
  id: string;
  agentId: string;
  name: string;
  type: PushType;
  status: PushStatus;
  enabled: boolean;
  formStyle: PushFormStyle;
  webhookUrl?: string;
  chatId?: string;
  targetUser?: string;
  appEntry?: string;
  title?: string;
  titleSuffix?: 'date' | 'none';
  summaryType?: 'none' | 'custom' | 'report' | 'ai';
  summaryContent?: string;
  coverImage?: string;
  pushTiming: 'immediate' | 'period' | 'custom';
  cronExpression?: string;
  audit?: AuditConfig;
  supportChat?: boolean;
  linkedAgentId?: string;
  showThinkingProcess?: boolean;
  atUsers?: AtUserConfig;
  lastPushAt?: string;
  target?: string;
}

export interface AuditConfig {
  enabled: boolean;
  methods: ('ai' | 'manual')[];
  ruleType?: 'mustMeet' | 'mustNotMeet';
  rule?: string;
}

export interface AtUserConfig {
  enabled: boolean;
  type: 'specific' | 'all';
  users: string[];
}
