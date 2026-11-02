const DEFAULT_API_BASE_URL = '/api';

export function apiBaseUrl(value = import.meta.env.VITE_API_BASE_URL) {
  const configured = String(value || '').trim().replace(/\/+$/, '');
  if (!configured) return DEFAULT_API_BASE_URL;

  // Axios treats a bare host such as "expressnetbilling.com/api" as a
  // relative path. Only accept explicit same-origin paths or full URLs.
  if (configured.startsWith('/')) return configured;
  if (/^https?:\/\//i.test(configured)) return configured;
  return DEFAULT_API_BASE_URL;
}
