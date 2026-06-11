import { useCallback, useEffect, useState } from 'react';
import {
  Button, Input, Modal, Popconfirm, Spin, Switch, Upload, message,
} from 'antd';
import {
  CodeOutlined, DeleteOutlined, DownloadOutlined,
  FileTextOutlined, InboxOutlined, PlusOutlined,
} from '@ant-design/icons';
import { FormCard } from '../components/FormParts';
import { skillService } from '@/services/skillService';
import type { Skill, SkillFile } from '@/types/skill';

const { Dragger } = Upload;

export default function SkillConfigPanel({ agentId }: { agentId: string }) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Add-skill modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [autoName, setAutoName] = useState('');
  const [description, setDescription] = useState('');
  const [version, setVersion] = useState('');

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const res = await skillService.list(agentId);
      setSkills(res.data ?? []);
    } catch {
      message.error('加载技能列表失败');
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    reload();
  }, [reload]);

  const resetModal = () => {
    setFile(null);
    setAutoName('');
    setDescription('');
    setVersion('');
    setInspecting(false);
  };

  const openModal = () => {
    resetModal();
    setModalOpen(true);
  };

  const handleInspect = async (f: File) => {
    setFile(f);
    setAutoName('');
    setDescription('');
    setInspecting(true);
    try {
      const res = await skillService.inspect(f);
      setAutoName(res.data.name);
      setDescription(res.data.description);
    } catch {
      message.error('解析技能包失败，请确认 zip 内含 SKILL.md');
      setFile(null);
    } finally {
      setInspecting(false);
    }
  };

  const handleCreate = async () => {
    if (!file) {
      message.warning('请上传技能 zip 包');
      return;
    }
    if (!version.trim()) {
      message.warning('请输入版本号');
      return;
    }
    if (inspecting) return;
    setSubmitting(true);
    try {
      await skillService.upload(agentId, file, version.trim());
      message.success('技能已添加');
      setModalOpen(false);
      resetModal();
      reload();
    } catch (err: unknown) {
      const msg = extractErrorMessage(err) ?? '添加技能失败';
      message.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDownload = async (skill: Skill) => {
    try {
      await skillService.download(skill.id, `${skill.name}.zip`);
    } catch {
      message.error('下载失败');
    }
  };

  const handleToggle = async (skill: Skill, enabled: boolean) => {
    const prev = skills;
    setSkills((list) => list.map((s) => (s.id === skill.id ? { ...s, enabled } : s)));
    try {
      await skillService.toggle(skill.id, enabled);
    } catch {
      setSkills(prev);
      message.error('切换状态失败');
    }
  };

  const handleRemove = async (skillId: string) => {
    try {
      await skillService.remove(skillId);
      message.success('技能已删除');
      reload();
    } catch {
      message.error('删除技能失败');
    }
  };

  return (
    <FormCard>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h4 style={{ fontWeight: 600, margin: 0 }}>技能配置（Skill）</h4>
        <Button type="primary" icon={<PlusOutlined />} onClick={openModal}>
          添加技能
        </Button>
      </div>

      <Spin spinning={loading}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {skills.map((skill) => {
            const expanded = expandedId === skill.id;
            const files: SkillFile[] =
              skill.files && skill.files.length > 0
                ? skill.files
                : [{ name: 'SKILL.md', type: 'markdown' }];
            return (
              <div
                key={skill.id}
                style={{ border: '1px solid #d9d9d9', borderRadius: 8, overflow: 'hidden' }}
              >
                <div
                  style={{
                    padding: 16,
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    cursor: 'pointer',
                  }}
                  onClick={() => setExpandedId(expanded ? null : skill.id)}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
                    <span style={{ fontSize: 16 }}>📁</span>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 500, fontSize: 14 }}>
                        {skill.name} <span style={{ color: '#00000073', fontWeight: 400 }}>v{skill.version}</span>
                      </div>
                      <p style={{ fontSize: 12, color: '#00000073', marginTop: 4, marginBottom: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {skill.description || '—'}
                      </p>
                      <p style={{ fontSize: 12, color: '#00000040', marginTop: 2, marginBottom: 0 }}>
                        修改时间: {new Date(skill.updatedAt).toLocaleString('zh-CN')} | 修改人: {skill.updatedBy}
                      </p>
                    </div>
                  </div>
                  <div
                    style={{ display: 'flex', alignItems: 'center', gap: 16, flexShrink: 0 }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Switch
                      size="small"
                      checked={skill.enabled}
                      onChange={(v) => handleToggle(skill, v)}
                    />
                    <DownloadOutlined
                      style={{ color: skill.hasZip ? '#1677ff' : '#00000040', cursor: skill.hasZip ? 'pointer' : 'not-allowed' }}
                      onClick={() => skill.hasZip && handleDownload(skill)}
                    />
                    <Popconfirm
                      title="确认删除该技能？"
                      okText="删除"
                      cancelText="取消"
                      onConfirm={() => handleRemove(skill.id)}
                    >
                      <DeleteOutlined style={{ color: '#ff4d4f', cursor: 'pointer' }} />
                    </Popconfirm>
                  </div>
                </div>

                {expanded && (
                  <div style={{ padding: '0 24px 16px' }}>
                    <div
                      style={{
                        borderLeft: '2px solid #d9d9d9',
                        paddingLeft: 16,
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 8,
                      }}
                    >
                      {files.map((f, idx) => (
                        <div
                          key={`${f.name}-${idx}`}
                          style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, padding: '6px 0' }}
                        >
                          {f.type === 'code' ? (
                            <CodeOutlined style={{ color: '#52c41a' }} />
                          ) : (
                            <FileTextOutlined style={{ color: '#1677ff' }} />
                          )}
                          {f.name}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </Spin>

      <Modal
        title="添加技能"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleCreate}
        confirmLoading={submitting}
        okText="保存"
        cancelText="取消"
        okButtonProps={{ disabled: !file || inspecting }}
        destroyOnClose
      >
        {/* 技能名称（自动读取） */}
        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 14, fontWeight: 500 }}>
            技能名称 <span style={{ fontSize: 12, color: '#00000073' }}>(自动读取)</span>
          </label>
          <Input
            readOnly
            value={autoName}
            placeholder="默认以 SKILL.md 内的 name 或文件夹名称为准"
            style={{ marginTop: 4, background: '#fafafa' }}
          />
          <div style={{ fontSize: 12, color: '#00000073', marginTop: 4 }}>
            {description ? `描述：${description}` : '技能名称将自动从上传文件中识别'}
          </div>
        </div>

        {/* 版本号 */}
        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 14, fontWeight: 500 }}>
            版本号 <span style={{ color: '#ff4d4f' }}>*</span>
          </label>
          <Input
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            placeholder="如 v1.0.0"
            style={{ marginTop: 4 }}
          />
          <div style={{ fontSize: 12, color: '#00000073', marginTop: 4 }}>请输入版本号，不要与已上传的版本相同</div>
        </div>

        {/* 版本提示 */}
        <div
          style={{
            background: '#e6f4ff',
            border: '1px solid #bae0ff',
            borderRadius: 8,
            padding: 10,
            marginBottom: 12,
            fontSize: 12,
            color: '#1677ff',
          }}
        >
          <strong>提示：</strong>版本号用于区分技能的不同版本，相同版本号可能导致错误
        </div>

        {/* 上传 zip */}
        <Dragger
          accept=".zip,application/zip"
          multiple={false}
          showUploadList={false}
          beforeUpload={(f) => {
            // antd passes an RcFile, which is a File subclass.
            void handleInspect(f);
            return false;
          }}
        >
          {inspecting ? (
            <Spin />
          ) : (
            <>
              <p className="ant-upload-drag-icon" style={{ marginBottom: 8 }}>
                <InboxOutlined style={{ color: '#1677ff', fontSize: 36 }} />
              </p>
              <p style={{ margin: 0, color: '#00000073', fontSize: 13 }}>
                {file ? `已选择：${file.name}` : '点击或拖拽文件到此处上传'}
              </p>
              <p style={{ margin: '4px 0 0', color: '#00000040', fontSize: 12 }}>支持 .zip 格式</p>
            </>
          )}
        </Dragger>
      </Modal>
    </FormCard>
  );
}

/** Best-effort extraction of a backend error message from an axios error. */
function extractErrorMessage(err: unknown): string | undefined {
  if (err && typeof err === 'object') {
    const data = (err as { response?: { data?: { message?: unknown } } }).response?.data;
    const m = data?.message;
    if (typeof m === 'string' && m) return m;
  }
  return undefined;
}
