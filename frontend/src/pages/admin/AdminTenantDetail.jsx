import { ArrowLeft, ExternalLink, Router, Save } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import adminApi from '../../api/adminAxios';
import { adminPath } from '../../config/adminPaths';
import StatusBadge from '../../components/StatusBadge';

const profileFields = ['business_name', 'owner_name', 'email', 'phone', 'status'];
const labels = { business_name: 'Business name', owner_name: 'Owner name', email: 'Email', phone: 'Phone', status: 'Status' };
const initialNetwork = { mikrotik_host: '', mikrotik_user: '', mikrotik_port: '8728' };

function Metric({ title, value, note }) {
  return <article className="theme-card rounded-2xl border p-5 shadow-sm"><p className="theme-muted text-xs font-medium">{title}</p><p className="theme-text mt-2 text-2xl font-bold tracking-tight">{value}</p><p className="theme-muted mt-1 text-[10px]">{note}</p></article>;
}

function DataTable({ rows, columns, empty }) {
  return <div className="table-shell overflow-x-auto rounded-xl"><table className="min-w-full divide-y divide-slate-200 text-left"><thead className="table-head"><tr>{columns.map((column) => <th key={column.key} className="whitespace-nowrap px-4 py-3">{column.label}</th>)}</tr></thead><tbody className="divide-y divide-slate-100">{rows.length === 0 ? <tr><td className="table-cell py-10 text-center text-slate-500" colSpan={columns.length}>{empty}</td></tr> : rows.map((row) => <tr key={row.id} className="transition hover:bg-slate-50">{columns.map((column) => <td key={column.key} className="table-cell">{column.render ? column.render(row) : row[column.key] || '—'}</td>)}</tr>)}</tbody></table></div>;
}

export default function AdminTenantDetail() {
  const { id } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [tenant, setTenant] = useState(null);
  const [overview, setOverview] = useState(null);
  const [form, setForm] = useState({});
  const [network, setNetwork] = useState(initialNetwork);
  const [networkPassword, setNetworkPassword] = useState('');
  const [tabRows, setTabRows] = useState([]);
  const [mikrotikResult, setMikrotikResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [tabSaving, setTabSaving] = useState(false);
  const tab = ['overview', 'profile', 'network', 'customers', 'payments', 'packages', 'audit'].includes(searchParams.get('tab')) ? searchParams.get('tab') : 'overview';

  const loadTenant = useCallback(async () => {
    const { data } = await adminApi.get(`/admin/tenants/${id}`);
    setTenant(data);
    setForm(Object.fromEntries(profileFields.map((field) => [field, data[field] || ''])));
    setNetwork({ mikrotik_host: data.mikrotik_host || '', mikrotik_user: data.mikrotik_user || '', mikrotik_port: String(data.mikrotik_port || 8728) });
  }, [id]);

  const loadTab = useCallback(async (selected) => {
    if (selected === 'network' || selected === 'profile') { setTabRows([]); return; }
    const { data } = await adminApi.get(`/admin/tenants/${id}/${selected}`);
    if (selected === 'overview') setOverview(data);
    else {
      const rows = Array.isArray(data) ? data : [];
      // Show the current tenant's latest payment first, even where an older
      // ledger import is returned in insertion order.
      setTabRows(selected === 'payments' ? [...rows].sort((left, right) => {
        const leftTime = Date.parse(left.paid_at || left.initiated_at || left.created_at || '') || 0;
        const rightTime = Date.parse(right.paid_at || right.initiated_at || right.created_at || '') || 0;
        return rightTime - leftTime;
      }) : rows);
    }
  }, [id]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    loadTenant().catch((error) => { if (alive) toast.error(error.response?.data?.error || 'Failed to load tenant'); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [loadTenant]);

  useEffect(() => {
    let alive = true;
    loadTab(tab).catch((error) => { if (alive) toast.error(error.response?.data?.error || `Failed to load ${tab}`); });
    return () => { alive = false; };
  }, [loadTab, tab]);

  const switchTab = (next) => setSearchParams({ tab: next });
  const updateProfile = (event) => setForm((current) => ({ ...current, [event.target.name]: event.target.value }));
  const updateNetwork = (event) => setNetwork((current) => ({ ...current, [event.target.name]: event.target.value }));

  const saveProfile = async (event) => {
    event.preventDefault(); setSaving(true);
    try {
      await adminApi.patch(`/admin/tenants/${id}`, { ...form, plan: tenant?.subscription?.plan || 'basic' });
      toast.success('Tenant profile updated'); await loadTenant();
    } catch (error) { toast.error(error.response?.data?.error || 'Failed to update tenant profile'); }
    finally { setSaving(false); }
  };

  const saveNetwork = async (event) => {
    event.preventDefault(); setTabSaving(true);
    try {
      const payload = { ...network, mikrotik_port: Number(network.mikrotik_port || 8728) };
      if (networkPassword.trim()) payload.mikrotik_pass = networkPassword;
      await adminApi.patch(`/admin/tenants/${id}`, payload);
      toast.success('Network settings updated'); setNetworkPassword(''); await loadTenant();
    } catch (error) { toast.error(error.response?.data?.error || 'Failed to save network settings'); }
    finally { setTabSaving(false); }
  };

  const testMikrotik = async () => {
    setMikrotikResult(null);
    try { const { data } = await adminApi.post(`/admin/tenants/${id}/mikrotik/test`); setMikrotikResult(data); toast.success(data.success ? 'MikroTik connected' : 'MikroTik test failed'); }
    catch (error) { setMikrotikResult({ success: false, error: error.response?.data?.error || 'Connection failed' }); }
  };

  if (loading) return <p className="text-xs font-semibold text-slate-500">Loading tenant…</p>;
  if (!tenant) return <p className="text-xs font-semibold text-slate-500">Tenant not found.</p>;

  const tabs = ['overview', 'profile', 'network', 'customers', 'payments', 'packages', 'audit'];
  const customerColumns = [{ key: 'name', label: 'Name' }, { key: 'phone', label: 'Phone' }, { key: 'username', label: 'Username' }, { key: 'service_type', label: 'Service' }, { key: 'package', label: 'Package' }, { key: 'status', label: 'Status', render: (row) => <StatusBadge status={row.status} /> }, { key: 'expiry_date', label: 'Expiry' }];
  const paymentColumns = [{ key: 'customer_name', label: 'Customer' }, { key: 'phone', label: 'Phone' }, { key: 'amount', label: 'Amount', render: (row) => `KES ${Number(row.amount || 0).toLocaleString()}` }, { key: 'payment_code', label: 'Reference' }, { key: 'provider', label: 'Provider' }, { key: 'paid_at', label: 'Paid at' }, { key: 'status', label: 'Status', render: (row) => <StatusBadge status={row.status} /> }];
  const packageColumns = [{ key: 'name', label: 'Name' }, { key: 'speed', label: 'Speed' }, { key: 'duration_days', label: 'Duration' }, { key: 'price', label: 'Price', render: (row) => `KES ${row.price || 0}` }];
  const auditColumns = [{ key: 'timestamp', label: 'When', render: (row) => row.timestamp ? new Date(row.timestamp).toLocaleString() : '—' }, { key: 'admin_email', label: 'Actor' }, { key: 'action', label: 'Event', render: (row) => String(row.action || 'event').replaceAll('_', '.') }, { key: 'ip', label: 'Source' }];
  const columns = { customers: customerColumns, payments: paymentColumns, packages: packageColumns, audit: auditColumns };

  return <div className="space-y-6">
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><Link to={adminPath('tenants')} className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300"><ArrowLeft size={14}/>Tenant directory</Link><h1 className="page-title mt-2">{tenant.business_name}</h1><p className="mt-1 text-[11px] font-semibold text-slate-400">Tenant ID: {tenant.id}</p></div><a className="btn-secondary" href={`/portal/${tenant.id}`} target="_blank" rel="noreferrer"><ExternalLink size={16}/>Customer portal</a></div>
    <div className="flex flex-wrap gap-2">{tabs.map((item) => <button key={item} type="button" onClick={() => switchTab(item)} className={`rounded-lg px-3 py-2 text-xs font-semibold capitalize ${tab === item ? 'bg-app-accent text-white' : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-50'}`}>{item === 'network' ? 'Network settings' : item}</button>)}</div>

    {tab === 'overview' && <div className="space-y-5"><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><Metric title="PPPoE customers" value={Number(overview?.pppoeCustomers || 0).toLocaleString()} note="Customer accounts using PPPoE"/><Metric title="Hotspot users" value={Number(overview?.hotspotUsers || 0).toLocaleString()} note="Customer accounts using hotspot"/><Metric title="Total customers" value={Number(overview?.totalCustomers || 0).toLocaleString()} note="Across supported service types"/><Metric title="Average monthly revenue" value={`KES ${Number(overview?.averageMonthlyRevenue || 0).toLocaleString()}`} note="Average of the last six calendar months"/></div><section className="theme-card overflow-hidden rounded-2xl border p-5"><div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="theme-text text-sm font-bold">Monthly payment revenue</h2><p className="theme-muted mt-1 text-xs">Last six months · successful customer payments</p></div><span className="theme-muted text-[10px]">KES</span></div><div className="mt-6 grid h-48 grid-cols-6 items-end gap-3">{(overview?.revenueByMonth || []).map((item) => { const max = Math.max(...(overview?.revenueByMonth || []).map((entry) => Number(entry.amount || 0)), 1); const height = Math.max(5, Number(item.amount || 0) / max * 100); return <div key={item.month} className="flex h-full flex-col items-center justify-end gap-2"><span className="theme-muted text-[9px]">{Number(item.amount || 0).toLocaleString()}</span><div className="w-full max-w-12 rounded-t-lg bg-app-accent transition-all" style={{ height: `${height}%` }}/><span className="theme-muted text-[10px]">{item.month}</span></div>; })}</div></section></div>}

    {tab === 'profile' && <form className="theme-card rounded-2xl border p-5 sm:p-6" onSubmit={saveProfile}><h2 className="theme-text mb-4 text-sm font-bold">Business profile</h2><div className="grid gap-4 md:grid-cols-2">{profileFields.map((field) => <div key={field}><label className="form-label" htmlFor={field}>{labels[field]}</label>{field === 'status' ? <select id={field} name={field} className="form-input" value={form[field]} onChange={updateProfile}><option value="active">Active</option><option value="pending_setup">Pending setup</option><option value="suspended">Suspended</option><option value="inactive">Inactive</option></select> : <input id={field} name={field} className="form-input" value={form[field] || ''} onChange={updateProfile}/>}</div>)}</div><button type="submit" className="btn-primary mt-5" disabled={saving}><Save size={16}/>{saving ? 'Saving…' : 'Save profile'}</button></form>}

    {tab === 'network' && <form className="theme-card rounded-2xl border p-5 sm:p-6" onSubmit={saveNetwork}><div className="mb-4 flex items-start justify-between gap-3"><div><h2 className="theme-text flex items-center gap-2 text-sm font-bold"><Router size={16}/>Tenant network access</h2><p className="theme-muted mt-1 text-xs">Router credentials and connection settings for this tenant.</p></div><span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold ${tenant.onboarding?.mikrotik ? 'bg-emerald-500/15 text-emerald-500' : 'bg-amber-500/15 text-amber-600'}`}>{tenant.onboarding?.mikrotik ? 'Configured' : 'Not configured'}</span></div><div className="grid gap-4 md:grid-cols-2">{[['mikrotik_host', 'MikroTik host'], ['mikrotik_user', 'MikroTik user'], ['mikrotik_port', 'MikroTik port']].map(([field, label]) => <div key={field}><label className="form-label" htmlFor={field}>{label}</label><input id={field} name={field} type={field === 'mikrotik_port' ? 'number' : 'text'} className="form-input" value={network[field]} onChange={updateNetwork}/></div>)}<div><label className="form-label" htmlFor="network_password">MikroTik password</label><input id="network_password" type="password" className="form-input" value={networkPassword} onChange={(event) => setNetworkPassword(event.target.value)} placeholder="Leave blank to keep existing" autoComplete="new-password"/></div></div><div className="mt-5 flex flex-wrap items-center gap-3"><button type="submit" className="btn-primary" disabled={tabSaving}><Save size={16}/>{tabSaving ? 'Saving…' : 'Save network settings'}</button><button type="button" className="btn-secondary" onClick={testMikrotik}><Router size={15}/>Test connection</button>{mikrotikResult && <span className={`text-xs font-semibold ${mikrotikResult.success ? 'text-emerald-500' : 'text-rose-500'}`}>{mikrotikResult.success ? `Connected · ${mikrotikResult.routers_count} profiles` : mikrotikResult.error}</span>}</div></form>}

    {['customers', 'payments', 'packages', 'audit'].includes(tab) && <DataTable rows={tabRows} columns={columns[tab]} empty={`No ${tab} found for this tenant.`}/>}
  </div>;
}
