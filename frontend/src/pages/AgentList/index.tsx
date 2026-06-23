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
    <div className="app-page">
      <AgentListHeader />
      <Spin spinning={loading}>
        {agents.length === 0 && !loading ? (
          <Empty description="暂无智能体" style={{ marginTop: 120 }} />
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 'var(--space-4)', padding: 'var(--space-6)' }}>
            {agents.map((agent) => (
              <AgentCard key={agent.id} agent={agent} />
            ))}
          </div>
        )}
      </Spin>
    </div>
  );
}
