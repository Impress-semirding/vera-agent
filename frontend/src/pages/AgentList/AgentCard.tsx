import { Tag } from 'antd';
import { StarFilled, StarOutlined } from '@ant-design/icons';
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
  const initial = agent.name.charAt(0).toUpperCase();

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
      </div>
    </div>
  );
}
