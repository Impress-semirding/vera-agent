import { Tag, Popconfirm, message } from 'antd';
import { StarFilled, StarOutlined, DeleteOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { Agent } from '@/types/agent';
import { useAgentStore } from '@/stores/useAgentStore';
import styles from './index.module.less';

const TYPE_LABELS = { system: 'Cluade code' };
const TYPE_COLORS = { system: 'blue', personal: 'green' };
const MODE_LABELS = { claude: 'Claude Code', normal: '普通模式' };
const MODE_COLORS = { claude: 'geekblue', normal: 'default' };

export default function AgentCard({ agent }: { agent: Agent }) {
  const navigate = useNavigate();
  const toggleStar = useAgentStore((s) => s.toggleStar);
  const deleteAgent = useAgentStore((s) => s.deleteAgent);
  const initial = agent.name.charAt(0).toUpperCase();
  const canDelete = agent.permissions?.includes('delete') ?? false;

  const handleDelete = async () => {
    try {
      await deleteAgent(agent.id);
      message.success('已删除');
    } catch {
      message.error('删除失败');
    }
  };

  return (
    <div className={styles.card} onClick={() => navigate(`/chat/${agent.id}`)}>
      <div className={styles.cardTop}>
        <div className={styles.avatar}>{initial}</div>
        <div className={styles.cardInfo}>
          <div className={styles.cardName}>{agent.name}</div>
          <div className={styles.cardBadges}>
            <Tag color={TYPE_COLORS[agent.type]}>{TYPE_LABELS[agent.type]}</Tag>
            <Tag color={MODE_COLORS[agent.mode]}>{MODE_LABELS[agent.mode]}</Tag>
          </div>
        </div>
      </div>

      <span
        className={`${styles.starBtn} ${agent.starred ? styles.starred : ''}`}
        onClick={(e) => {
          e.stopPropagation();
          toggleStar(agent.id);
        }}
      >
        {agent.starred ? <StarFilled /> : <StarOutlined />}
      </span>

      <div className={styles.cardFooter}>
        <span>{agent.updatedBy}</span>
        <span>·</span>
        <span>{new Date(agent.updatedAt).toLocaleDateString('zh-CN')}</span>
        {canDelete && (
          <span onClick={(e) => e.stopPropagation()} style={{ marginLeft: 'auto' }}>
            <Popconfirm
              title="确认删除该智能体？"
              description="删除后不可恢复"
              onConfirm={handleDelete}
            >
              <span className={styles.deleteBtn}>
                <DeleteOutlined />
              </span>
            </Popconfirm>
          </span>
        )}
      </div>
    </div>
  );
}
