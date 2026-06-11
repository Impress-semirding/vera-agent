import axios from 'axios';
import { clearUser, getUserName } from './authUser';

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
  // NOTE: no fixed Content-Type — axios auto-sets `application/json` for object
  // bodies and lets the browser set `multipart/form-data; boundary=...` for
  // FormData uploads. A hardcoded json header here would break file uploads.
});

// Attach the logged-in user identity to every request (header-based auth).
// Percent-encode the value: HTTP header bytes are decoded as latin-1, so raw
// non-ASCII names (Chinese) would arrive mojibake'd. The backend unquotes it.
api.interceptors.request.use((config) => {
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
