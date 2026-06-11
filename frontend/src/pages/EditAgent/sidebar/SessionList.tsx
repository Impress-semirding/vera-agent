import { Popconfirm } from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import s from '../index.module.less';

interface Session {
  id: string;
  name: string;
  active: boolean;
}

interface SessionListProps {
  sessions: Session[];
  onNew: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

export default function SessionList({ sessions, onNew, onSelect, onDelete }: SessionListProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
      <div style={{ padding: '10px 12px 4px' }}>
        <button className={s.newSessionBtn} onClick={onNew}>
          <PlusOutlined /> 新建会话
        </button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '4px 8px' }}>
        {sessions.map((sess) => (
          <div
            key={sess.id}
            className={`${s.sessionItem} ${sess.active ? s.active : ''}`}
            onClick={() => onSelect(sess.id)}
          >
            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {sess.name}
            </span>
            <Popconfirm title="删除此会话？" onConfirm={(e) => { e?.stopPropagation(); onDelete(sess.id); }}>
              <DeleteOutlined style={{ fontSize: 12, color: '#00000040' }} onClick={(e) => e.stopPropagation()} />
            </Popconfirm>
          </div>
        ))}
      </div>
    </div>
  );
}
