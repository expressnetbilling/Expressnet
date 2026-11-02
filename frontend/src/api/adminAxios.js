import axios from 'axios';
import { ADMIN_API_PATH, adminLoginUrl } from '../config/adminPaths';
import { apiBaseUrl } from '../config/apiBaseUrl';

const adminApi = axios.create({
  baseURL: apiBaseUrl(),
  timeout: 60000,
});

adminApi.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  if (typeof config.url === 'string' && config.url.startsWith('/admin')) {
    config.url = `${ADMIN_API_PATH}${config.url.slice('/admin'.length)}`;
  }
  return config;
});

adminApi.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.code === 'ECONNABORTED') {
      return Promise.reject(new Error('The server took too long to respond. Please try again.'));
    }

    if ([401, 403].includes(error.response?.status)) {
      localStorage.removeItem('admin_token');
      localStorage.removeItem('admin_user');
      const loginUrl = adminLoginUrl();
      const target = new URL(loginUrl, window.location.href);
      if (window.location.origin !== target.origin || window.location.pathname !== target.pathname) {
        window.location.assign(loginUrl);
      }
    }
    return Promise.reject(error);
  },
);

export default adminApi;
