import { RefreshCw, Server } from 'lucide-react';
import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import adminApi from '../../api/adminAxios';

function Badge({ value }) {
  const ok = value === 'ok' || value === 'healthy';
  return <span className={`rounded-full px-2 py-1 text-xs font-medium ${ok ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>{value || 'unknown'}</span>;
}

export default function AdminSystem() {
  const [health, setHealth] = useState(null);
  const [migrations, setMigrations] = useState([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    try {
      const [healthRes, migrationRes] = await Promise.all([adminApi.get('/health/'), adminApi.get('/admin/system/migrations')]);
      setHealth(healthRes.data);
      setMigrations(migrationRes.data.migrations || []);
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to load system health');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, []);

  if (loading) return <p className="text-xs text-slate-600">Loading system status...</p>;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="page-title">System</h1>
        <p className="page-subtitle">Infrastructure health, database, Redis, Firebase, and migrations.</p>
      </div>
      <section className="theme-card rounded-lg border p-5 shadow-sm">
        <div className="flex items-center justify-between"><h2 className="theme-text flex items-center gap-2 text-sm font-semibold tracking-tight"><Server size={17} />Health</h2><button className="btn-secondary" onClick={load}><RefreshCw size={15} />Refresh</button></div>
        <div className="mt-4 grid gap-3 sm:grid-cols-4">
          {['db', 'redis', 'firebase', 'status'].map((key) => <div key={key} className="theme-card-muted rounded-md border p-3"><p className="theme-muted text-xs font-medium uppercase">{key}</p><div className="mt-2"><Badge value={health?.[key]} /></div></div>)}
        </div>
      </section>
      <section className="theme-card rounded-lg border p-5 shadow-sm">
        <h2 className="theme-text text-sm font-semibold tracking-tight">Migrations</h2>
        <pre className="mt-3 max-h-96 overflow-auto rounded-md bg-slate-950 p-4 text-xs text-slate-100">{migrations.join('\n')}</pre>
      </section>
    </div>
  );
}
