import { lazy, Suspense, useEffect, useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import Navbar from './components/Navbar';
import AdminLayout from './components/admin/AdminLayout';
import AdminProtectedRoute from './components/admin/AdminProtectedRoute';
import ProtectedRoute from './components/ProtectedRoute';
import Sidebar from './components/Sidebar';
const AdminAuditLog = lazy(() => import('./pages/admin/AdminAuditLog'));
const AdminCommunications = lazy(() => import('./pages/admin/AdminCommunications'));
const AdminDashboard = lazy(() => import('./pages/admin/AdminDashboard'));
const AdminIntegrations = lazy(() => import('./pages/admin/AdminIntegrations'));
const AdminLogin = lazy(() => import('./pages/admin/AdminLogin'));
const AdminSystem = lazy(() => import('./pages/admin/AdminSystem'));
const AdminSettings = lazy(() => import('./pages/admin/AdminSettings'));
const AdminTenantDetail = lazy(() => import('./pages/admin/AdminTenantDetail'));
const AdminTenants = lazy(() => import('./pages/admin/AdminTenants'));
const AdminPayments = lazy(() => import('./pages/admin/AdminPayments'));
const TenantAuditLog = lazy(() => import('./pages/TenantAuditLog'));
const BusinessSettings = lazy(() => import('./pages/BusinessSettings'));
const BillingPayment = lazy(() => import('./pages/BillingPayment'));
const Customers = lazy(() => import('./pages/Customers'));
const CustomerPortal = lazy(() => import('./pages/CustomerPortal'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Emails = lazy(() => import('./pages/Emails'));
const Equipment = lazy(() => import('./pages/Equipment'));
const Expenses = lazy(() => import('./pages/Expenses'));
const Home = lazy(() => import('./pages/Home'));
const Invoices = lazy(() => import('./pages/Invoices'));
const IspOperations = lazy(() => import('./pages/IspOperations'));
const Login = lazy(() => import('./pages/Login'));
const Messages = lazy(() => import('./pages/Messages'));
const MikrotikLink = lazy(() => import('./pages/MikrotikLink'));
const MikrotikSettings = lazy(() => import('./pages/MikrotikSettings'));
const NotFound = lazy(() => import('./pages/NotFound'));
const Packages = lazy(() => import('./pages/Packages'));
const Payments = lazy(() => import('./pages/Payments'));
const Profile = lazy(() => import('./pages/Profile'));
const PppoeProfile = lazy(() => import('./pages/PppoeProfile'));
const Register = lazy(() => import('./pages/Register'));
const Reports = lazy(() => import('./pages/Reports'));
const Requisitions = lazy(() => import('./pages/Requisitions'));
const StaffReports = lazy(() => import('./pages/StaffReports'));
const StaffRequisitions = lazy(() => import('./pages/StaffRequisitions'));
const StaffTasks = lazy(() => import('./pages/StaffTasks'));
const Tr069 = lazy(() => import('./pages/Tr069'));
const Vouchers = lazy(() => import('./pages/Vouchers'));
import { ADMIN_DASHBOARD_PATH, ADMIN_PATH, adminPath } from './config/adminPaths';
import { TENANT_THEME_EVENT, applyTenantTheme } from './utils/theme';
import { isAdminHost, isAppHost, isTenantHost } from './config/hostRouting';
import { useAuth } from './context/AuthContext';
import { useAdminAuth } from './context/AdminAuthContext';

function DashboardLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    applyTenantTheme();
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const listener = () => applyTenantTheme();
    media.addEventListener('change', listener);
    window.addEventListener('storage', listener);
    window.addEventListener(TENANT_THEME_EVENT, listener);
    return () => {
      media.removeEventListener('change', listener);
      window.removeEventListener('storage', listener);
      window.removeEventListener(TENANT_THEME_EVENT, listener);
    };
  }, []);

  return (
    <div className="tenant-app theme-page min-h-screen w-full">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="min-h-screen w-full min-w-0 lg:ml-[232px] lg:w-[calc(100%-232px)]">
        <Navbar onMenuClick={() => setSidebarOpen(true)} />
        <main className="mx-auto w-full max-w-[1200px] px-4 py-4 sm:px-8 sm:py-5">
          <Routes>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/audit" element={<TenantAuditLog />} />
            <Route path="/billing/payment" element={<BillingPayment />} />
            <Route path="/customers" element={<Customers title="Users" />} />
            <Route path="/pppoe-customers" element={<Customers initialFilter="pppoe" serviceLocked="pppoe" title="PPPoE Customers" />} />
            <Route path="/hotspot-customers" element={<Customers initialFilter="hotspot" serviceLocked="hotspot" title="Hotspot Customers" />} />
            <Route path="/static-customers" element={<Customers initialFilter="static" serviceLocked="static" title="Static Customers" />} />
            <Route path="/active-users" element={<Navigate to="/customers" replace />} />
            
            <Route path="/tickets" element={<IspOperations module="tickets" />} />
            <Route path="/packages" element={<Packages />} />
            <Route path="/payments" element={<Payments />} />
            <Route path="/vouchers" element={<Vouchers />} />
            <Route path="/requisitions" element={<Requisitions />} />
            <Route path="/expenses" element={<Expenses />} />
            <Route path="/invoices" element={<Invoices />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/reports/finance" element={<Reports type="finance" />} />
            <Route path="/reports/management" element={<Reports type="management" />} />
            <Route path="/reports/network" element={<Reports type="network" />} />
            <Route path="/messages" element={<Messages />} />
            <Route path="/emails" element={<Emails />} />
            <Route path="/mikrotik" element={<MikrotikSettings />} />
            <Route path="/mikrotik/link" element={<MikrotikLink />} />
            <Route path="/tr069" element={<Tr069 />} />
            <Route path="/equipment" element={<Equipment />} />
            <Route path="/staff/tasks" element={<StaffTasks />} />
            <Route path="/staff/reports" element={<StaffReports />} />
            <Route path="/staff/requisitions" element={<StaffRequisitions />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="/settings" element={<BusinessSettings />} />
            <Route path="/settings/expresswifi/edit" element={<BusinessSettings />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  const onAdminHost = isAdminHost();
  const tenantHost = isTenantHost() || isAppHost();
  const { isAuthenticated } = useAuth();
  const { isAdminAuthenticated } = useAdminAuth();

  return (
    <Suspense fallback={<div className="min-h-screen bg-slate-950" aria-busy="true" />}>
    <Routes>
      <Route path="/" element={onAdminHost
        ? (isAdminAuthenticated ? <Navigate to={ADMIN_DASHBOARD_PATH} replace /> : <AdminLogin />)
        : tenantHost
          ? (isAuthenticated ? <Navigate to="/dashboard" replace /> : <Login />)
          : <Home />} />
      <Route path="/register" element={<Register />} />
      <Route path="/portal/:tenantId" element={<CustomerPortal />} />
      <Route path="/customers/:tenantId" element={<CustomerPortal />} />
      <Route path="/customer/:tenantId" element={<CustomerPortal />} />
      <Route path="/hotspot/:tenantId" element={<CustomerPortal />} />
      <Route path="/pppoe/:tenantId" element={<CustomerPortal />} />
      <Route path="/pppoe-renew/:tenantId" element={<CustomerPortal />} />
      <Route path="/pppoe-profile/:tenantId" element={<PppoeProfile />} />
      <Route path="/pppoe-expired/:tenantId" element={<PppoeProfile />} />
      <Route path="/tv/:tenantId" element={<CustomerPortal />} />
      <Route element={<AdminProtectedRoute />}>
        <Route path={ADMIN_PATH} element={<AdminLayout />}>
          <Route index element={<Navigate to={ADMIN_DASHBOARD_PATH} replace />} />
          <Route path="dashboard" element={<AdminDashboard />} />
          <Route path="tenants" element={<AdminTenants />} />
          <Route path="tenants/:id" element={<AdminTenantDetail />} />
          <Route path="payments" element={<AdminPayments />} />
          <Route path="communications" element={<AdminCommunications />} />
          <Route path="integrations" element={<AdminIntegrations />} />
          <Route path="system" element={<AdminSystem />} />
          <Route path="audit" element={<AdminAuditLog />} />
          <Route path="settings" element={<AdminSettings />} />
        </Route>
      </Route>
      {ADMIN_PATH !== '/admin' && (
        <>
          <Route path="/admin" element={<Navigate to={adminPath('dashboard')} replace />} />
        </>
      )}
      <Route element={<ProtectedRoute />}>
        <Route path="/*" element={<DashboardLayout />} />
      </Route>
    </Routes>
    </Suspense>
  );
}
