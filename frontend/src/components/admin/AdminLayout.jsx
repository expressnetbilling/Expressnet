import {
  Activity, ArrowRight, Building2, Command, FileClock, LayoutDashboard, LogOut, Settings2,
  CreditCard, Menu, MessageSquareText, PlugZap, Search,
  Wifi, X,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAdminAuth } from '../../context/AdminAuthContext';
import { adminLoginUrl, adminPath } from '../../config/adminPaths';

const sections = [
  { label: 'Overview', links: [{ to: adminPath('dashboard'), label: 'Dashboard', icon: LayoutDashboard }] },
  { label: 'Accounts', links: [
    { to: adminPath('tenants'), label: 'Tenants', icon: Building2 },
    { to: adminPath('payments'), label: 'Payments', icon: CreditCard },
  ] },
  { label: 'Operations', links: [
    { to: adminPath('communications'), label: 'Communications', icon: MessageSquareText },
    { to: adminPath('integrations'), label: 'Integrations', icon: PlugZap },
  ] },
  { label: 'Platform', links: [
    { to: adminPath('system'), label: 'System health', icon: Activity },
    { to: adminPath('audit'), label: 'Audit log', icon: FileClock },
  ] },
  { label: 'Preferences', links: [{ to: adminPath('settings'), label: 'Settings', icon: Settings2 }] },
];
const allLinks = sections.flatMap((section) => section.links);
const ADMIN_PREFERENCES_KEY = 'expressnet.admin.preferences';
const accentColors = { blue: '#2563eb', violet: '#7c3aed', teal: '#0f9f91', rose: '#e44770', orange: '#f97316' };

function pageTitle(pathname) {
  if (pathname.includes('/tenants/') && pathname !== adminPath('tenants')) return 'Tenant workspace';
  return allLinks.find((link) => pathname === link.to || pathname.startsWith(`${link.to}/`))?.label || 'Admin console';
}

export default function AdminLayout() {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [preferences, setPreferences] = useState(() => {
    try { return JSON.parse(localStorage.getItem(ADMIN_PREFERENCES_KEY) || '{}'); } catch { return {}; }
  });
  const { admin, logoutAdmin } = useAdminAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const title = pageTitle(location.pathname);
  const matches = useMemo(() => {
    const text = search.trim().toLowerCase();
    return (text ? allLinks.filter((link) => link.label.toLowerCase().includes(text)) : allLinks).slice(0, 6);
  }, [search]);

  useEffect(() => {
    const onShortcut = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setSearchOpen(true);
        window.setTimeout(() => document.getElementById('admin-page-search')?.focus(), 0);
      }
      if (event.key === 'Escape') setSearchOpen(false);
    };
    window.addEventListener('keydown', onShortcut);
    return () => window.removeEventListener('keydown', onShortcut);
  }, []);

  useEffect(() => {
    const handlePreferences = () => {
      try { setPreferences(JSON.parse(localStorage.getItem(ADMIN_PREFERENCES_KEY) || '{}')); } catch { setPreferences({}); }
    };
    window.addEventListener('expressnet-admin-preferences', handlePreferences);
    return () => window.removeEventListener('expressnet-admin-preferences', handlePreferences);
  }, []);

  const accent = accentColors[preferences.accent] || accentColors.blue;
  const effectiveTheme = preferences.theme === 'system'
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : (preferences.theme || 'dark');
  const adminStyle = {
    '--admin-accent': accent,
    '--admin-accent-soft': `${accent}1a`,
    '--admin-accent-border': `${accent}55`,
    '--admin-font-family': preferences.font === 'system-ui' ? 'system-ui' : (preferences.font || 'Inter'),
  };

  const logout = () => {
    logoutAdmin();
    window.location.assign(adminLoginUrl());
  };

  const goTo = (path) => {
    navigate(path);
    setSearch('');
    setSearchOpen(false);
    setOpen(false);
  };

  return (
    <div className="admin-shell min-h-screen bg-[#f4f6fa] text-slate-900" data-admin-theme={effectiveTheme} style={adminStyle}>
      <button className={`fixed inset-0 z-30 bg-slate-950/55 backdrop-blur-[2px] lg:hidden ${open ? '' : 'hidden'}`} onClick={() => setOpen(false)} aria-label="Close navigation" />

      <aside className={`fixed inset-y-0 left-0 z-40 flex w-[278px] flex-col border-r border-white/10 bg-[#101c32] text-white shadow-2xl transition-transform duration-200 lg:translate-x-0 ${open ? 'translate-x-0' : '-translate-x-full'}`}>
        <div className="flex h-[78px] items-center justify-between border-b border-white/10 px-5">
          <div className="flex items-center gap-3">
            <div className="admin-sidebar-logo flex h-10 w-10 items-center justify-center rounded-xl shadow-lg"><Wifi size={21} strokeWidth={2.5} /></div>
            <div>
              <p className="text-[14px] font-bold tracking-tight">ExpressNet</p>
              <p className="mt-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Control center</p>
            </div>
          </div>
          <button className="rounded-lg p-2 text-slate-400 hover:bg-white/10 hover:text-white lg:hidden" onClick={() => setOpen(false)} aria-label="Close navigation"><X size={18} /></button>
        </div>

        <nav className="min-h-0 flex-1 space-y-6 overflow-y-auto px-3 py-7">
          {sections.map((section) => (
            <div key={section.label}>
              <p className="mb-2 px-3 text-[10px] font-medium uppercase tracking-[0.18em] text-slate-500">{section.label}</p>
              <div className="space-y-1">
                {section.links.map(({ to, label, icon: Icon }) => (
                  <NavLink key={to} to={to} end={to === adminPath('dashboard')} onClick={() => setOpen(false)} className={({ isActive }) => `admin-nav-link group relative flex h-10 items-center gap-3 rounded-lg px-3 text-[12px] font-normal tracking-[0.01em] transition ${isActive ? 'is-active shadow-md shadow-black/10' : 'text-slate-300 hover:bg-white/[0.07] hover:text-white'}`}>
                    <Icon size={16} strokeWidth={1.65} />
                    <span className="flex-1">{label}</span>
                    <ArrowRight size={13} className="opacity-0 transition group-hover:translate-x-0.5 group-hover:opacity-60" />
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        <div className="border-t border-white/10 p-4">
          <div className="mb-3 flex min-w-0 items-center gap-3 rounded-xl bg-white/[0.05] p-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#f3b554] text-xs font-bold text-[#1a2539]">{String(admin?.name || 'A').trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase()}</div>
            <div className="min-w-0 flex-1"><p className="truncate text-xs font-semibold">{admin?.name || 'Administrator'}</p><p className="mt-1 truncate text-[10px] text-slate-400">{admin?.email || 'Platform operator'}</p></div>
          </div>
          <button type="button" className="flex h-10 w-full items-center gap-3 rounded-lg px-3 text-xs font-medium text-slate-300 transition hover:bg-rose-400/10 hover:text-rose-200" onClick={logout}><LogOut size={16} /> Sign out</button>
        </div>
      </aside>

      <div className="min-h-screen lg:pl-[278px]">
        <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/90 backdrop-blur-xl">
          <div className="flex min-h-[78px] items-center justify-between gap-4 px-4 sm:px-7 xl:px-10">
            <div className="flex min-w-0 items-center gap-3">
              <button className="rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-50 lg:hidden" onClick={() => setOpen(true)} aria-label="Open navigation"><Menu size={19} /></button>
              <div className="min-w-0">
                <div className="mb-1 flex items-center gap-2 text-[10px] font-medium text-slate-400"><span>Control center</span><span>/</span><span className="truncate text-slate-600">{title}</span></div>
                <h1 className="truncate text-[19px] font-bold tracking-tight text-slate-900">{title}</h1>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="relative hidden sm:block">
                <div className={`flex h-10 w-[min(34vw,330px)] items-center gap-2 rounded-xl border bg-slate-50 px-3 transition ${searchOpen ? 'border-orange-300 ring-4 ring-orange-100' : 'border-slate-200 hover:border-slate-300'}`}>
                  <Search size={16} className="shrink-0 text-slate-400" />
                  <input id="admin-page-search" value={search} onFocus={() => setSearchOpen(true)} onChange={(event) => { setSearch(event.target.value); setSearchOpen(true); }} placeholder="Jump to a page..." className="min-w-0 flex-1 bg-transparent text-xs text-slate-800 outline-none placeholder:text-slate-400" />
                  <kbd className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-1.5 py-1 text-[9px] font-semibold text-slate-400"><Command size={10} /> K</kbd>
                </div>
                {searchOpen && <>
                  <button className="fixed inset-0 z-20 cursor-default" aria-label="Close page search" onClick={() => setSearchOpen(false)} />
                  <div className="absolute right-0 top-12 z-30 w-full overflow-hidden rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl shadow-slate-900/10">
                    <p className="px-2.5 py-2 text-[9px] font-bold uppercase tracking-[0.14em] text-slate-400">Pages</p>
                    {matches.length ? matches.map(({ to, label, icon: Icon }) => <button key={to} type="button" onClick={() => goTo(to)} className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2.5 text-left text-xs font-medium text-slate-700 hover:bg-orange-50 hover:text-slate-950"><Icon size={15} className="text-slate-400" />{label}<ArrowRight size={13} className="ml-auto text-slate-300" /></button>) : <p className="px-2.5 py-3 text-xs text-slate-500">No matching pages.</p>}
                  </div>
                </>}
              </div>
              <div className="hidden items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-2 md:flex"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /><span className="text-[10px] font-semibold text-emerald-700">Platform online</span></div>
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1540px] px-4 py-6 sm:px-7 sm:py-8 xl:px-10"><Outlet /></main>
      </div>
    </div>
  );
}
