import { useEffect, useState } from 'react';
import { Button, Input, Modal, Spin, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { FormCard } from '../components/FormParts';
import { configFileService } from '@/services/configFileService';
import type { ConfigFile } from '@/types/config';

const CLAUDE_MD = 'CLAUDE.md';
const RULES_FOLDER = 'rules';

export default function BaseConfigPanel({ agentId }: { agentId: string }) {
  const [loading, setLoading] = useState(true);
  const [claudeContent, setClaudeContent] = useState('');
  const [claudeSaving, setClaudeSaving] = useState(false);

  const [rules, setRules] = useState<ConfigFile[]>([]);
  const [activeRulePath, setActiveRulePath] = useState<string>('');
  const [ruleContent, setRuleContent] = useState('');
  const [ruleSaving, setRuleSaving] = useState(false);
  const [ruleLoading, setRuleLoading] = useState(false);

  const [addOpen, setAddOpen] = useState(false);
  const [newRuleName, setNewRuleName] = useState('');
  const [adding, setAdding] = useState(false);

  // Load CLAUDE.md + rules tree on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        await Promise.all([loadClaude(), loadRules()]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId]);

  async function loadClaude() {
    try {
      const res = await configFileService.read(agentId, CLAUDE_MD);
      setClaudeContent(res.data?.content ?? '');
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setClaudeContent('');
      } else {
        message.error('加载 CLAUDE.md 失败');
      }
    }
  }

  async function loadRules() {
    try {
      const res = await configFileService.tree(agentId);
      const folder = (res.data ?? []).find((n) => n.path === RULES_FOLDER && n.type === 'folder');
      const children = folder?.children ?? [];
      setRules(children);
      if (children.length > 0 && !children.some((r) => r.path === activeRulePath)) {
        const first = children[0];
        if (first) {
          setActiveRulePath(first.path);
          await loadRuleContent(first.path, first.name);
        }
      } else if (children.length === 0) {
        setActiveRulePath('');
        setRuleContent('');
      }
    } catch {
      message.error('加载 rules 失败');
    }
  }

  async function loadRuleContent(path: string, _name?: string) {
    setRuleLoading(true);
    try {
      const res = await configFileService.read(agentId, path);
      setRuleContent(res.data?.content ?? '');
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setRuleContent('');
      } else {
        message.error('加载规则内容失败');
      }
    } finally {
      setRuleLoading(false);
    }
  }

  async function handleSelectRule(path: string) {
    setActiveRulePath(path);
    await loadRuleContent(path);
  }

  async function handleSaveClaude() {
    setClaudeSaving(true);
    try {
      await configFileService.save(agentId, CLAUDE_MD, claudeContent);
      message.success('CLAUDE.md 已保存');
    } catch {
      message.error('保存 CLAUDE.md 失败');
    } finally {
      setClaudeSaving(false);
    }
  }

  async function handleSaveRule() {
    if (!activeRulePath) return;
    setRuleSaving(true);
    try {
      await configFileService.save(agentId, activeRulePath, ruleContent);
      message.success('规则已保存');
    } catch {
      message.error('保存规则失败');
    } finally {
      setRuleSaving(false);
    }
  }

  function openAdd() {
    setNewRuleName('');
    setAddOpen(true);
  }

  async function handleAddRule() {
    const name = newRuleName.trim();
    if (!name) {
      message.warning('请输入规则名称');
      return;
    }
    const fileName = name.endsWith('.md') ? name : `${name}.md`;
    const path = `${RULES_FOLDER}/${fileName}`;
    setAdding(true);
    try {
      await configFileService.create(agentId, path, '');
      message.success('规则已创建');
      setAddOpen(false);
      setNewRuleName('');
      await loadRules();
      await handleSelectRule(path);
    } catch (err: any) {
      if (err?.response?.status === 409) {
        message.error('该规则已存在');
      } else {
        message.error('创建规则失败');
      }
    } finally {
      setAdding(false);
    }
  }

  const activeRuleName = activeRulePath.split('/').pop() ?? activeRulePath;

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
        <Spin />
      </div>
    );
  }

  return (
    <>
      {/* CLAUDE.md */}
      <FormCard>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <h4 style={{ fontWeight: 600 }}>{CLAUDE_MD}</h4>
          <Button size="small" type="primary" ghost disabled>
            历史版本
          </Button>
        </div>
        <p style={{ fontSize: 12, color: '#00000073', marginBottom: 16 }}>
          每次会话都加载的上下文，智能体级的持久指令，建议不超过200行
        </p>
        <Input.TextArea
          rows={10}
          value={claudeContent}
          onChange={(e) => setClaudeContent(e.target.value)}
          placeholder="在此编辑 CLAUDE.md 内容"
          style={{ fontFamily: 'monospace', background: '#fafafa' }}
        />
        <div style={{ marginTop: 12, textAlign: 'right' }}>
          <Button type="primary" loading={claudeSaving} onClick={handleSaveClaude}>
            保存
          </Button>
        </div>
      </FormCard>

      {/* rules */}
      <FormCard>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <h4 style={{ fontWeight: 600 }}>rules</h4>
          <Button type="link" size="small" icon={<PlusOutlined />} onClick={openAdd}>
            添加rule
          </Button>
        </div>
        <p style={{ fontSize: 12, color: '#00000073', marginBottom: 16 }}>
          复杂项目使用，可分主题设置不同规范
        </p>
        <div style={{ display: 'flex', gap: 16 }}>
          {/* left list */}
          <div style={{ width: 192, flexShrink: 0, border: '1px solid #d9d9d9', borderRadius: 8, padding: 8 }}>
            {rules.length === 0 ? (
              <div style={{ padding: '6px 8px', fontSize: 13, color: '#00000040' }}>暂无规则</div>
            ) : (
              rules.map((r) => {
                const name = r.path.split('/').pop() ?? r.path;
                const active = r.path === activeRulePath;
                return (
                  <div
                    key={r.path}
                    onClick={() => handleSelectRule(r.path)}
                    style={{
                      padding: '6px 8px',
                      borderRadius: 4,
                      cursor: 'pointer',
                      fontSize: 13,
                      background: active ? '#e6f4ff' : '',
                      color: active ? '#1677ff' : '#000000a6',
                    }}
                  >
                    {name}
                  </div>
                );
              })
            )}
          </div>

          {/* right editor */}
          <div style={{ flex: 1, border: '1px solid #d9d9d9', borderRadius: 8, padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
              <span style={{ fontWeight: 500, fontSize: 14 }}>{activeRuleName || '—'}</span>
              <Button size="small" type="primary" ghost disabled>
                历史版本
              </Button>
            </div>
            <Spin spinning={ruleLoading}>
              <Input.TextArea
                rows={8}
                value={ruleContent}
                onChange={(e) => setRuleContent(e.target.value)}
                placeholder="选择左侧规则进行编辑"
                disabled={!activeRulePath}
                style={{ fontFamily: 'monospace', background: '#fafafa' }}
              />
            </Spin>
            <div style={{ marginTop: 12, textAlign: 'right' }}>
              <Button
                type="primary"
                loading={ruleSaving}
                disabled={!activeRulePath}
                onClick={handleSaveRule}
              >
                保存
              </Button>
            </div>
          </div>
        </div>
      </FormCard>

      {/* add rule modal */}
      <Modal
        title="添加 rule"
        open={addOpen}
        onCancel={() => setAddOpen(false)}
        confirmLoading={adding}
        onOk={handleAddRule}
        okText="创建"
        cancelText="取消"
        destroyOnClose
      >
        <Input
          placeholder="规则名称，例如 sample"
          value={newRuleName}
          onChange={(e) => setNewRuleName(e.target.value)}
          onPressEnter={handleAddRule}
          autoFocus
        />
      </Modal>
    </>
  );
}
