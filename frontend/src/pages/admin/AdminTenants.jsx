import {
  Building2,
  CalendarClock,
  CheckCircle2,
  Clock3,
  Download,
  Edit,
  Eye,
  ExternalLink,
  LockKeyhole,
  MoreHorizontal,
  Plus,
  Power,
  Search,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import adminApi from '../../api/adminAxios';
import Modal from '../../components/Modal';

const emptyForm = {
  business_name: '',
  owner_name: '',
  email: '',
  phone: '',
  password: '',
  mikrotik_host: '',
  mikrotik_user: '',
  mikrotik_pass: '',
  mikrotik_port: '8728',
  status: 'active',
  plan: 'basic',
};

const labels = {
  business_name: 'Business name',
  owner_name: 'Owner name',
  email: 'Email',
  phone: 'Phone',
  password: 'Tenant password',
  mikrotik_host: 'MikroTik host',
  mikrotik_user: 'MikroTik user',
  mikrotik_pass: 'MikroTik password',
  mikrotik_port: 'MikroTik port',
  status: 'Status',
  plan: 'Plan',
};

function formatDate(value) {
  return value ? new Date(value).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '-';
}

function formatKES(value) {
  return `KES ${Number(value || 0).toLocaleString()}`;
}

function getExpiryDays(tenant) {
  const explicit = tenant.subscription?.days_until_expiry;
  if (explicit !== undefined && explicit !== null) return Number(explicit);
  if (!tenant.subscription?.expires_at) return null;
  const diff = new Date(tenant.subscription.expires_at).getTime() - Date.now();
  return Math.ceil(diff / 86400000);
}

function getTenantRevenue(tenant) {
  return tenant.monthly_revenue ?? tenant.revenue ?? 0;
}

function getUserCount(tenant) {
  return tenant.users_count || tenant.customer_count || tenant.customers_count || tenant.total_users || tenant.users || 0;
}

function getOnlineCount(tenant) {
  return tenant.online_users || tenant.active_sessions || tenant.online_count || 0;
}

function getHealth(tenant) {
  if (tenant.status === 'suspended') return 'Critical';
  if (tenant.status === 'inactive') return 'Offline';
  if (tenant.status === 'pending_setup') return 'Warning';
  const days = getExpiryDays(tenant);
  if (days !== null && days < 0) return 'Critical';
  if (days !== null && days <= 7) return 'Warning';
  return tenant.health || 'Healthy';
}

function tenantInitials(name) {
  return String(name || 'Tenant').split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase();
}

function StatCard({ label, value, note, icon: Icon, tone = 'blue' }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-[0_10px_30px_rgba(15,34,64,0.05)]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="theme-muted text-xs font-medium">{label}</p>
          <p className="theme-text mt-1 text-2xl font-semibold leading-none tracking-tight">{value}</p>
        </div>
        <div className="admin-accent-icon flex h-11 w-11 shrink-0 items-center justify-center rounded-full">
          <Icon size={21} />
        </div>
      </div>
      <p className={`mt-3 text-xs font-normal ${tone === 'rose' ? 'text-rose-600' : tone === 'amber' || tone === 'orange' ? 'text-orange-600' : 'text-emerald-600'}`}>{note}</p>
    </section>
  );
}

function StatusFilterButton({ active, children, dot, onClick }) {
  return (
    <button
      type="button"
      className={`inline-flex h-8 items-center gap-2 rounded-md border px-3 text-xs font-medium transition ${
        active ? 'admin-selected-option' : 'admin-option hover:border-blue-200'
      }`}
      onClick={onClick}
    >
      {dot && <span className={`h-2 w-2 rounded-full ${dot}`} />}
      {children}
    </button>
  );
}

function HealthBadge({ value }) {
  const normalized = String(value || 'Healthy').toLowerCase();
  const tone = normalized === 'critical' ? 'bg-rose-500' : normalized === 'warning' ? 'bg-amber-500' : normalized === 'offline' ? 'bg-slate-400' : 'bg-emerald-500';
  return (
    <span className="theme-text inline-flex items-center gap-2 text-xs font-medium">
      <span className={`h-2.5 w-2.5 rounded-full ${tone}`} />
      {value}
    </span>
  );
}

function TenantAvatar({ tenant, index }) {
  return (
    <div className="admin-primary flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold">
      {tenant.logo ? <img src={tenant.logo} alt="" className="h-full w-full rounded-full object-cover" /> : tenantInitials(tenant.business_name)}
    </div>
  );
}

function Field({ name, value, error, onChange, type = 'text', placeholder = '' }) {
  return (
    <div>
      <label className="form-label" htmlFor={name}>{labels[name]}</label>
      <input id={name} name={name} type={type} className="form-input" value={value} onChange={onChange} placeholder={placeholder} />
      {error && <p className="form-error">{error}</p>}
    </div>
  );
}

export default function AdminTenants() {
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [updatingId, setUpdatingId] = useState(null);
  const [modalMode, setModalMode] = useState(null);
  const [editingTenant, setEditingTenant] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [errors, setErrors] = useState({});
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sortOrder, setSortOrder] = useState('newest');
  const [page, setPage] = useState(1);
  const [openActionId, setOpenActionId] = useState(null);
  const [subscriptionModalTenant, setSubscriptionModalTenant] = useState(null);
  const [subscriptionDate, setSubscriptionDate] = useState('');
  const [subscriptionSaving, setSubscriptionSaving] = useState(false);
  const [viewTenant, setViewTenant] = useState(null);
  const [viewTab, setViewTab] = useState('overview');
  const [viewData, setViewData] = useState(null);
  const [viewLoading, setViewLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const { data } = await adminApi.get('/admin/tenants');
      setTenants(Array.isArray(data) ? data : []);
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to load tenants');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const stats = useMemo(() => ({
    total: tenants.length,
    active: tenants.filter((tenant) => tenant.status === 'active').length,
    pending: tenants.filter((tenant) => tenant.status === 'pending_setup').length,
    suspended: tenants.filter((tenant) => tenant.status === 'suspended').length,
    expiring: tenants.filter((tenant) => {
      const days = getExpiryDays(tenant);
      return days !== null && days >= 0 && days <= 7;
    }).length,
  }), [tenants]);

  const openCreate = () => {
    setModalMode('create');
    setEditingTenant(null);
    setForm(emptyForm);
    setErrors({});
  };

  const openEdit = (tenant) => {
    setModalMode('edit');
    setEditingTenant(tenant);
    setForm({
      ...emptyForm,
      business_name: tenant.business_name || '',
      owner_name: tenant.owner_name || '',
      email: tenant.email || '',
      phone: tenant.phone || '',
      password: '',
      mikrotik_host: tenant.mikrotik_host || '',
      mikrotik_user: tenant.mikrotik_user || '',
      mikrotik_pass: '',
      mikrotik_port: String(tenant.mikrotik_port || 8728),
      status: tenant.status || 'active',
      plan: tenant.subscription?.plan || 'basic',
    });
    setErrors({});
  };

  const closeModal = () => {
    if (saving) return;
    setModalMode(null);
    setEditingTenant(null);
    setForm(emptyForm);
    setErrors({});
  };

  const update = (event) => {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }));
    setErrors((current) => ({ ...current, [event.target.name]: '' }));
  };

  const validate = () => {
    const nextErrors = {};
    const createRequired = Object.keys(emptyForm).filter((field) => !['status', 'plan'].includes(field));
    const editRequired = ['business_name', 'owner_name', 'email', 'phone'];
    const required = modalMode === 'create' ? createRequired : editRequired;

    required.forEach((field) => {
      if (!String(form[field] || '').trim()) nextErrors[field] = `${labels[field]} is required`;
    });

    if (modalMode === 'create' && form.password.length < 6) {
      nextErrors.password = 'Password must be at least 6 characters';
    }

    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const saveTenant = async (event) => {
    event.preventDefault();
    if (!validate()) return;

    setSaving(true);
    try {
      const payload = {
        ...form,
        mikrotik_port: Number(form.mikrotik_port || 8728),
      };

      if (modalMode === 'edit') {
        delete payload.password;
        ['mikrotik_host', 'mikrotik_user', 'mikrotik_pass', 'mikrotik_port'].forEach((field) => delete payload[field]);
        await adminApi.patch(`/admin/tenants/${editingTenant.id}`, payload);
        toast.success('Tenant updated');
      } else {
        await adminApi.post('/admin/tenants', payload);
        toast.success('Tenant created');
      }

      closeModal();
      await load();
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to save tenant');
    } finally {
      setSaving(false);
    }
  };

  const deleteTenant = async (tenant) => {
    setOpenActionId(null);
    if (!window.confirm(`Permanently delete ${tenant.business_name || 'this tenant'} and its customer, payment, and subscription records? This cannot be undone.`)) return;
    setUpdatingId(tenant.id);
    try {
      await adminApi.delete(`/admin/tenants/${tenant.id}`);
      toast.success('Tenant and its data deleted');
      await load();
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to delete tenant');
    } finally {
      setUpdatingId(null);
    }
  };

  const openTenantView = async (tenant) => {
    setOpenActionId(null);
    setViewTenant(tenant);
    setViewTab('overview');
    setViewData(null);
    setViewLoading(true);
    try {
      const { data } = await adminApi.get(`/admin/tenants/${encodeURIComponent(tenant.id)}/overview`);
      setViewData(data);
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to load tenant overview');
    } finally {
      setViewLoading(false);
    }
  };

  const closeTenantView = () => {
    setViewTenant(null);
    setViewData(null);
    setViewTab('overview');
  };

  const setStatus = async (tenant, status) => {
    setOpenActionId(null);
    setUpdatingId(tenant.id);
    try {
      if (status === 'suspended') {
        await adminApi.patch(`/admin/tenants/${tenant.id}`, { status: 'suspended' });
      } else {
        await adminApi.patch(`/admin/tenants/${tenant.id}`, { status });
      }
      toast.success(status === 'suspended' ? 'Tenant suspended' : 'Tenant activated');
      await load();
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to update tenant');
    } finally {
      setUpdatingId(null);
    }
  };

  const filteredTenants = useMemo(() => {
    return tenants.filter((tenant) => {
      const text = `${tenant.business_name || ''} ${tenant.owner_name || ''} ${tenant.email || ''} ${tenant.domain || ''}`.toLowerCase();
      if (!text.includes(query.toLowerCase())) return false;
      if (statusFilter === 'all') return true;
      if (statusFilter === 'expiring') return tenant.subscription && Number(tenant.subscription.days_until_expiry) <= 7 && Number(tenant.subscription.days_until_expiry) >= 0;
      return tenant.status === statusFilter;
    }).sort((a, b) => {
      if (sortOrder === 'oldest') return new Date(a.created_at || 0) - new Date(b.created_at || 0);
      if (sortOrder === 'name') return String(a.business_name || '').localeCompare(String(b.business_name || ''));
      return new Date(b.created_at || b.updated_at || 0) - new Date(a.created_at || a.updated_at || 0);
    });
  }, [tenants, query, statusFilter, sortOrder]);

  const pageSize = 10;
  const pagedTenants = filteredTenants.slice((page - 1) * pageSize, page * pageSize);
  const totalPages = Math.max(1, Math.ceil(filteredTenants.length / pageSize));

  const extendTenant = async (tenant) => {
    const current = tenant.subscription?.expires_at ? new Date(tenant.subscription.expires_at) : new Date();
    setSubscriptionModalTenant(tenant);
    setSubscriptionDate(current.toISOString().slice(0, 10));
    setOpenActionId(null);
  };

  const closeSubscriptionModal = () => {
    if (subscriptionSaving) return;
    setSubscriptionModalTenant(null);
    setSubscriptionDate('');
  };

  const saveSubscriptionDate = async (event) => {
    event.preventDefault();
    if (!subscriptionModalTenant || !subscriptionDate) return;
    setSubscriptionSaving(true);
    try {
      const expiresAt = new Date(`${subscriptionDate}T23:59:59`);
      await adminApi.patch(`/admin/tenants/${subscriptionModalTenant.id}/subscription`, { expires_at: expiresAt.toISOString() });
      toast.success('Subscription date updated');
      setSubscriptionModalTenant(null);
      setSubscriptionDate('');
      await load();
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to update subscription');
    } finally {
      setSubscriptionSaving(false);
    }
  };

  const exportCsv = () => {
    const columns = [
      ['Business', 'business_name'], ['Owner', 'owner_name'], ['Email', 'email'], ['Phone', 'phone'],
      ['Status', 'status'], ['Plan', 'plan'], ['Created', 'created_at'], ['Subscription expiry', 'expires_at'],
    ];
    const cell = (value) => {
      let text = String(value ?? '');
      if (/^[=+\-@]/.test(text)) text = `'${text}`;
      return `"${text.replaceAll('"', '""')}"`;
    };
    const rows = filteredTenants.map((tenant) => [
      tenant.business_name, tenant.owner_name, tenant.email, tenant.phone, tenant.status,
      tenant.subscription?.plan, tenant.created_at, tenant.subscription?.expires_at,
    ]);
    const csv = [columns.map(([label]) => cell(label)).join(','), ...rows.map((row) => row.map(cell).join(','))].join('\r\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'expressnet-tenants.csv';
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="admin-accent-label text-[10px] font-bold uppercase tracking-[0.18em]">Organizations</p>
          <h2 className="admin-heading mt-1 text-2xl font-bold tracking-tight">Tenant directory</h2>
          <p className="admin-muted mt-1 text-sm">Review subscriptions, onboarding, and account health across the platform.</p>
        </div>
        <button className="admin-primary inline-flex h-11 items-center gap-2 rounded-xl px-4 text-xs font-semibold shadow-lg shadow-slate-900/10 transition hover:brightness-90" type="button" onClick={openCreate}>
          <Plus size={16} />
          Create Tenant
        </button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard label="Total tenants" value={stats.total.toLocaleString()} note="Registered organizations" icon={Building2} />
        <StatCard label="Active Tenants" value={stats.active.toLocaleString()} note={`${stats.total ? ((stats.active / stats.total) * 100).toFixed(1) : '0.0'}% of total`} icon={CheckCircle2} tone="green" />
        <StatCard label="Pending Setup" value={stats.pending.toLocaleString()} note="Requires onboarding" icon={Clock3} tone="amber" />
        <StatCard label="Suspended" value={stats.suspended.toLocaleString()} note={`${stats.total ? ((stats.suspended / stats.total) * 100).toFixed(1) : '0.0'}% of total`} icon={LockKeyhole} tone="rose" />
        <StatCard label="Expiring Soon" value={stats.expiring.toLocaleString()} note="Within 7 days" icon={CalendarClock} tone="orange" />
      </div>

      <section className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-[0_16px_48px_rgba(15,23,42,0.06)]">
        <div className="flex flex-col gap-4 border-b border-slate-100 p-4 xl:flex-row xl:items-center xl:justify-between">
          <label className="relative block w-full xl:max-w-[390px]">
            <Search size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-blue-500" />
            <input className="form-input h-8 pl-10" placeholder="Search tenants, owner, email or domain..." value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={exportCsv} className="admin-accent-button inline-flex h-9 items-center gap-2 rounded-lg border bg-white px-3 text-xs font-semibold transition hover:border-slate-300 hover:bg-slate-50">
              <Download size={15} />
              Export {filteredTenants.length} rows
            </button>
          </div>
        </div>

        <div className="flex flex-col gap-4 border-b border-slate-100 p-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex flex-wrap items-center gap-3">
            <span className="theme-muted text-xs font-medium">Status:</span>
            <StatusFilterButton active={statusFilter === 'all'} onClick={() => { setStatusFilter('all'); setPage(1); }}>All Status</StatusFilterButton>
            <StatusFilterButton active={statusFilter === 'active'} dot="bg-emerald-500" onClick={() => { setStatusFilter('active'); setPage(1); }}>Active</StatusFilterButton>
            <StatusFilterButton active={statusFilter === 'pending_setup'} dot="bg-amber-500" onClick={() => { setStatusFilter('pending_setup'); setPage(1); }}>Pending Setup</StatusFilterButton>
            <StatusFilterButton active={statusFilter === 'suspended'} dot="bg-rose-500" onClick={() => { setStatusFilter('suspended'); setPage(1); }}>Suspended</StatusFilterButton>
            <StatusFilterButton active={statusFilter === 'expiring'} dot="bg-orange-500" onClick={() => { setStatusFilter('expiring'); setPage(1); }}>Expiring Soon</StatusFilterButton>
            <StatusFilterButton active={statusFilter === 'inactive'} dot="bg-slate-400" onClick={() => { setStatusFilter('inactive'); setPage(1); }}>Offline</StatusFilterButton>
          </div>
          <div className="flex items-center gap-2">
            <label htmlFor="tenant-sort" className="admin-muted text-xs font-medium">Sort</label>
            <select id="tenant-sort" className="admin-input h-9 rounded-lg border px-3 text-xs font-semibold outline-none focus:ring-4" value={sortOrder} onChange={(event) => { setSortOrder(event.target.value); setPage(1); }}>
              <option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="name">Business name</option>
            </select>
          </div>
        </div>

        <div className="overflow-x-auto">
        <table className="w-full min-w-[1120px] text-left">
          <thead className="table-head">
            <tr>
              <th className="px-4 py-4">Tenant</th>
              <th className="px-4 py-3">Owner</th>
              <th className="px-4 py-3">Users</th>
              <th className="px-4 py-3">Revenue (This Month)</th>
              <th className="px-4 py-3">Health</th>
              <th className="px-4 py-3">Subscription Expires</th>
              <th className="px-4 py-3">Created</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {loading ? (
              <tr><td className="px-4 py-6 text-xs text-slate-500" colSpan="8">Loading tenants...</td></tr>
            ) : pagedTenants.length === 0 ? (
              <tr><td className="px-4 py-6 text-xs text-slate-500" colSpan="8">No tenants found.</td></tr>
            ) : pagedTenants.map((tenant, index) => {
              const days = getExpiryDays(tenant);
              const health = getHealth(tenant);
              const revenue = getTenantRevenue(tenant);
              return (
              <tr key={tenant.id} className="hover:bg-slate-50/70">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-3">
                    <TenantAvatar tenant={tenant} index={index} />
                    <div className="min-w-0">
                      <p className="theme-text truncate text-xs font-medium uppercase">{tenant.business_name || '-'}</p>
                      <a className="inline-flex max-w-[190px] items-center gap-1 truncate text-[11px] font-semibold text-blue-500 hover:text-blue-700" href={`/portal/${tenant.id}`} target="_blank" rel="noreferrer">
                        {tenant.domain || `${String(tenant.business_name || 'tenant').toLowerCase().replace(/\s+/g, '')}.expressnet.com`}
                        <ExternalLink size={11} />
                      </a>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <p className="theme-text text-xs font-medium">{tenant.owner_name || '-'}</p>
                  <p className="theme-muted text-[11px] font-normal">{tenant.email || tenant.phone || '-'}</p>
                </td>
                <td className="px-4 py-3">
                  <p className="theme-text text-xs font-semibold">{Number(getUserCount(tenant)).toLocaleString()}</p>
                  <p className="text-[11px] font-normal text-emerald-600">{Number(getOnlineCount(tenant)).toLocaleString()} online</p>
                </td>
                <td className="px-4 py-3">
                  <p className="theme-text text-xs font-semibold">{formatKES(revenue)}</p>
                  <p className={`text-[11px] font-normal ${revenue > 0 ? 'text-emerald-600' : 'text-slate-400'}`}>{revenue > 0 ? 'Revenue recorded' : 'No revenue recorded'}</p>
                </td>
                <td className="px-4 py-3"><HealthBadge value={health} /></td>
                <td className="px-4 py-3">
                  <p className="theme-text text-xs font-semibold">{formatDate(tenant.subscription?.expires_at)}</p>
                  <p className={`text-[11px] font-normal ${days !== null && days <= 7 ? 'text-orange-600' : 'text-blue-600'}`}>{days === null ? '-' : days < 0 ? 'Expired' : `${days} days left`}</p>
                </td>
                <td className="theme-text px-4 py-3 text-xs font-medium">{formatDate(tenant.created_at)}</td>
                <td className="px-4 py-3">
                  <div className="relative inline-flex">
                      <button
                      className="admin-accent-button flex h-9 w-9 items-center justify-center rounded-lg border transition hover:bg-slate-50"
                      type="button"
                      onClick={() => setOpenActionId((current) => (current === tenant.id ? null : tenant.id))}
                      disabled={updatingId === tenant.id}
                      aria-expanded={openActionId === tenant.id}
                      aria-haspopup="menu"
                      aria-label={`Open actions for ${tenant.business_name || 'tenant'}`}
                    >
                      <MoreHorizontal size={15} />
                    </button>
                    {openActionId === tenant.id && (
                      <div className="theme-card absolute right-0 top-10 z-20 w-48 overflow-hidden rounded-md border py-1 text-xs font-medium shadow-[0_18px_40px_rgba(15,34,64,0.16)]" role="menu">
                        <button className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-slate-50" type="button" onClick={() => openTenantView(tenant)} role="menuitem"><Eye size={14} />View tenant</button>
                        <button className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-slate-50" type="button" onClick={() => { setOpenActionId(null); openEdit(tenant); }} role="menuitem">
                          <Edit size={14} />
                          Edit tenant
                        </button>
                        <button className="flex w-full items-center gap-2 px-3 py-2 text-left text-blue-600 hover:bg-blue-50" type="button" onClick={() => extendTenant(tenant)} role="menuitem">
                          <CalendarClock size={14} />
                          Set subscription date
                        </button>
                        {tenant.status !== 'active' ? (
                          <button className="flex w-full items-center gap-2 px-3 py-2 text-left text-emerald-600 hover:bg-emerald-50" type="button" onClick={() => setStatus(tenant, 'active')} role="menuitem">
                            <ShieldCheck size={14} />
                            Activate tenant
                          </button>
                        ) : (
                          <button className="flex w-full items-center gap-2 px-3 py-2 text-left text-rose-600 hover:bg-rose-50" type="button" onClick={() => setStatus(tenant, 'suspended')} role="menuitem">
                            <Power size={14} />
                            Suspend tenant
                          </button>
                        )}
                        <button className="flex w-full items-center gap-2 border-t border-slate-200 px-3 py-2 text-left text-rose-600 hover:bg-rose-50" type="button" onClick={() => deleteTenant(tenant)} role="menuitem"><Trash2 size={14} />Delete tenant</button>
                      </div>
                    )}
                  </div>
                </td>
              </tr>);
            })}
          </tbody>
        </table>
        </div>
        <div className="flex flex-col gap-3 border-t border-slate-100 px-4 py-3 text-xs text-slate-500 sm:flex-row sm:items-center sm:justify-between">
          <span className="font-semibold">Showing {filteredTenants.length === 0 ? 0 : ((page - 1) * pageSize) + 1} to {Math.min(page * pageSize, filteredTenants.length)} of {filteredTenants.length} tenants</span>
          <div className="flex items-center gap-1">
            <button className="h-8 rounded-md border border-slate-200 px-3 text-xs font-medium disabled:opacity-50" disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>Previous</button>
            {Array.from({ length: Math.min(totalPages, 5) }, (_, item) => item + 1).map((item) => (
              <button key={item} className={`h-8 w-8 rounded-md text-xs font-medium ${page === item ? 'bg-app-accent text-white' : 'border border-slate-200 text-slate-700'}`} onClick={() => setPage(item)}>{item}</button>
            ))}
            {totalPages > 6 && <span className="px-2 text-slate-400">...</span>}
            {totalPages > 5 && <button className={`h-8 w-8 rounded-md text-xs font-medium ${page === totalPages ? 'bg-app-accent text-white' : 'border border-slate-200 text-slate-700'}`} onClick={() => setPage(totalPages)}>{totalPages}</button>}
            <button className="h-8 rounded-md border border-slate-200 px-3 text-xs font-medium text-app-accent disabled:opacity-50" disabled={page >= totalPages} onClick={() => setPage((current) => Math.min(totalPages, current + 1))}>Next</button>
          </div>
        </div>
      </section>

      {modalMode && (
        <Modal title={modalMode === 'create' ? 'Create Tenant' : `Edit ${editingTenant?.business_name || 'Tenant'}`} onClose={closeModal}>
          <form className="space-y-5" onSubmit={saveTenant}>
            <section>
              <h2 className="theme-text mb-3 text-sm font-semibold tracking-tight">Business Info</h2>
              <div className="grid gap-4 md:grid-cols-2">
                <Field name="business_name" value={form.business_name} error={errors.business_name} onChange={update} />
                <Field name="owner_name" value={form.owner_name} error={errors.owner_name} onChange={update} />
                <Field name="email" type="email" value={form.email} error={errors.email} onChange={update} />
                <Field name="phone" value={form.phone} error={errors.phone} onChange={update} />
                {modalMode === 'create' && <Field name="password" type="password" value={form.password} error={errors.password} onChange={update} />}
                {modalMode === 'edit' && (
                  <div>
                    <label className="form-label" htmlFor="status">Status</label>
                    <select id="status" name="status" className="form-input" value={form.status} onChange={update}>
                      <option value="active">active</option>
                      <option value="pending_setup">pending_setup</option>
                      <option value="suspended">suspended</option>
                      <option value="inactive">inactive</option>
                    </select>
                  </div>
                )}
                <div>
                  <label className="form-label" htmlFor="plan">Plan</label>
                  <select id="plan" name="plan" className="form-input" value={form.plan} onChange={update}>
                    <option value="basic">Basic</option>
                    <option value="pro">Pro</option>
                    <option value="enterprise">Enterprise</option>
                  </select>
                </div>
              </div>
            </section>

            {modalMode === 'create' && <section>
              <h2 className="theme-text mb-3 text-sm font-semibold tracking-tight">MikroTik</h2>
              <div className="grid gap-4 md:grid-cols-2">
                <Field name="mikrotik_host" value={form.mikrotik_host} error={errors.mikrotik_host} onChange={update} />
                <Field name="mikrotik_user" value={form.mikrotik_user} error={errors.mikrotik_user} onChange={update} />
                <Field name="mikrotik_pass" type="password" value={form.mikrotik_pass} error={errors.mikrotik_pass} onChange={update} placeholder={modalMode === 'edit' ? 'Leave blank to keep existing' : ''} />
                <Field name="mikrotik_port" type="number" value={form.mikrotik_port} error={errors.mikrotik_port} onChange={update} />
              </div>
            </section>}

            <div className="flex justify-end gap-3 border-t border-slate-200 pt-4">
              <button type="button" className="btn-secondary" onClick={closeModal}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={saving}>
                {saving ? 'Saving...' : modalMode === 'create' ? 'Create Tenant' : 'Update Tenant'}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {subscriptionModalTenant && (
        <Modal title={`Subscription for ${subscriptionModalTenant.business_name || 'Tenant'}`} onClose={closeSubscriptionModal}>
          <form className="space-y-5" onSubmit={saveSubscriptionDate}>
            <div>
              <label className="form-label" htmlFor="subscription_expires_at">Subscription expiry date</label>
              <input
                id="subscription_expires_at"
                type="date"
                className="form-input"
                value={subscriptionDate}
                onChange={(event) => setSubscriptionDate(event.target.value)}
                autoFocus
              />
            </div>
            <div className="flex justify-end gap-3 border-t border-slate-200 pt-4">
              <button type="button" className="btn-secondary" onClick={closeSubscriptionModal}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={subscriptionSaving || !subscriptionDate}>
                {subscriptionSaving ? 'Saving...' : 'Save date'}
              </button>
            </div>
          </form>
        </Modal>
      )}

      {viewTenant && (
        <Modal title={viewTenant.business_name || 'Tenant overview'} onClose={closeTenantView}>
          <div className="space-y-5">
            <div className="flex gap-2 border-b border-slate-200 pb-3 dark:border-slate-700">
              {['overview', 'network'].map((tab) => <button key={tab} type="button" onClick={() => setViewTab(tab)} className={`rounded-lg px-3 py-2 text-xs font-semibold capitalize transition ${viewTab === tab ? 'bg-app-accent text-white' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'}`}>{tab}</button>)}
            </div>
            {viewLoading ? <div className="space-y-3"><div className="h-24 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800"/><div className="h-52 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800"/></div> : viewTab === 'overview' ? <div className="space-y-5">
              <div className="grid gap-3 sm:grid-cols-2">
                <section className="theme-card rounded-xl border p-4"><p className="theme-muted text-[10px] font-semibold uppercase">Routers</p><p className="theme-text mt-2 text-2xl font-bold">{Number(viewData?.routerCount || 0).toLocaleString()}</p><p className="theme-muted mt-1 text-[10px]">Registered in the tenant network</p></section>
                <section className="theme-card rounded-xl border p-4"><p className="theme-muted text-[10px] font-semibold uppercase">Active sessions</p><p className="theme-text mt-2 text-2xl font-bold">{Number(viewData?.activeSessions || 0).toLocaleString()}</p><p className="theme-muted mt-1 text-[10px]">Latest available router snapshot and RADIUS accounting</p></section>
                <section className="theme-card rounded-xl border p-4"><p className="theme-muted text-[10px] font-semibold uppercase">Current day earnings</p><p className="theme-text mt-2 text-xl font-bold">{formatKES(viewData?.revenueToday)}</p><p className="theme-muted mt-1 text-[10px]">Successful customer payments today</p></section>
                <section className="theme-card rounded-xl border p-4"><p className="theme-muted text-[10px] font-semibold uppercase">Current month earnings</p><p className="theme-text mt-2 text-xl font-bold">{formatKES(viewData?.revenueThisMonth)}</p><p className="theme-muted mt-1 text-[10px]">Successful customer payments · {viewData?.systemFeePeriod || ''}</p></section>
                <section className="rounded-xl border border-[var(--app-accent)]/30 bg-app-accent/5 p-4 sm:col-span-2"><p className="text-[10px] font-semibold uppercase text-app-accent">Current month system fee due</p><p className="mt-2 text-2xl font-bold text-app-accent">{viewData?.systemFeeCurrency || 'KES'} {Number(viewData?.systemFeeDue || 0).toLocaleString()}</p><p className="mt-1 text-[10px] text-slate-500">Based on {viewData?.systemFeePercent ?? 0}% of {viewData?.systemFeeCurrency || 'KES'} {Number(viewData?.systemFeeSalesBasis || 0).toLocaleString()} in successful sales</p></section>
                <section className="theme-card rounded-xl border p-4"><p className="theme-muted text-[10px] font-semibold uppercase">PPPoE customers</p><p className="theme-text mt-2 text-xl font-bold">{Number(viewData?.pppoeCustomers || 0).toLocaleString()}</p></section>
                <section className="theme-card rounded-xl border p-4"><p className="theme-muted text-[10px] font-semibold uppercase">Hotspot users</p><p className="theme-text mt-2 text-xl font-bold">{Number(viewData?.hotspotUsers || 0).toLocaleString()}</p></section>
              </div>
              <section className="theme-card rounded-xl border p-4"><div className="mb-4 flex items-start justify-between"><div><h3 className="theme-text text-xs font-bold">Six month earnings</h3><p className="theme-muted mt-1 text-[10px]">Successful customer payments</p></div><span className="theme-muted text-[10px]">KES</span></div><div className="grid h-36 grid-cols-6 items-end gap-2">{(viewData?.revenueByMonth || []).map((month) => { const max = Math.max(1, ...(viewData?.revenueByMonth || []).map((entry) => Number(entry.amount || 0))); const height = Math.max(4, Number(month.amount || 0) / max * 100); return <div key={month.month} className="flex h-full min-w-0 flex-col items-center justify-end gap-1"><span className="theme-muted truncate text-[8px]">{Number(month.amount || 0).toLocaleString()}</span><div className="w-full max-w-10 rounded-t-md bg-app-accent" style={{ height: `${height}%` }}/><span className="theme-muted text-[9px]">{month.month?.slice(5)}</span></div>; })}</div></section>
            </div> : <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2"><section className="theme-card rounded-xl border p-4"><p className="theme-muted text-[10px] font-semibold uppercase">Network status</p><p className="theme-text mt-2 text-lg font-bold capitalize">{viewData?.network?.status || 'unknown'}</p><p className="theme-muted mt-1 text-[10px]">{viewData?.network?.provisioningStatus || viewData?.network?.sessionSource || ''}</p></section><section className="theme-card rounded-xl border p-4"><p className="theme-muted text-[10px] font-semibold uppercase">Active sessions</p><p className="theme-text mt-2 text-lg font-bold">{Number(viewData?.network?.activeSessions || 0).toLocaleString()}</p><p className="theme-muted mt-1 text-[10px]">{viewData?.network?.sessionSource || 'No active session records'}</p></section></div>
              <section className="theme-card rounded-xl border p-4"><div className="mb-3"><h3 className="theme-text text-xs font-bold">Tenant network configuration</h3><p className="theme-muted mt-1 text-[10px]">Read from the tenant’s saved account network settings.</p></div><div className="grid gap-3 sm:grid-cols-3"><div><p className="theme-muted text-[10px]">Primary host</p><p className="theme-text mt-1 break-all text-xs font-semibold">{viewData?.network?.host || 'Not configured'}</p></div><div><p className="theme-muted text-[10px]">Router user</p><p className="theme-text mt-1 text-xs font-semibold">{viewData?.network?.username || '—'}</p></div><div><p className="theme-muted text-[10px]">API port</p><p className="theme-text mt-1 text-xs font-semibold">{viewData?.network?.port || '—'}</p></div></div><p className="theme-muted mt-3 text-[10px]">RADIUS accounting: {viewData?.network?.radiusEnabled ? 'Enabled' : 'Not enabled'}{viewData?.network?.lastSeenAt ? ` · Last router contact ${new Date(viewData.network.lastSeenAt).toLocaleString()}` : ''}</p></section>
              <section className="theme-card rounded-xl border p-4"><h3 className="theme-text mb-3 text-xs font-bold">Registered routers ({viewData?.network?.routers?.length || 0})</h3>{viewData?.network?.routers?.length ? <div className="space-y-2">{viewData.network.routers.map((router) => <div key={router.id} className="grid gap-2 rounded-lg border border-slate-200 p-3 sm:grid-cols-4 dark:border-slate-700"><div><p className="theme-muted text-[9px] uppercase">Name</p><p className="theme-text mt-1 text-xs font-semibold">{router.name || 'Router'}</p></div><div><p className="theme-muted text-[9px] uppercase">Host</p><p className="theme-text mt-1 break-all text-xs">{router.host || '—'}</p></div><div><p className="theme-muted text-[9px] uppercase">Model</p><p className="theme-text mt-1 text-xs">{router.model || '—'}</p></div><div><p className="theme-muted text-[9px] uppercase">Status · Port</p><p className="theme-text mt-1 text-xs capitalize">{router.status || 'configured'} · {router.port || '—'}</p></div></div>)}</div> : <p className="theme-muted text-xs">No router records are linked to this tenant account.</p>}</section>
            </div>}
          </div>
        </Modal>
      )}
    </div>
  );
}
