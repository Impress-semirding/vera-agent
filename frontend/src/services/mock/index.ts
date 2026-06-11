import MockAdapter from 'axios-mock-adapter';
import api from '../api';
import { mockAgents } from './agentMocks';

const mock = new MockAdapter(api, { delayResponse: 300 });

// ---- Agent CRUD ----
mock.onGet('/agents').reply((config) => {
  const params = config.params || {};
  let items = [...mockAgents];
  if (params.type && params.type !== 'all') items = items.filter((a) => a.type === params.type);
  if (params.mode) items = items.filter((a) => a.mode === params.mode);
  if (params.search) {
    const q = params.search.toLowerCase();
    items = items.filter((a) => a.name.toLowerCase().includes(q));
  }
  if (params.starred) items = items.filter((a) => a.starred);
  return [200, { code: 0, data: { items, total: items.length }, message: 'ok' }];
});

mock.onPost('/agents').reply((config) => {
  const body = JSON.parse(config.data);
  const agent = {
    id: `agent-${Date.now()}`,
    ...body,
    starred: false,
    visibility: true,
    createdBy: 'current-user',
    updatedBy: 'current-user',
    updatedAt: new Date().toISOString(),
    createdAt: new Date().toISOString(),
  };
  mockAgents.push(agent);
  return [200, { code: 0, data: agent, message: 'ok' }];
});

mock.onGet(/\/agents\/agent-\w+/).reply((config) => {
  const id = config.url?.split('/').pop();
  const agent = mockAgents.find((a) => a.id === id);
  if (agent) return [200, { code: 0, data: agent, message: 'ok' }];
  return [404, { code: 404, data: null, message: 'not found' }];
});

mock.onPost(/\/agents\/agent-\w+\/star/).reply(200, { code: 0, data: null, message: 'ok' });

// Catch-all for unmocked endpoints — return empty success
mock.onAny().reply(200, { code: 0, data: null, message: 'mock ok' });

export default mock;
