import {
  AlertTriangle,
  ArrowRight,
  BellRing,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  Database,
  Radio,
  Search,
  Server,
  TrendingUp,
  Users,
  WalletCards,
  Wifi,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import { Link } from 'react-router-dom';
import adminApi from '../../api/adminAxios';
import { adminPath } from '../../config/adminPaths';

function formatKES(value) {
  return `KES ${Number(value || 0).toLocaleString()}`;
}

function formatCompactKES(value) {
  const numeric = Number(value || 0);
  if (numeric >= 1000000) return `KES ${(numeric / 1000000).toFixed(2)}M`;
  return formatKES(numeric);
}

function formatDate(value) {
  return value ? new Date(value).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '-';
}

function formatDateShort(value) {
  return value ? new Date(value).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '-';
}

function formatDateTime(value) {
  return value ? new Date(value).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '-';
}

function formatMonthRange() {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), 1);
  const end = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  return `${formatDateShort(start)} - ${formatDate(end)}`;
}

function getTenantRevenue(tenant) {
  return tenant.subscription?.amount || tenant.subscription?.price || tenant.monthly_revenue || tenant.revenue || 0;
}

function getUserCount(tenant) {
  return tenant.users_count || tenant.customer_count || tenant.customers_count || tenant.total_users || tenant.users || 0;
}

function getOnlineCount(tenant) {
  return tenant.online_users || tenant.active_sessions || tenant.online_count || 0;
}

function tenantInitials(name) {
  return String(name || 'Tenant').split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase();
}

function Panel({ title, action, children, className = '' }) {
  return (
    <section className={`theme-card overflow-hidden rounded-lg border shadow-sm ${className}`}>
      <div className="flex items-center justify-between px-5 py-4">
        <h2 className="theme-text text-sm font-semibold tracking-tight">{title}</h2>
        {action && <Link to={action.to} className="text-xs font-medium text-app-accent">{action.label}</Link>}
      </div>
      {children}
    </section>
  );
}

function Sparkline({ color = '#2563eb', fill = '#dbeafe', points }) {
  if (!Array.isArray(points) || points.length < 2) return null;
  const max = Math.max(...points, 1);
  const min = Math.min(...points, 0);
  const width = 170;
  const height = 44;
  const coords = points.map((point, index) => {
    const x = (index / (points.length - 1)) * width;
    const y = height - ((point - min) / Math.max(max - min, 1)) * 32 - 6;
    return `${x},${y}`;
  });
  const area = `0,${height} ${coords.join(' ')} ${width},${height}`;

  return (
    <svg className="mt-4 h-11 w-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      <polygon points={area} fill={fill} opacity="0.55" />
      <polyline points={coords.join(' ')} fill="none" stroke={color} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      {coords.map((coord, index) => {
        const [cx, cy] = coord.split(',');
        return <circle key={`${coord}-${index}`} cx={cx} cy={cy} r="1.5" fill={color} />;
      })}
    </svg>
  );
}

function MetricCard({ label, value, helper, icon: Icon, tone = 'blue', spark }) {
  const tones = {
    blue: ['bg-blue-100 text-blue-600', '#2563eb', '#dbeafe'],
    green: ['bg-emerald-100 text-emerald-600', '#16a34a', '#dcfce7'],
    purple: ['bg-violet-100 text-violet-600', '#7c3aed', '#ede9fe'],
    cyan: ['bg-cyan-100 text-cyan-600', '#06b6d4', '#cffafe'],
    orange: ['bg-orange-100 text-orange-600', '#f97316', '#ffedd5'],
    rose: ['bg-rose-100 text-rose-600', '#e11d48', '#ffe4e6'],
  };
  const [iconTone, line, fill] = tones[tone];

  return (
    <section className="theme-card rounded-lg border p-3.5 shadow-sm">
      <div className="flex items-start gap-4">
        <div className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md ${iconTone}`}>
          <Icon size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="theme-muted text-xs font-medium">{label}</p>
          <p className="theme-text mt-1 text-2xl font-semibold leading-none tracking-tight">{value}</p>
          {helper && <p className="theme-muted mt-2 text-xs font-normal">{helper}</p>}
        </div>
      </div>
      <Sparkline color={line} fill={fill} points={spark} />
    </section>
  );
}

function TenantAvatar({ tenant, index }) {
  const colors = ['bg-blue-600', 'bg-orange-500', 'bg-cyan-500', 'bg-violet-600', 'bg-sky-500', 'bg-red-500'];
  return (
    <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white ${colors[index % colors.length]}`}>
      {tenantInitials(tenant.business_name)}
    </div>
  );
}

function RevenueTrend({ chart }) {
  const rows = Array.isArray(chart) ? chart : [];
  const amounts = rows.map((item) => Number(item.amount || 0));
  const max = Math.max(...amounts, 1);
  const toPoints = (series) => series.map((value, index) => `${(index / Math.max(series.length - 1, 1)) * 620},${190 - (value / max) * 160}`).join(' ');
  const points = toPoints(amounts.length ? amounts : [0, 0]);

  return (
    <Panel title="Revenue Trend" className="xl:col-span-2">
      <div className="px-5 pb-5">
        <div className="relative h-[250px]">
          <div className="absolute inset-0 grid grid-rows-4 pl-1 text-xs font-medium text-blue-600">
            {['250K', '150K', '50K', '0'].map((label) => <div key={label} className="border-t border-slate-100 pt-0.5">{label}</div>)}
          </div>
          <svg className="absolute left-12 top-2 h-[210px] w-[calc(100%-4rem)]" viewBox="0 0 620 210" preserveAspectRatio="none">
            <defs>
              <linearGradient id="trafficBlue" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="#2563eb" stopOpacity="0.23" />
                <stop offset="100%" stopColor="#2563eb" stopOpacity="0.02" />
              </linearGradient>
              <linearGradient id="trafficGreen" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="#16a34a" stopOpacity="0.18" />
                <stop offset="100%" stopColor="#16a34a" stopOpacity="0.02" />
              </linearGradient>
            </defs>
            <polygon points={`0,210 ${points} 620,210`} fill="url(#trafficBlue)" />
            <polyline points={points} fill="none" stroke="#2563eb" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div className="absolute bottom-0 left-12 right-0 grid grid-cols-7 text-[11px] font-normal text-slate-500">
            {rows.filter((_, index) => index % Math.max(Math.floor(rows.length / 6), 1) === 0).slice(0, 7).map((item) => <span key={item.date}>{formatDateShort(item.date)}</span>)}
          </div>
        </div>
      </div>
    </Panel>
  );
}

function PlatformHealth({ health }) {
  const status = health?.status || 'unknown';
  const rows = [
    [Database, 'Database', health?.dbError || 'Primary database check', health?.db || 'unknown', health?.db === 'ok' ? 'green' : 'rose'],
    [Wifi, 'Redis', health?.redisError || 'Cache and queue broker check', health?.redis || 'unknown', health?.redis === 'ok' ? 'green' : 'rose'],
    [Server, 'Firebase', 'Realtime database configuration check', health?.firebase || 'unknown', health?.firebase === 'ok' ? 'green' : 'rose'],
  ];
  const iconTone = { green: 'bg-emerald-100 text-emerald-600', rose: 'bg-rose-100 text-rose-600' };

  return (
    <Panel title="Platform Health" action={{ to: adminPath('system'), label: 'View All' }}>
      <div className="divide-y divide-slate-100 px-5 pb-4">
        {rows.map(([Icon, label, detail, status, tone]) => (
          <div key={label} className="flex items-center gap-4 py-4">
            <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full ${iconTone[tone]}`}><Icon size={22} /></div>
            <div className="min-w-0 flex-1">
              <p className="theme-text text-xs font-medium">{label}</p>
              <p className="theme-muted text-xs font-normal">{detail}</p>
            </div>
            <span className={`rounded-md px-3 py-1 text-xs font-medium ${status === 'ok' ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'}`}>{status}</span>
          </div>
        ))}
      </div>
      <div className="theme-muted border-t border-slate-100 px-5 py-3 text-xs font-medium">
        <span className="inline-flex items-center gap-2"><CheckCircle2 size={15} className={status === 'healthy' ? 'text-emerald-600' : 'text-rose-600'} />System status: {status}</span>
      </div>
    </Panel>
  );
}

function SystemPerformance({ stats }) {
  const services = [
    ['Total tenants', Number(stats?.totalTenants || 0).toLocaleString()],
    ['Active tenants', Number(stats?.activeTenants || 0).toLocaleString()],
    ['Suspended tenants', Number(stats?.suspendedTenants || 0).toLocaleString()],
    ['Pending setup', Number(stats?.pendingTenants || 0).toLocaleString()],
    ['Expiring this week', Number(stats?.expiringThisWeek || 0).toLocaleString()],
    ['Expired subscriptions', Number(stats?.expiredCount || 0).toLocaleString()],
  ];
  return (
    <Panel title="Platform Summary" action={{ to: adminPath('system'), label: 'View All' }}>
      <div className="px-5 pb-5">
        <div className="space-y-2">
          {services.map(([label, value]) => (
            <div key={label} className="flex h-9 items-center gap-3 rounded-md border border-slate-200 px-3">
              <Server size={15} className="text-blue-600" />
              <span className="theme-muted flex-1 text-xs font-normal">{label}</span>
              <span className="theme-text text-xs font-semibold">{value}</span>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  );
}

function RecentTenants({ tenants }) {
  return (
    <Panel title="Recent Tenants" action={{ to: adminPath('tenants'), label: 'View All' }} className="xl:col-span-2">
      <div className="overflow-x-auto px-5 pb-4">
        <table className="w-full min-w-[650px] text-left">
          <thead className="table-head">
            <tr>{['Tenant', 'Plan', 'Users', 'Revenue (This Month)', 'Status', 'Joined On'].map((heading) => <th key={heading} className="px-1 py-3">{heading}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {tenants.length === 0 ? (
              <tr><td colSpan="6" className="py-6 text-xs text-slate-500">No tenants found.</td></tr>
            ) : tenants.map((tenant, index) => (
              <tr key={tenant.id}>
                <td className="py-3">
                  <div className="flex items-center gap-3"><TenantAvatar tenant={tenant} index={index} /><span className="theme-text text-xs font-medium uppercase">{tenant.business_name || tenant.owner_name || '-'}</span></div>
                </td>
                <td className="theme-text text-xs font-medium">{tenant.subscription?.plan || '-'}</td>
                <td className="theme-text text-xs font-semibold">{Number(getUserCount(tenant)).toLocaleString()}</td>
                <td><p className="theme-text text-xs font-semibold">{formatKES(getTenantRevenue(tenant))}</p></td>
                <td><span className={`rounded-md px-3 py-1.5 text-[11px] font-medium ${tenant.status === 'active' ? 'bg-emerald-100 text-emerald-700' : tenant.status === 'suspended' ? 'bg-rose-100 text-rose-700' : 'bg-amber-100 text-amber-700'}`}>{tenant.status || '-'}</span></td>
                <td className="theme-text text-xs font-medium">{formatDate(tenant.created_at || tenant.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Link to={adminPath('tenants')} className="flex items-center justify-center gap-2 px-5 pb-5 text-xs font-medium text-app-accent">View all tenants <ArrowRight size={14} /></Link>
    </Panel>
  );
}

function TopTenants({ tenants }) {
  const ranked = [...tenants].sort((a, b) => getTenantRevenue(b) - getTenantRevenue(a)).slice(0, 5);
  return (
    <Panel title={<span>Top Tenants by Revenue <span className="font-medium text-slate-500">(This Month)</span></span>} action={{ to: adminPath('tenants'), label: 'View All' }}>
      <div className="divide-y divide-slate-100 px-5 pb-4">
        {ranked.length === 0 ? <p className="py-6 text-sm text-slate-500">No tenant revenue yet.</p> : ranked.map((tenant, index) => (
          <div key={tenant.id} className="flex items-center gap-4 py-3">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-slate-100 text-xs font-medium text-slate-600">{index + 1}</span>
            <TenantAvatar tenant={tenant} index={index + 3} />
            <div className="min-w-0 flex-1">
              <p className="theme-text truncate text-xs font-medium uppercase">{tenant.business_name || '-'}</p>
              <p className="theme-muted text-xs font-normal">{Number(getUserCount(tenant)).toLocaleString()} users</p>
            </div>
            <div className="text-right">
              <p className="theme-text text-xs font-semibold">{formatKES(getTenantRevenue(tenant))}</p>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function RecentActivity({ activities }) {
  const rows = activities.slice(0, 5).map((activity, index) => [
    formatDateTime(activity.timestamp),
    String(activity.action || 'Activity').replaceAll('_', ' '),
    activity.admin_email || activity.target_type || '-',
    index === 2 ? AlertTriangle : BellRing,
    index === 2 ? 'bg-rose-100 text-rose-600' : 'bg-blue-100 text-blue-600',
  ]);

  return (
    <Panel title="Recent Activity" action={{ to: adminPath('audit'), label: 'View All' }}>
      <div className="divide-y divide-slate-100 px-5 pb-5">
        {rows.length === 0 ? <p className="py-6 text-sm text-slate-500">No recent activity.</p> : rows.map(([time, title, detail, Icon, tone]) => (
          <div key={`${time}-${title}`} className="flex items-center gap-4 py-3">
            <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${tone}`}><Icon size={17} /></div>
            <span className="theme-muted w-20 text-xs font-normal">{time}</span>
            <div className="min-w-0">
              <p className="theme-text text-xs font-medium">{title}</p>
              <p className="theme-muted truncate text-xs font-normal">{detail}</p>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export default function AdminDashboard() {
  const [stats, setStats] = useState(null);
  const [chart, setChart] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [activities, setActivities] = useState([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    try {
      const [statsRes, chartRes, tenantsRes, auditRes] = await Promise.all([
        adminApi.get('/admin/system/stats'),
        adminApi.get('/admin/subscriptions/revenue-chart?days=31'),
        adminApi.get('/admin/tenants'),
        adminApi.get('/admin/tenants/audit/logs'),
      ]);
      setStats(statsRes.data);
      setChart(Array.isArray(chartRes.data) ? chartRes.data : []);
      setTenants(Array.isArray(tenantsRes.data) ? tenantsRes.data : []);
      setActivities(Array.isArray(auditRes.data) ? auditRes.data : []);
    } catch (error) {
      toast.error(error.response?.data?.error || 'Failed to load admin dashboard');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const timer = setInterval(load, 60000);
    return () => clearInterval(timer);
  }, []);

  const derived = useMemo(() => {
    const activeTenants = Number(stats?.activeTenants ?? tenants.filter((tenant) => tenant.status === 'active').length);
    const totalTenants = Number(stats?.totalTenants ?? tenants.length);
    const customers = tenants.reduce((sum, tenant) => sum + Number(getUserCount(tenant)), 0);
    const online = tenants.reduce((sum, tenant) => sum + Number(getOnlineCount(tenant)), 0);
    const monthlyRevenue = Number(stats?.monthlyRevenue ?? tenants.reduce((sum, tenant) => sum + Number(getTenantRevenue(tenant)), 0));
    return {
      totalTenants,
      activeTenants,
      customers: Number(stats?.totalCustomers ?? customers),
      onlineUsers: Number(stats?.onlineUsers ?? online),
      monthlyRevenue,
      visits: Number(stats?.websiteVisits ?? 0),
    };
  }, [stats, tenants]);

  const revenueSpark = useMemo(() => chart.map((item) => Number(item.amount || 0)), [chart]);

  const recentTenants = useMemo(() => {
    return [...tenants]
      .sort((a, b) => new Date(b.created_at || b.updated_at || 0) - new Date(a.created_at || a.updated_at || 0))
      .slice(0, 5);
  }, [tenants]);

  if (loading) {
    return <p className="text-xs font-medium text-slate-600">Loading admin dashboard...</p>;
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">Overview of your platform operations</p>
        </div>
        <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-center">
          <label className="relative block w-full sm:w-[340px]">
            <Search size={17} className="absolute left-4 top-1/2 -translate-y-1/2 text-blue-700" />
            <input className="form-input h-8 pl-10 pr-14" placeholder="Search tenants, users, invoices..." />
            <span className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md bg-slate-100 px-2 py-1 text-[11px] font-medium text-slate-500">Ctrl K</span>
          </label>
          <button type="button" className="btn-secondary" onClick={load}>
            <CalendarDays size={15} />
            {formatMonthRange()}
            <ChevronDown size={14} />
          </button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
        <MetricCard label="Total Tenants" value={derived.totalTenants.toLocaleString()} helper="All registered tenants" icon={Server} tone="blue" />
        <MetricCard label="Active Tenants" value={derived.activeTenants.toLocaleString()} helper={`${derived.totalTenants ? ((derived.activeTenants / derived.totalTenants) * 100).toFixed(1) : '0.0'}% of total`} icon={CheckCircle2} tone="green" />
        <MetricCard label="Total Customers" value={derived.customers.toLocaleString()} helper="Across all tenants" icon={Users} tone="purple" />
        <MetricCard label="Active Users (Online)" value={derived.onlineUsers.toLocaleString()} helper="Reported by tenant data" icon={Radio} tone="cyan" />
        <MetricCard label="Monthly Revenue" value={formatCompactKES(derived.monthlyRevenue)} helper="Subscription payments this month" icon={WalletCards} tone="orange" spark={revenueSpark} />
        <MetricCard label="Website Visits" value={derived.visits.toLocaleString()} helper={stats?.websiteVisits === undefined ? 'Metric not provided by API' : 'From stats API'} icon={TrendingUp} tone="rose" />
      </div>

      <div className="grid gap-5 xl:grid-cols-4">
        <RevenueTrend chart={chart} />
        <PlatformHealth health={stats?.systemHealth} />
        <SystemPerformance stats={stats} />
      </div>

      <div className="grid gap-5 xl:grid-cols-4">
        <RecentTenants tenants={recentTenants} />
        <TopTenants tenants={tenants} />
        <RecentActivity activities={activities} />
      </div>
    </div>
  );
}
