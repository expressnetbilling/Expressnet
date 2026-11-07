import { Edit, ExternalLink, Globe, Link as LinkIcon, MoreHorizontal, RefreshCw, Search, Trash2, WifiOff, XCircle } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import { useNavigate } from 'react-router-dom';
import api from '../api/axios';
import Pagination from '../components/Pagination';
import { openBearerWebSocket } from '../utils/realtime';

function toDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? null : date;
}

function isFreshLastSeen(value) {
  const date = toDate(value);
  return date ? Date.now() - date.getTime() <= 3 * 60 * 1000 : false;
}

function formatLastSeen(value) {
  const date = toDate(value);
  if (!date) return 'Never';
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return date.toLocaleString();
}

function formatMemory(value) {
  const bytes = Number(value || 0);
  if (!bytes) return '-';
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB free`;
  return `${Math.round(bytes / (1024 * 1024))} MB free`;
}

function webConsoleUrl(router) {
  const host = String(router.lastSeenIp || router.lanIp || router.wanIp || router.tunnelIp || '').trim();
  if (!host || host === '-') return '';
  if (/^https?:\/\//i.test(host)) return host;
  const secure = router.web_scheme === 'https' || Number(router.web_port) === 443;
  const port = Number(router.web_port) || (secure ? 443 : 80);
  const authority = host.includes(':') && !host.startsWith('[') ? `[${host}]` : host;
  return `${secure ? 'https' : 'http'}://${authority}${[80, 443].includes(port) ? '' : `:${port}`}`;
}

export default function MikrotikSettings() {
  const navigate = useNavigate();
  const [config, setConfig] = useState(null);
  const [routerStatus, setRouterStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [workingId, setWorkingId] = useState('');
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [openActionId, setOpenActionId] = useState('');
  const [actionPosition, setActionPosition] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState('');
  const [deletePassword, setDeletePassword] = useState('');
  const [routerRealtimeTick, setRouterRealtimeTick] = useState(0);
  const [hiddenRouterIds, setHiddenRouterIds] = useState(() => new Set());
  const [page, setPage] = useState(1);
  const pageSize = 10;

  const rows = useMemo(() => {
    const linked = config?.linked_routers || {};
    return Object.entries(linked)
      // A settings refresh can arrive after a successful delete with the old
      // Firebase snapshot. Keep deleted rows hidden immediately instead of
      // asking the tenant to delete the same router again.
      .filter(([id]) => !hiddenRouterIds.has(id))
      .map(([id, item]) => ({
      id,
      routerName: item.name || item.mikrotik_name || config?.mikrotik_name || config?.router_name || '',
      boardName: routerStatus?.device?.board_name || item.board_name || item.identity || 'MikroTik Router',
      provisioning: item.provisioning_status || config?.mikrotik_provisioning_status || 'pending',
      cpu: routerStatus?.device?.cpu_load ?? item.cpu_load,
      memory: routerStatus?.device?.free_memory ?? item.free_memory,
      status: routerStatus?.connection_status || item.status || (isFreshLastSeen(item.last_seen_at || config?.mikrotik_last_seen_at) ? 'online' : 'offline'),
      tunnelIp: item.tunnel_ip || config?.mikrotik_host || '-',
      wanIp: item.wan_ip || '',
      lanIp: item.lan_ip || '',
      lastSeenIp: routerStatus?.last_seen_ip || item.last_seen_ip || '',
      lastSeenAt: routerStatus?.last_seen_at || item.last_seen_at || config?.mikrotik_last_seen_at,
      web_port: item.web_port || item.webPort || config?.mikrotik_web_port,
      web_scheme: item.web_scheme || item.webScheme || config?.mikrotik_web_scheme,
      source: routerStatus?.source || 'stored',
      ports: routerStatus?.interfaces?.length ?? item.interface_count,
      version: routerStatus?.device?.version || item.version,
      }));
  }, [config, hiddenRouterIds, routerStatus]);

  const counts = useMemo(() => ({
    all: rows.length,
    online: rows.filter((item) => item.status === 'online').length,
    offline: rows.filter((item) => item.status !== 'online').length,
  }), [rows]);

  const filteredRows = rows.filter((item) => {
    const text = `${item.routerName} ${item.boardName} ${item.tunnelIp} ${item.wanIp} ${item.lanIp} ${item.provisioning}`.toLowerCase();
    if (!text.includes(search.toLowerCase())) return false;
    if (filter === 'online') return item.status === 'online';
    if (filter === 'offline') return item.status !== 'online';
    return true;
  });
  const pagedRows = filteredRows.slice((page - 1) * pageSize, page * pageSize);
  const sessionsCount = Number(routerStatus?.active_sessions?.total ?? routerStatus?.active_sessions ?? 0);

  useEffect(() => {
    setPage(1);
  }, [filter, search]);

  useEffect(() => {
    setPage((current) => Math.min(current, Math.max(1, Math.ceil(filteredRows.length / pageSize))));
  }, [filteredRows.length]);

  async function loadConfig({ silent = false } = {}) {
    if (!silent) setLoading(true);
    try {
      const { data } = await api.get('/settings/mikrotik');
      setConfig(data);
      if (Object.keys(data.linked_routers || {}).length > 0 || data.mikrotik_last_seen_at) {
        try {
          const status = await api.get('/router/status');
          setRouterStatus(status.data);
        } catch {
          setRouterStatus(null);
        }
      }
    } catch (error) {
      toast.error(error.response?.data?.message || 'Failed to load MikroTik routers');
    } finally {
      if (!silent) setLoading(false);
    }
  }

  useEffect(() => {
    const token = localStorage.getItem('billing_saas_token');
    return openBearerWebSocket('/ws/tenant/realtime/', token, (event) => {
      if (String(event.type || '').startsWith('router.')) {
        setRouterRealtimeTick((value) => value + 1);
      }
    });
  }, []);

  useEffect(() => {
    loadConfig();
    const interval = window.setInterval(() => {
      loadConfig({ silent: true });
    }, 30000);
    return () => window.clearInterval(interval);
  }, [routerRealtimeTick]);

  const editRouter = async (routerId) => {
    setOpenActionId('');
    setWorkingId(`edit:${routerId}`);
    try {
      const { data } = await api.get('/router/status');
      setRouterStatus(data);
      toast.success('Router configuration pulled');
      navigate('/mikrotik/link?edit=1');
    } catch (error) {
      setRouterStatus(null);
      toast.error(error.response?.data?.message || 'Failed to pull router configuration');
    } finally {
      setWorkingId('');
    }
  };

  const suspendRouter = async (routerId) => {
    setOpenActionId('');
    setWorkingId(`suspend:${routerId}`);
    try {
      const { data } = await api.post('/router/suspend');
      toast.success(data.message || 'Router suspension queued');
      await loadConfig();
    } catch (error) {
      toast.error(error.response?.data?.message || 'Failed to suspend router');
    } finally {
      setWorkingId('');
    }
  };

  const requestDeleteRouter = (routerId) => {
    setOpenActionId('');
    setActionPosition(null);
    setDeletePassword('');
    setDeleteTarget(routerId);
  };

  const deleteRouter = async () => {
    if (!deleteTarget || !deletePassword) return;
    const routerId = deleteTarget;
    setWorkingId(`delete:${routerId}`);
    try {
      const { data } = await api.delete('/router/delete', { data: { current_password: deletePassword } });
      toast.success(data.message || 'Router deleted');
      // Do not make the operator wait for Firebase/the next status poll before
      // reflecting a successful, password-confirmed deletion. The API clears
      // the tenant's linked router, and this optimistic update prevents the
      // old row being presented as if it still needs deleting.
      setConfig((current) => {
        if (!current) return current;
        return {
          ...current,
          linked_routers: {},
          mikrotik_provisioning_status: '',
          mikrotik_last_seen_at: '',
          mikrotik_last_seen_ip: '',
        };
      });
      setHiddenRouterIds((current) => {
        const next = new Set(current);
        Object.keys(config?.linked_routers || {}).forEach((id) => next.add(id));
        next.add(routerId);
        return next;
      });
      setRouterStatus(null);
      setDeleteTarget('');
      setDeletePassword('');
      // Reconcile in the background; the row is already gone from the UI.
      void loadConfig({ silent: true });
    } catch (error) {
      toast.error(error.response?.data?.message || 'Failed to delete router');
    } finally {
      setWorkingId('');
    }
  };

  const reprovisionRouter = () => {
    setOpenActionId('');
    navigate('/mikrotik/link?reprovision=1');
  };

  if (loading) return <p className="text-sm font-medium text-slate-600">Loading MikroTik routers...</p>;

  return (
    <div className="space-y-5">
      <section>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-[28px] font-medium leading-tight tracking-tight text-[var(--app-text)]">Link <span style={{ color: 'var(--app-accent)' }}>Routers</span></h1>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-primary rounded-full px-5" onClick={() => navigate('/mikrotik/link?add=1')}>
              <LinkIcon size={16} />
              + Link MikroTik
            </button>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 overflow-hidden rounded-2xl border border-[var(--app-border)] bg-[var(--app-panel)] sm:grid-cols-2 xl:grid-cols-4 [&>div]:border-b [&>div]:border-[var(--app-border)] sm:[&>div:nth-child(odd)]:border-r xl:[&>div]:border-b-0 xl:[&>div:not(:last-child)]:border-r">
        {[
          ['Routers', counts.all, 'registered NAS devices'],
          ['Online', counts.online, 'reachable via monitoring'],
          ['Offline', counts.offline, 'not responding'],
          ['Live Sessions', sessionsCount, 'open sessions right now'],
        ].map(([label, value, helper]) => (
          <div key={label} className="min-w-0 px-4 py-4 first:pl-5 last:pr-5">
            <p className="text-[11px] font-medium uppercase tracking-wide text-[var(--app-muted)]">{label}</p>
            <p className="mt-2 text-[22px] font-medium leading-tight tracking-tight text-[var(--app-text)]">{value}</p>
            <p className="mt-2 text-xs text-[var(--app-muted)]">{helper}</p>
          </div>
        ))}
      </section>

      <section>
        <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="inline-flex w-fit rounded-full border border-[var(--app-border)] bg-[var(--app-panel)] p-1">
            {[
              ['all', 'All', counts.all],
              ['online', 'Online', counts.online],
              ['offline', 'Offline', counts.offline],
            ].map(([key, label, count]) => (
              <button
                key={key}
                type="button"
                className={`inline-flex h-8 items-center gap-2 rounded-full px-3 text-xs font-normal transition ${
                  filter === key ? 'bg-[var(--app-panel-muted)] text-[var(--app-text)]' : 'text-[var(--app-muted)]'
                }`}
                onClick={() => setFilter(key)}
              >
                {label}
                <span className="rounded-full bg-[var(--app-panel-muted)] px-1.5 py-0.5 text-[10px] text-[var(--app-muted)]">{count}</span>
              </button>
            ))}
          </div>
          <label className="relative block w-full sm:w-72">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--app-muted)]" size={16} />
            <input className="form-input mt-0 rounded-full border-[var(--app-border)] pl-9" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search name, model, or shortname..." />
          </label>
        </div>

        <div className="overflow-hidden rounded-2xl border border-[var(--app-border)] bg-[var(--app-panel)]">
          <div className="overflow-x-auto">
            <table className="min-w-[980px] w-full divide-y divide-[var(--app-border)]">
              <thead className="bg-[var(--app-panel-muted)] text-left text-xs font-medium uppercase tracking-wide text-[var(--app-muted)]">
                <tr>
                  <th className="px-4 py-3">Router</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Sessions</th>
                  <th className="px-4 py-3">Winbox</th>
                  <th className="px-4 py-3">Web</th>
                  <th className="px-4 py-3">Last Online</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--app-border)] text-sm text-[var(--app-text)]">
                {filteredRows.length === 0 ? (
                  <tr>
                    <td className="px-4 py-8 text-center text-[var(--app-muted)]" colSpan="7">No MikroTik routers linked yet.</td>
                  </tr>
                ) : pagedRows.map((router) => (
                  <tr key={router.id}>
                    <td className="px-4 py-3 font-medium">
                      <div>{router.routerName || router.boardName}</div>
                      {router.routerName && <div className="mt-1 text-[11px] font-normal text-[var(--app-muted)]">{router.boardName}</div>}
                    </td>
                    <td className="px-4 py-3"><span className={`rounded-full border px-2.5 py-1 text-[11px] font-normal ${router.status === 'online' ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-500' : router.status === 'suspended' ? 'border-amber-500/30 bg-amber-500/10 text-amber-500' : 'border-red-500/30 bg-red-500/10 text-red-500'}`}>
                        {router.status === 'online' ? 'Online' : router.status === 'suspended' ? 'Suspended' : 'Offline'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-center">{router.id === rows[0]?.id ? sessionsCount : '-'}</td>
                    <td className="px-4 py-3 font-mono text-xs text-emerald-500">:{router.winbox_port || router.winboxPort || config?.mikrotik_winbox_port || '8291'}</td>
                    <td className="px-4 py-3">{webConsoleUrl(router) ? <a href={webConsoleUrl(router)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-full border border-[var(--app-border)] px-3 py-1 text-xs text-[var(--app-text)] transition hover:border-[var(--app-accent)] hover:text-[var(--app-accent)]"><Globe size={13} />Open<ExternalLink size={11} /></a> : <span className="text-xs text-[var(--app-muted)]">IP unavailable</span>}</td>
                    <td className="px-4 py-3 text-xs">{formatLastSeen(router.lastSeenAt)}</td>
                    <td className="px-4 py-3">
                      <div className="relative flex justify-end">
                        <button
                          type="button"
                          className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-600 transition hover:border-[var(--app-accent-soft)] hover:text-[var(--app-accent)] disabled:cursor-not-allowed disabled:opacity-50"
                          onClick={(event) => {
                            if (openActionId === router.id) {
                              setOpenActionId('');
                              setActionPosition(null);
                              return;
                            }
                            const rect = event.currentTarget.getBoundingClientRect();
                            setOpenActionId(router.id);
                            setActionPosition({ top: rect.bottom + 4, left: rect.right - 176 });
                          }}
                          disabled={Boolean(workingId)}
                          aria-label={`Open actions for ${router.boardName}`}
                          aria-expanded={openActionId === router.id}
                        >
                          <MoreHorizontal size={18} />
                        </button>

                        {openActionId === router.id && (
                          <div style={{ top: actionPosition?.top, left: actionPosition?.left }} className="fixed z-[9999] w-44 rounded-md border border-slate-200 bg-white py-1 text-left shadow-lg">
                            <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-[var(--app-accent-muted)] hover:text-[var(--app-accent)]" onClick={() => editRouter(router.id)}>
                              <Edit size={14} />
                              Edit
                            </button>
                            <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50" onClick={() => suspendRouter(router.id)}>
                              <XCircle size={14} />
                              Suspend
                            </button>
                            <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50" onClick={reprovisionRouter}>
                              <RefreshCw size={14} />
                              Reprovision
                            </button>
                            <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-xs font-semibold text-red-600 hover:bg-red-50" onClick={() => requestDeleteRouter(router.id)}>
                              <Trash2 size={14} />
                              Delete
                            </button>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Pagination page={page} pageSize={pageSize} total={filteredRows.length} label="routers" onPageChange={setPage} />
        </div>
      </section>
      {deleteTarget && (
        <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-slate-950/45 p-4" role="dialog" aria-modal="true" aria-labelledby="delete-router-title">
          <form
            className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl"
            onSubmit={(event) => {
              event.preventDefault();
              deleteRouter();
            }}
          >
            <h2 id="delete-router-title" className="text-lg font-semibold text-slate-900">Delete linked MikroTik?</h2>
            <p className="mt-2 text-sm text-slate-600">Enter your account password to permanently remove this router link and its queued commands.</p>
            <label className="mt-5 block text-sm font-medium text-slate-700" htmlFor="delete-router-password">Account password</label>
            <input
              id="delete-router-password"
              type="password"
              autoComplete="current-password"
              autoFocus
              value={deletePassword}
              onChange={(event) => setDeletePassword(event.target.value)}
              className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-slate-900 outline-none focus:border-[var(--app-accent)] focus:ring-2 focus:ring-[var(--app-accent-muted)]"
              required
            />
            <div className="mt-6 flex justify-end gap-3">
              <button type="button" className="btn-secondary rounded-full px-4" disabled={Boolean(workingId)} onClick={() => { setDeleteTarget(''); setDeletePassword(''); }}>Cancel</button>
              <button type="submit" className="rounded-full bg-red-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={!deletePassword || Boolean(workingId)}>
                {workingId.startsWith('delete:') ? 'Deleting…' : 'Delete router'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
