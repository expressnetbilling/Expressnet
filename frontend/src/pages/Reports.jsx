import { CalendarDays, Download, RotateCcw } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import api from '../api/axios';

function toDate(value) {
  if (!value) return null;
  if (value._seconds) return new Date(value._seconds * 1000);
  if (value.seconds) return new Date(value.seconds * 1000);
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? null : date;
}

function formatKES(value) {
  return `Ksh ${Number(value || 0).toLocaleString('en-KE', { minimumFractionDigits: 2 })}`;
}

const ACCENT = 'var(--app-accent)';
const ACCENT_SOFT = 'var(--app-accent-soft)';
const GRID = '#e5e7eb';

const fallbackSeries = {
  payments: [['Jan', 23000], ['Feb', 18000], ['Mar', 21000], ['Apr', 14000], ['May', 14000], ['Jun', 200]],
  activeUsers: [['Mon', 36, 0], ['Tue', 19, 0], ['Wed', 5, 0], ['Thu', 2, 0], ['Fri', 1, 0]],
  retention: [['Jan', 130, 70, 38], ['Feb', 138, 68, 37], ['Mar', 72, 68, 39], ['Apr', 66, 67, 34], ['May', 50, 63, 43], ['Jun', 10, 28, 75]],
  dataUsage: [['27 May', 62], ['28 May', 38], ['29 May', 49], ['30 May', 50], ['31 May', 75], ['01 Jun', 45]],
  sms: [['Thu', 70], ['Fri', 190], ['Sat', 190], ['Sun', 170], ['Mon', 190], ['Tue', 40]],
};

const reportCopy = {
  finance: {
    title: 'Financial Report',
    subtitle: 'Payments, revenue, settlements, and money movement.',
    exportName: 'financial-report.csv',
  },
  management: {
    title: 'Management Report',
    subtitle: 'Work progress, staff activity, operational tasks, and customer follow-up.',
    exportName: 'management-report.csv',
  },
  network: {
    title: 'Network Report',
    subtitle: 'Router health, sessions, traffic, provisioning, and MikroTik activity.',
    exportName: 'network-report.csv',
  },
};

function maxValue(data, index = 1) {
  return Math.max(...data.map((item) => Number(item[index]) || 0), 1);
}

function points(data, index, width = 320, height = 190, pad = 18) {
  const max = maxValue(data, index);
  return data.map((item, i) => {
    const x = pad + (i * (width - pad * 2)) / Math.max(data.length - 1, 1);
    const y = height - pad - ((Number(item[index]) || 0) / max) * (height - pad * 2);
    return `${x},${y}`;
  }).join(' ');
}

function ChartCard({ title, subtitle, children, action = 'This week' }) {
  return (
    <section className="theme-card min-h-[318px] rounded-lg border">
      <div className="flex items-start justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div>
          <h2 className="theme-text text-sm font-medium">{title}</h2>
          <p className="theme-muted mt-1 text-[11px]">{subtitle}</p>
        </div>
        <button type="button" className="theme-card-muted h-8 rounded-md border px-3 text-[11px] font-medium">{action}</button>
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function BarChart({ data, valueIndex = 1, height = 190 }) {
  const max = maxValue(data, valueIndex);
  return (
    <div className="flex items-end gap-3" style={{ height }}>
      {data.map((item) => (
        <div key={item[0]} className="flex flex-1 flex-col items-center gap-2">
          <div className="w-full max-w-[26px] rounded-t-sm" style={{ height: `${Math.max(((Number(item[valueIndex]) || 0) / max) * (height - 28), item[valueIndex] ? 5 : 1)}px`, background: ACCENT }} />
          <span className="text-[10px] text-slate-500">{item[0]}</span>
        </div>
      ))}
    </div>
  );
}

function LineChart({ data, indexes = [1], colors = [ACCENT], height = 190 }) {
  return (
    <svg viewBox="0 0 320 190" className="h-full w-full" style={{ minHeight: height }}>
      {[0, 1, 2, 3].map((line) => <line key={line} x1="18" x2="304" y1={24 + line * 42} y2={24 + line * 42} stroke={GRID} strokeWidth="1" />)}
      {indexes.map((index, lineIndex) => <polyline key={index} fill="none" stroke={colors[lineIndex]} strokeWidth="3" points={points(data, index)} />)}
      {indexes.map((index, lineIndex) => points(data, index).split(' ').map((point) => {
        const [cx, cy] = point.split(',');
        return <circle key={`${index}-${point}`} cx={cx} cy={cy} r="3.5" fill={colors[lineIndex]} stroke="#fff" strokeWidth="1" />;
      }))}
      {data.map((item, index) => <text key={item[0]} x={18 + (index * 286) / Math.max(data.length - 1, 1)} y="184" textAnchor="middle" fill="#64748b" fontSize="9">{String(item[0]).split(' ')[0]}</text>)}
    </svg>
  );
}

function dateInputValue(date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function monthStartInputValue() {
  const today = new Date();
  return dateInputValue(new Date(today.getFullYear(), today.getMonth(), 1));
}

function paymentSeries(payments) {
  const grouped = new Map();
  payments.forEach((payment) => {
    const paidAt = toDate(payment.paid_at || payment.created_at || payment.initiated_at);
    if (!paidAt) return;
    const key = dateInputValue(paidAt);
    grouped.set(key, (grouped.get(key) || 0) + Number(payment.amount || 0));
  });
  return [...grouped.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .slice(-12)
    .map(([date, amount]) => [date.slice(5), amount]);
}

function packageSeries(payments) {
  const grouped = new Map();
  payments.forEach((payment) => {
    const name = String(payment.package_name || 'Unassigned').trim() || 'Unassigned';
    grouped.set(name, (grouped.get(name) || 0) + Number(payment.amount || 0));
  });
  return [...grouped.entries()]
    .sort((left, right) => right[1] - left[1])
    .slice(0, 6);
}

function exportCsv(rows, filename = 'report.csv') {
  const headers = ['customer_name', 'phone', 'payment_code', 'amount', 'status', 'paid_at', 'provider'];
  const csv = [headers.join(','), ...rows.map((item) => headers.map((key) => JSON.stringify(item[key] ?? '')).join(','))].join('\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function MetricCard({ title, value, helper }) {
  return (
    <div className="rounded-md p-4 shadow-[0_18px_30px_rgba(15,23,42,0.12)]" style={{ background: 'var(--app-metric-card-bg)', color: 'var(--app-text)' }}>
      <p className="text-xs font-medium">{title}</p>
      <p className="mt-3 text-xl font-semibold">{formatKES(value)}</p>
      <p className="mt-2 text-xs">{helper}</p>
    </div>
  );
}

function PlainMetricCard({ title, value, helper }) {
  return (
    <div className="theme-card rounded-md border p-4">
      <p className="theme-muted text-xs font-medium">{title}</p>
      <p className="theme-text mt-3 text-2xl font-semibold">{value}</p>
      <p className="theme-muted mt-2 text-xs">{helper}</p>
    </div>
  );
}

export default function Reports({ type = 'finance' }) {
  const reportType = reportCopy[type] ? type : 'finance';
  const copy = reportCopy[reportType];
  const [payments, setPayments] = useState([]);
  const [dashboard, setDashboard] = useState(null);
  const [expenseSummary, setExpenseSummary] = useState({ total_expenses: 0, net_revenue: 0 });
  const [fromDate, setFromDate] = useState(monthStartInputValue);
  const [toDateValue, setToDateValue] = useState(() => dateInputValue(new Date()));
  const [appliedRange, setAppliedRange] = useState(() => ({ from: monthStartInputValue(), to: dateInputValue(new Date()) }));

  useEffect(() => {
    async function load() {
      try {
        const query = new URLSearchParams({ all: '1' });
        if (reportType === 'finance') {
          if (appliedRange.from) query.set('from', appliedRange.from);
          if (appliedRange.to) query.set('to', appliedRange.to);
        }
        const [paymentsResponse, dashboardResponse] = await Promise.all([
          api.get(`/payments?${query.toString()}`),
          api.get('/dashboard/stats'),
        ]);
        const paymentData = paymentsResponse.data;
        setPayments(Array.isArray(paymentData) ? paymentData : paymentData.results || []);
        setDashboard(dashboardResponse.data);
        if (reportType === 'finance') {
          const expensesResponse = await api.get(`/reports/expenses?from=${encodeURIComponent(appliedRange.from)}&to=${encodeURIComponent(appliedRange.to)}`);
          setExpenseSummary(expensesResponse.data || { total_expenses: 0, net_revenue: 0 });
        }
      } catch (error) {
        toast.error(error.response?.data?.message || 'Failed to load report');
      }
    }
    load();
  }, [reportType, appliedRange]);

  const successfulPayments = useMemo(() => payments.filter((payment) => payment.status === 'success'), [payments]);
  const financialTotals = useMemo(() => {
    const revenue = successfulPayments.reduce((sum, payment) => sum + Number(payment.amount || 0), 0);
    const expenses = Number(expenseSummary.total_expenses || 0);
    return { revenue, expenses, net: revenue - expenses };
  }, [expenseSummary, successfulPayments]);
  const financialPaymentSeries = useMemo(() => paymentSeries(successfulPayments), [successfulPayments]);
  const financialPackageSeries = useMemo(() => packageSeries(successfulPayments), [successfulPayments]);
  const rangeLabel = appliedRange.from && appliedRange.to ? `${appliedRange.from} to ${appliedRange.to}` : 'Selected period';

  const applyDateRange = () => {
    if (fromDate && toDateValue && fromDate > toDateValue) {
      toast.error('The start date must be on or before the end date');
      return;
    }
    setAppliedRange({ from: fromDate, to: toDateValue });
  };

  const resetDateRange = () => {
    const next = { from: monthStartInputValue(), to: dateInputValue(new Date()) };
    setFromDate(next.from);
    setToDateValue(next.to);
    setAppliedRange(next);
  };

  const chartData = useMemo(() => ({
    payments: dashboard?.payments_chart?.length ? dashboard.payments_chart : fallbackSeries.payments,
    activeUsers: dashboard?.active_users_chart?.length ? dashboard.active_users_chart : fallbackSeries.activeUsers,
    retention: dashboard?.retention_chart?.length ? dashboard.retention_chart : fallbackSeries.retention,
    dataUsage: dashboard?.data_usage_chart?.length ? dashboard.data_usage_chart : fallbackSeries.dataUsage,
    forecast: dashboard?.revenue_forecast?.length ? dashboard.revenue_forecast : fallbackSeries.payments,
    sms: dashboard?.sms_chart?.length ? dashboard.sms_chart : fallbackSeries.sms,
  }), [dashboard]);

  const routerCount = Number(dashboard?.router_count || dashboard?.active_routers || 0);
  const totalUsers = Number(dashboard?.total_customers || dashboard?.total_users || 0);
  const activeUsers = Number(dashboard?.active_customers || dashboard?.active_users || 0);
  const staffCount = Number(dashboard?.staff_count || dashboard?.team_members || 0);
  const taskCount = Number(dashboard?.open_tickets || dashboard?.tasks_open || 0);

  return (
    <div className="space-y-7">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div>
            <h1 className="theme-text text-xl font-medium">{copy.title}</h1>
            <p className="theme-muted mt-1 text-xs">{copy.subtitle}</p>
          </div>
          <span className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-slate-900 text-[10px]">i</span>
        </div>
        <button type="button" className="btn-primary h-9 px-4 shadow-md" onClick={() => exportCsv(reportType === 'finance' ? successfulPayments : payments, copy.exportName)}>
          <Download size={14} />
          Export Report
        </button>
      </div>

      {reportType === 'finance' && (
        <>
          <section className="theme-card flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="theme-text text-sm font-medium">Report period</h2>
              <p className="theme-muted mt-1 text-xs">Choose the dates to include in every financial total, chart, table, and export.</p>
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <label className="text-xs font-medium text-[var(--app-muted)]">From
                <input type="date" className="form-input mt-1 h-9" value={fromDate} max={toDateValue || undefined} onChange={(event) => setFromDate(event.target.value)} />
              </label>
              <label className="text-xs font-medium text-[var(--app-muted)]">To
                <input type="date" className="form-input mt-1 h-9" value={toDateValue} min={fromDate || undefined} onChange={(event) => setToDateValue(event.target.value)} />
              </label>
              <button type="button" className="btn-secondary h-9 px-3" onClick={resetDateRange} title="Reset to this month"><RotateCcw size={14} /></button>
              <button type="button" className="btn-primary h-9 px-4" onClick={applyDateRange}><CalendarDays size={14} />Apply</button>
            </div>
          </section>
          <section className="grid gap-6 md:grid-cols-3">
            <MetricCard title="Revenue Collected" value={financialTotals.revenue} helper={rangeLabel} />
            <MetricCard title="Expenses" value={financialTotals.expenses} helper="Recorded expenses in this period" />
            <MetricCard title="Net Revenue" value={financialTotals.net} helper="Revenue less recorded expenses" />
          </section>
        </>
      )}

      {reportType === 'management' && (
        <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
          <PlainMetricCard title="Open Tasks" value={taskCount.toLocaleString('en-KE')} helper="Current staff work queue" />
          <PlainMetricCard title="Staff Members" value={staffCount.toLocaleString('en-KE')} helper="Team members with system access" />
          <PlainMetricCard title="Active Customers" value={activeUsers.toLocaleString('en-KE')} helper="Customers requiring ongoing service" />
          <PlainMetricCard title="Total Customers" value={totalUsers.toLocaleString('en-KE')} helper="Operational customer base" />
        </section>
      )}

      {reportType === 'network' && (
        <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
          <PlainMetricCard title="Routers" value={routerCount.toLocaleString('en-KE')} helper="Linked MikroTik routers" />
          <PlainMetricCard title="Active Users" value={activeUsers.toLocaleString('en-KE')} helper="Current service activity" />
          <PlainMetricCard title="PPPoE Users" value={Number(dashboard?.pppoe_customers || 0).toLocaleString('en-KE')} helper="Router-backed PPPoE customers" />
          <PlainMetricCard title="Hotspot Users" value={Number(dashboard?.hotspot_customers || 0).toLocaleString('en-KE')} helper="Captive portal users" />
        </section>
      )}

      <section className="grid gap-4 xl:grid-cols-2">
        {reportType === 'finance' && (
          <>
            <ChartCard title="Payments trend" subtitle="Successful payments across the selected period." action={rangeLabel}><BarChart data={financialPaymentSeries.length ? financialPaymentSeries : [['No payments', 0]]} height={230} /></ChartCard>
            <ChartCard title="Top packages" subtitle="Revenue collected by package in the selected period." action={rangeLabel}><BarChart data={financialPackageSeries.length ? financialPackageSeries : [['No packages', 0]]} height={230} /></ChartCard>
          </>
        )}
        {reportType === 'management' && (
          <>
            <ChartCard title="Work Progress" subtitle="Open, active, and completed work movement."><LineChart data={chartData.activeUsers} indexes={[1, 2]} colors={[ACCENT, ACCENT_SOFT]} height={230} /></ChartCard>
            <ChartCard title="Staff Communication" subtitle="SMS and customer follow-up activity."><BarChart data={chartData.sms} height={230} /></ChartCard>
            <ChartCard title="Customer Retention" subtitle="Recurring and active customer movement."><LineChart data={chartData.retention} indexes={[1, 2, 3]} colors={[ACCENT, '#16a34a', '#ef4444']} height={230} /></ChartCard>
          </>
        )}
        {reportType === 'network' && (
          <>
            <ChartCard title="Data Usage" subtitle="Router data usage trend for PPPoE and Hotspot users."><LineChart data={chartData.dataUsage} indexes={[1]} colors={[ACCENT]} height={230} /></ChartCard>
            <ChartCard title="Active Sessions" subtitle="Router-backed active and new sessions."><LineChart data={chartData.activeUsers} indexes={[1, 2]} colors={[ACCENT, ACCENT_SOFT]} height={230} /></ChartCard>
          </>
        )}
      </section>

      {reportType === 'finance' && (
        <section className="theme-card overflow-hidden rounded-lg border">
          <div className="border-b border-slate-200 px-4 py-3">
            <h2 className="theme-text text-sm font-medium">Successful payments</h2>
            <p className="theme-muted mt-1 text-[11px]">Only transactions within {rangeLabel} are shown.</p>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="theme-card-muted text-xs text-[var(--app-muted)]"><tr><th className="px-4 py-3">Date</th><th className="px-4 py-3">Customer</th><th className="px-4 py-3">Package</th><th className="px-4 py-3">Reference</th><th className="px-4 py-3 text-right">Amount</th></tr></thead>
              <tbody className="divide-y divide-slate-200">
                {successfulPayments.length ? successfulPayments.slice(0, 20).map((payment) => <tr key={payment.id || payment.payment_code}><td className="px-4 py-3">{toDate(payment.paid_at || payment.created_at)?.toLocaleDateString() || '—'}</td><td className="px-4 py-3">{payment.customer_name || payment.phone || 'Walk-in customer'}</td><td className="px-4 py-3">{payment.package_name || '—'}</td><td className="px-4 py-3">{payment.payment_code || payment.daraja_receipt_number || '—'}</td><td className="px-4 py-3 text-right font-medium">{formatKES(payment.amount)}</td></tr>) : <tr><td colSpan="5" className="theme-muted px-4 py-10 text-center">No successful payments in the selected period.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      )}

    </div>
  );
}
