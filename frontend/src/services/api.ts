import axios from 'axios';
import { clearUser, getToken, getUserName } from './authUser';

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
  // NOTE: no fixed Content-Type — axios auto-sets `application/json` for object
  // bodies and lets the browser set `multipart/form-data; boundary=...` for
  // FormData uploads. A hardcoded json header here would break file uploads.
});

// Attach the signed session token and X-User identity to every request.
api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers['Authorization'] = `Bearer ${token}`;
  const name = getUserName();
  if (name) config.headers['X-User'] = encodeURIComponent(name);
  return config;
});

api.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const status = err.response?.status;
    const url: string | undefined = err.config?.url;
    // 401 ⇒ identity gone/invalid → clear and bounce to login. Skip the
    // intentional /auth/me bootstrap probe (useAuthStore handles that locally).
    if (status === 401 && url && !url.includes('/auth/me')) {
      clearUser();
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    const msg = err.response?.data?.message || err.message || '请求失败';
    console.error('[API Error]', msg);
    return Promise.reject(err);
  },
);

export default api;
