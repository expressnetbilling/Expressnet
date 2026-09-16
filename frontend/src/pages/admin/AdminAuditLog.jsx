import { useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import adminApi from '../../api/adminAxios';
import AdminActionBadge from '../../components/admin/AdminActionBadge';

export default function AdminAuditLog() {
  const [logs, setLogs] = useState([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);

  async function load(showError = true) {
    try {
      const { data } = await adminApi.get('/admin/tenants/audit/logs');
      setLogs(Array.isArray(data) ? data : []);
    } catch (error) {
      if (showError) toast.error(error.response?.data?.error || 'Failed to load audit logs');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(() => load(false), 30000);
    return () => window.clearInterval(timer);
  }, []);

  const filtered = useMemo(() => {
    const text = query.toLowerCase().trim();
    if (!text) return logs;
    return logs.filter((log) =>
      String(log.action || '').toLowerCase().includes(text) ||
      String(log.admin_email || '').toLowerCase().includes(text)
    );
  }, [logs, query]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="page-title">Audit Log</h1>
          <p className="page-subtitle">Auto-refreshes every 30 seconds.</p>
        </div>
        <input className="form-input sm:max-w-xs" placeholder="Filter by action or admin email" value={query} onChange={(event) => setQuery(event.target.value)} />
      </div>

      <div className="table-shell overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200">
          <thead className="table-head">
            <tr>
              <th className="px-4 py-3">Timestamp</th>
              <th className="px-4 py-3">Admin</th>
              <th className="px-4 py-3">Action</th>
              <th className="px-4 py-3">Target Type</th>
              <th className="px-4 py-3">Target ID</th>
              <th className="px-4 py-3">IP Address</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr><td className="table-cell text-slate-500" colSpan="6">Loading audit logs...</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td className="table-cell text-slate-500" colSpan="6">No matching audit logs.</td></tr>
            ) : filtered.map((log) => (
              <tr key={log.id}>
                <td className="table-cell">{log.timestamp ? new Date(log.timestamp).toLocaleString() : '-'}</td>
                <td className="table-cell">{log.admin_email || '-'}</td>
                <td className="table-cell"><AdminActionBadge action={log.action} /></td>
                <td className="table-cell">{log.target_type || '-'}</td>
                <td className="table-cell">{log.target_id || '-'}</td>
                <td className="table-cell">{log.ip_address || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
