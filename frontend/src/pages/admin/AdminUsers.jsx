import { PlugZap, Search, ShieldOff } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import adminApi from '../../api/adminAxios';
import StatusBadge from '../../components/StatusBadge';

export default function AdminUsers() {
  const [users, setUsers] = useState([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [workingId, setWorkingId] = useState(null);

  async function load() {
    setLoading(true);
    try {
      const { data } = await adminApi.get('/admin/users');
      setUsers(Array.isArray(data) ? data : []);
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to load users');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const filtered = useMemo(() => {
    const text = query.toLowerCase().trim();
    if (!text) return users;
    return users.filter((user) =>
      [user.name, user.phone, user.username, user.tenant_name, user.package]
        .some((value) => String(value || '').toLowerCase().includes(text))
    );
  }, [users, query]);

  const action = async (user, type) => {
    setWorkingId(user.id);
    try {
      await adminApi.post(`/admin/users/${user.tenant_id}/${user.id}/${type}`);
      toast.success(type === 'reconnect' ? 'User reconnected' : 'User disabled');
      await load();
    } catch (error) {
      toast.error(error.response?.data?.error || 'Action failed');
    } finally {
      setWorkingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="page-title">Platform Users</h1>
          <p className="page-subtitle">View and manage hotspot customers across all tenants.</p>
        </div>
        <div className="relative sm:w-80">
          <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
          <input className="form-input mt-0 pl-10" placeholder="Search users" value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
      </div>

      <div className="table-shell overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200">
          <thead className="table-head">
            <tr>
              <th className="px-4 py-3">Tenant</th>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Phone</th>
              <th className="px-4 py-3">Username</th>
              <th className="px-4 py-3">Package</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr><td className="table-cell text-slate-500" colSpan="7">Loading users...</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td className="table-cell text-slate-500" colSpan="7">No users found.</td></tr>
            ) : filtered.map((user) => (
              <tr key={`${user.tenant_id}-${user.id}`}>
                <td className="table-cell">{user.tenant_name}</td>
                <td className="table-cell font-medium text-slate-900">{user.name || '-'}</td>
                <td className="table-cell">{user.phone || '-'}</td>
                <td className="table-cell">{user.username || '-'}</td>
                <td className="table-cell">{user.package || '-'}</td>
                <td className="table-cell"><StatusBadge status={user.status} /></td>
                <td className="table-cell">
                  <div className="flex flex-wrap gap-2">
                    <button className="btn-secondary" onClick={() => action(user, 'reconnect')} disabled={workingId === user.id}>
                      <PlugZap size={16} />Reconnect
                    </button>
                    <button className="btn-danger" onClick={() => action(user, 'disable')} disabled={workingId === user.id}>
                      <ShieldOff size={16} />Disable
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
