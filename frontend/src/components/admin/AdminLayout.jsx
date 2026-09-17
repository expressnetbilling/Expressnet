import {
  Bell,
  Building2,
  ChevronDown,
  Home,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  PlugZap,
  Search,
  Shield,
  UserCircle,
  Users,
  Wifi,
  X,
} from 'lucide-react';
import { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAdminAuth } from '../../context/AdminAuthContext';
import { ADMIN_LOGIN_PATH, adminPath } from '../../config/adminPaths';

const links = [
  { to: adminPath('dashboard'), label: 'Dashboard', icon: Home },
  { to: adminPath('tenants'), label: 'Tenants', icon: Users },
  { to: adminPath('users'), label: 'Customers', icon: Building2 },
  { to: adminPath('communications'), label: 'Communications', icon: MessageSquare },
  { to: adminPath('integrations'), label: 'Integrations', icon: PlugZap },
  { to: adminPath('system'), label: 'Reports', icon: LayoutDashboard },
  { to: adminPath('audit'), label: 'Audit Logs', icon: Shield },
  { to: adminPath('users'), label: 'Users & Roles', icon: UserCircle },
];

export default function AdminLayout() {
  const [open, setOpen] = useState(false);
  const { admin, logoutAdmin } = useAdminAuth();
  const navigate = useNavigate();

  const logout = () => {
    logoutAdmin();
    navigate(ADMIN_LOGIN_PATH, { replace: true });
  };

  const navClass = ({ isActive }) =>
    [
      'flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[12px] font-normal transition',
      isActive ? 'bg-[var(--sidebar-active)] text-white shadow-[inset_3px_0_0_rgba(255,255,255,0.28)]' : 'text-white/88 hover:bg-white/10 hover:text-white',
    ].join(' ');

  return (
    <div className="tenant-app theme-page min-h-screen text-[var(--app-text)]">
      <div
        className={`fixed inset-0 z-30 bg-slate-950/50 lg:hidden ${open ? '' : 'hidden'}`}
        onClick={() => setOpen(false)}
      />

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col px-3 py-4 text-white shadow-2xl transition-transform lg:w-[232px] lg:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
        style={{ background: 'linear-gradient(180deg, var(--sidebar-top) 0%, var(--sidebar-middle) 46%, var(--sidebar-bottom) 100%)' }}
      >
        <div className="mb-3 flex items-center justify-between rounded-md border p-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]" style={{ background: 'color-mix(in srgb, var(--sidebar-bottom) 28%, transparent)', borderColor: 'color-mix(in srgb, var(--sidebar-border) 32%, transparent)' }}>
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-white shadow-sm" style={{ background: 'var(--sidebar-avatar)' }}>
              <Wifi size={20} />
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-[13px] font-semibold text-white">ExpressNet Mtandao</h1>
              <p className="truncate text-[11px] font-normal text-white/70">Admin Portal</p>
            </div>
          </div>
          <button className="rounded-md p-2 hover:bg-white/10 lg:hidden" onClick={() => setOpen(false)} aria-label="Close admin nav">
            <X size={20} />
          </button>
        </div>

        <nav className="min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1">
          {links.map(({ to, label, icon: Icon }) => (
            <NavLink key={`${to}-${label}`} to={to} className={navClass} onClick={() => setOpen(false)}>
              <Icon size={16} />
              <span className="flex-1">{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-white/10 pt-4">
          <div className="mb-3 flex items-center gap-3 rounded-md px-2 py-2">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full" style={{ background: 'var(--sidebar-avatar)' }}>
              <UserCircle size={27} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-semibold">{admin?.name || 'Super Admin'}</p>
              <p className="truncate text-[11px] font-normal text-white/70">{admin?.email || 'admin@expressnet.co.ke'}</p>
            </div>
            <ChevronDown size={14} className="text-white/75" />
          </div>
          <button type="button" className="flex h-8 w-full items-center gap-2.5 rounded-md px-2.5 text-[12px] font-normal text-white/88 hover:bg-white/10 hover:text-white" onClick={logout}>
            <LogOut size={16} />
            Logout
          </button>
        </div>
      </aside>

      <div className="min-h-screen w-full min-w-0 lg:ml-[232px] lg:w-[calc(100%-232px)]">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-slate-200 px-4 lg:px-8">
          <div className="flex min-w-0 items-center gap-4">
            <button className="rounded-md p-2 text-slate-600 hover:bg-slate-100 lg:hidden" onClick={() => setOpen(true)} aria-label="Open admin nav">
              <Menu size={22} />
            </button>
            <button className="hidden rounded-md p-2 text-slate-600 hover:bg-slate-100 lg:block" aria-label="Toggle menu">
              <Menu size={22} />
            </button>
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Admin</p>
              <h2 className="text-base font-medium text-slate-950">Dashboard</h2>
              <div className="mt-1 hidden items-center gap-2 text-[11px] font-normal text-slate-400 sm:flex">
                <span>Home</span>
                <span>/</span>
                <span className="text-app-accent">Dashboard</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <label className="relative hidden w-[270px] md:block">
              <Search size={15} className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                className="form-input h-8 pl-10"
                placeholder="Search tenants, invoices, users..."
              />
            </label>
            <button className="relative flex h-8 w-8 items-center justify-center rounded-md text-slate-600 hover:bg-slate-100" aria-label="Notifications">
              <Bell size={20} />
              <span className="absolute right-0.5 top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[9px] font-medium text-white" style={{ background: 'var(--app-accent)' }}>5</span>
            </button>
            <div className="hidden items-center gap-3 md:flex">
              <div className="flex h-9 w-9 items-center justify-center rounded-full text-white" style={{ background: 'var(--app-accent)' }}>
                <UserCircle size={25} />
              </div>
              <div>
                <p className="text-[12px] font-medium text-slate-950">{admin?.name || 'Admin User'}</p>
                <p className="text-[11px] font-normal text-slate-500">{admin?.role || 'Super Admin'}</p>
              </div>
              <ChevronDown size={14} className="text-slate-500" />
            </div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1200px] px-4 py-4 sm:px-8 sm:py-5">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
