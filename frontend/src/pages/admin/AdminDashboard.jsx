import {
  AlertTriangle,
  ArrowRight,
  BellRing,
  CheckCircle2,
  Cpu,
  Database,
  HardDrive,
  MemoryStick,
  Radio,
  RefreshCw,
  Server,
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

function getTenantRevenue(tenant) {
  return tenant.monthly_revenue ?? tenant.revenue ?? 0;
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
    <section className={`theme-card overflow-hidden rounded-2xl border shadow-[0_12px_36px_rgba(15,23,42,0.045)] ${className}`}>
      <div className="flex items-center justify-between px-5 py-4">
        <h2 className="admin-heading text-sm font-bold tracking-tight">{title}</h2>
        {action && <Link to={action.to} className="text-xs font-medium text-app-accent">{action.label}</Link>}
      </div>
      {children}
    </section>
  );
}

function Sparkline({ color = 'var(--admin-accent)', fill = 'var(--admin-accent-soft)', points }) {
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
  return (
    <section className="theme-card rounded-2xl border p-4 shadow-[0_12px_36px_rgba(15,23,42,0.045)] transition hover:-translate-y-0.5 hover:shadow-lg">
      <div className="flex items-start gap-4">
        <div className="admin-accent-icon mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md">
          <Icon size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="theme-muted text-xs font-medium">{label}</p>
          <p className="theme-text mt-1 text-2xl font-semibold leading-none tracking-tight">{value}</p>
          {helper && <p className="theme-muted mt-2 text-xs font-normal">{helper}</p>}
        </div>
      </div>
      <Sparkline points={spark} />
    </section>
  );
}

function TenantAvatar({ tenant, index }) {
  return (
    <div className="admin-primary flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold">
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
            {Array.from({ length: 4 }, (_, index) => formatCompactKES(max * (3 - index) / 3)).map((label, index) => <div key={`${index}-${label}`} className="border-t border-slate-100 pt-0.5">{label}</div>)}
          </div>
          <svg className="absolute left-12 top-2 h-[210px] w-[calc(100%-4rem)]" viewBox="0 0 620 210" preserveAspectRatio="none">
            <defs>
              <linearGradient id="trafficBlue" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="var(--admin-accent)" stopOpacity="0.23" />
                <stop offset="100%" stopColor="var(--admin-accent)" stopOpacity="0.02" />
              </linearGradient>
              <linearGradient id="trafficGreen" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="#16a34a" stopOpacity="0.18" />
                <stop offset="100%" stopColor="#16a34a" stopOpacity="0.02" />
              </linearGradient>
            </defs>
            <polygon points={`0,210 ${points} 620,210`} fill="url(#trafficBlue)" />
            <polyline points={points} fill="none" stroke="var(--admin-accent)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
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
  ];
  return (
    <Panel title="Platform Health" action={{ to: adminPath('system'), label: 'View All' }}>
          <div className="divide-y divide-slate-100 px-5 pb-4">
        {rows.map(([Icon, label, detail, status, tone]) => (
          <div key={label} className="flex items-center gap-4 py-4">
            <div className="admin-accent-icon flex h-12 w-12 shrink-0 items-center justify-center rounded-full"><Icon size={22} /></div>
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
              <Server size={15} className="admin-accent-text" />
              <span className="theme-muted flex-1 text-xs font-normal">{label}</span>
              <span className="theme-text text-xs font-semibold">{value}</span>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  );
}

function ResourcePerformance({ metrics, samples }) {
  const resources = [
    { label: 'CPU utilization', value: metrics?.cpu?.usagePercent, suffix: '%', icon: Cpu, field: (sample) => sample.cpu?.usagePercent, tone: 'blue' },
    { label: 'Memory usage', value: metrics?.memory?.usagePercent, suffix: '%', icon: MemoryStick, field: (sample) => sample.memory?.usagePercent, tone: 'purple' },
    { label: 'Disk usage', value: metrics?.disk?.usagePercent, suffix: '%', icon: HardDrive, field: (sample) => sample.disk?.usagePercent, tone: 'orange' },
    { label: 'Database latency', value: metrics?.database?.latencyMs, suffix: ' ms', icon: Database, field: (sample) => sample.database?.latencyMs, tone: 'cyan' },
  ];
  return <Panel title="Live Server Resources" action={{ to: adminPath('system'), label: 'Open System Health' }} className="xl:col-span-4">
    <div className="grid gap-3 p-5 sm:grid-cols-2 xl:grid-cols-4">{resources.map(({ label, value, suffix, icon, field, tone }) => <MetricCard key={label} label={label} value={value == null ? '—' : `${Number(value).toFixed(1)}${suffix}`} helper="Live application host sample" icon={icon} tone={tone} spark={samples.map(field).filter((item) => item != null)} />)}</div>
  </Panel>;
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
    'admin-accent-icon',
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
  const [resourceMetrics, setResourceMetrics] = useState(null);
  const [resourceSamples, setResourceSamples] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  async function load() {
    setRefreshing(true);
    const results = await Promise.allSettled([
      adminApi.get('/admin/system/stats'),
      adminApi.get('/admin/subscriptions/revenue-chart?days=31'),
      adminApi.get('/admin/tenants'),
      adminApi.get('/admin/tenants/audit/logs?page=1'),
      adminApi.get('/admin/system/metrics'),
    ]);
    const [statsResult, chartResult, tenantsResult, auditResult, metricsResult] = results;
    if (statsResult.status === 'fulfilled') setStats(statsResult.value.data);
    else toast.error(statsResult.reason?.response?.data?.error || 'Failed to load dashboard summary');
    if (chartResult.status === 'fulfilled') setChart(Array.isArray(chartResult.value.data) ? chartResult.value.data : (chartResult.value.data.results || []));
    if (tenantsResult.status === 'fulfilled') setTenants(Array.isArray(tenantsResult.value.data) ? tenantsResult.value.data : (tenantsResult.value.data.results || []));
    if (auditResult.status === 'fulfilled') {
      const data = auditResult.value.data;
      setActivities(Array.isArray(data) ? data : (data.results || []));
    }
    if (metricsResult.status === 'fulfilled') {
      setResourceMetrics(metricsResult.value.data);
      setResourceSamples((previous) => [...previous, metricsResult.value.data].slice(-30));
    }
    setLoading(false);
    setRefreshing(false);
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
    };
  }, [stats, tenants]);

  const revenueSpark = useMemo(() => chart.map((item) => Number(item.amount || 0)), [chart]);

  const recentTenants = useMemo(() => {
    return [...tenants]
      .sort((a, b) => new Date(b.created_at || b.updated_at || 0) - new Date(a.created_at || a.updated_at || 0))
      .slice(0, 5);
  }, [tenants]);

  if (loading) return <div className="space-y-6"><div className="h-28 animate-pulse rounded-2xl bg-white" /><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">{Array.from({ length: 5 }, (_, index) => <div key={index} className="h-32 animate-pulse rounded-2xl bg-white" />)}</div><div className="grid gap-5 xl:grid-cols-3"><div className="h-80 animate-pulse rounded-2xl bg-white xl:col-span-2" /><div className="h-80 animate-pulse rounded-2xl bg-white" /></div></div>;

  return (
    <div className="space-y-6">
      <div className="admin-hero relative overflow-hidden rounded-2xl bg-[#15243d] px-6 py-6 text-white shadow-[0_20px_55px_rgba(15,23,42,0.16)] sm:px-8 sm:py-7">
        <div className="pointer-events-none absolute -right-8 -top-24 h-72 w-72 rounded-full border border-white/[0.08]" />
        <div className="pointer-events-none absolute -right-2 -top-16 h-60 w-60 rounded-full border border-white/[0.08]" />
        <div className="relative flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
          <div><p className="text-[10px] font-bold uppercase tracking-[0.18em] text-white/70">Platform overview</p><h2 className="mt-1 text-2xl font-bold tracking-tight">Your network at a glance</h2><p className="admin-muted mt-1 text-sm text-white/70">A live view of tenant growth, subscriptions, revenue, and platform health.</p></div>
          <div className="flex items-center gap-3"><span className="hidden text-xs text-white/70 sm:block">Updated {new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</span><button type="button" onClick={load} disabled={refreshing} className="inline-flex h-10 items-center gap-2 rounded-xl border border-white/15 bg-white/[0.08] px-4 text-xs font-semibold text-white transition hover:bg-white/[0.14] disabled:opacity-60"><RefreshCw size={14} className={`admin-accent-text ${refreshing ? 'animate-spin' : ''}`} />Refresh</button></div>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
        <MetricCard label="Total Tenants" value={derived.totalTenants.toLocaleString()} helper="All registered tenants" icon={Server} tone="blue" />
        <MetricCard label="Active Tenants" value={derived.activeTenants.toLocaleString()} helper={`${derived.totalTenants ? ((derived.activeTenants / derived.totalTenants) * 100).toFixed(1) : '0.0'}% of total`} icon={CheckCircle2} tone="green" />
        <MetricCard label="Total Customers" value={derived.customers.toLocaleString()} helper="Across all tenants" icon={Users} tone="purple" />
        <MetricCard label="Active Users (Online)" value={derived.onlineUsers.toLocaleString()} helper="Reported by tenant data" icon={Radio} tone="cyan" />
        <MetricCard label="Monthly Revenue" value={formatCompactKES(derived.monthlyRevenue)} helper="Subscription payments this month" icon={WalletCards} tone="orange" spark={revenueSpark} />
        <MetricCard label="Pending setup" value={Number(stats?.pendingTenants || 0).toLocaleString()} helper="Tenants awaiting onboarding" icon={BellRing} tone="rose" />
      </div>

      <div className="grid gap-5 xl:grid-cols-4">
        <RevenueTrend chart={chart} />
        <PlatformHealth health={stats?.systemHealth} />
        <SystemPerformance stats={stats} />
      </div>

      <div className="grid gap-5 xl:grid-cols-4"><ResourcePerformance metrics={resourceMetrics} samples={resourceSamples} /></div>

      <div className="grid gap-5 xl:grid-cols-4">
        <RecentTenants tenants={recentTenants} />
        <TopTenants tenants={tenants} />
        <RecentActivity activities={activities} />
      </div>
    </div>
  );
}
