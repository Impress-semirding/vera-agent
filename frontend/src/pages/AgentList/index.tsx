import { useEffect } from 'react';
import { Spin, Empty } from 'antd';
import { useAgentStore } from '@/stores/useAgentStore';
import AgentListHeader from './AgentListHeader';
import AgentCard from './AgentCard';

export default function AgentListPage() {
  const { agents, loading, fetchAgents } = useAgentStore();
  // Re-fetch whenever any filter changes. (Search still triggers on submit
  // from the header; typing alone does not refetch.)
  const { mode, typeFilter, mineOnly, starredOnly } = useAgentStore();

  useEffect(() => {
    fetchAgents();
  }, [mode, typeFilter, mineOnly, starredOnly, fetchAgents]);

  return (
    <div style={{ minHeight: '100vh', background: '#f5f5f5' }}>
      <AgentListHeader />
      <Spin spinning={loading}>
        {agents.length === 0 && !loading ? (
          <Empty description="暂无智能体" style={{ marginTop: 120 }} />
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, padding: 24 }}>
            {agents.map((agent) => (
              <AgentCard key={agent.id} agent={agent} />
            ))}
          </div>
        )}
      </Spin>
    </div>
  );
}
