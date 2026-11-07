import {
  BriefcaseBusiness,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CreditCard,
  Database,
  ClipboardCheck,
  ClipboardList,
  FileBarChart,
  FileText,
  Gauge,
  LayoutDashboard,
  Mail,
  MessageSquare,
  Network,
  Package,
  Tags,
  RadioTower,
  Receipt,
  Settings,
  Ticket,
  Users,
  WalletCards,
  Wifi,
  Wrench,
  X,
} from 'lucide-react';
import { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { canAccessPage, isTenantAdmin, pageForPath } from '../utils/permissions';

const sections = [
  {
    links: [{ to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard }],
  },
  {
    title: 'Customers',
    icon: Users,
    links: [
      { to: '/pppoe-customers', label: 'PPPoE', icon: RadioTower },
      { to: '/hotspot-customers', label: 'Hotspot', icon: Wifi },
      { to: '/static-customers', label: 'Static', icon: Database },
    ],
  },
  {
    title: 'Plans',
    icon: Tags,
    links: [
      { to: '/packages', label: 'Packages', icon: Package },
      { to: '/vouchers', label: 'Vouchers', icon: WalletCards },
    ],
  },
  {
    title: 'Management',
    icon: BriefcaseBusiness,
    links: [
      { to: '/tickets', label: 'Tickets', icon: Ticket },
      { to: '/audit', label: 'Audit trail', icon: ClipboardList },
      { to: '/equipment', label: 'Tools & Equipments', icon: Wrench },
      { to: '/requisitions', label: 'Requisitions', icon: ClipboardList },
      // { to: '/reports/management', label: 'Management Report', icon: FileBarChart },
    ],
  },
  {
    title: 'Staff Workspace',
    staffOnly: true,
    icon: ClipboardCheck,
    links: [
      { to: '/staff/tasks', label: 'Profile', icon: Ticket },
      { to: '/staff/reports', label: 'Reports', icon: FileText },
      { to: '/staff/requisitions', label: 'Requisitions', icon: ClipboardList },
    ],
  },
  {
    title: 'Finance',
    icon: CreditCard,
    links: [
      { to: '/payments', label: 'Payments', icon: CreditCard },
      { to: '/expenses', label: 'Expenses', icon: Receipt },
      { to: '/invoices', label: 'Invoices', icon: FileText },
      { to: '/reports/finance', label: 'Financial Report', icon: FileBarChart },
    ],
  },
  {
    title: 'Communication',
    icon: MessageSquare,
    links: [
      { to: '/messages', label: 'Messages', icon: MessageSquare },
      { to: '/emails', label: 'Emails', icon: Mail },
    ],
  },
  {
    title: 'Network',
    icon: Network,
    links: [
      { to: '/mikrotik', label: 'Link MikroTik', icon: Gauge },
      { to: '/tr069', label: 'TR-069', icon: RadioTower },
      // { to: '/reports/network', label: 'Network Report', icon: RadioTower },
    ],
  },
  {
    links: [{ to: '/settings', label: 'Settings', icon: Settings, trailing: ChevronLeft }],
  },
];

function tenantInitial(tenant) {
  const name = tenant?.business_name || tenant?.name || 'Expressnet';
  return String(name).trim().charAt(0).toUpperCase() || 'E';
}

export default function Sidebar({ open, onClose }) {
  const { tenant } = useAuth();
  const location = useLocation();
  const [collapsedSections, setCollapsedSections] = useState({});

  const visibleLinks = (links) => links.filter(({ to }) => canAccessPage(tenant, pageForPath(to)));

  const isGroupActive = (links) => links.some((link) => {
    if (link.to === '/dashboard') return location.pathname === '/dashboard';
    return location.pathname === link.to || location.pathname.startsWith(`${link.to}/`);
  });
  const toggleSection = (title) => {
    setCollapsedSections((current) => ({ ...current, [title]: !(current[title] ?? false) }));
  };

  const navClass = ({ isActive }) =>
    [
      'tenant-sidebar-nav-button flex h-9 items-center gap-2.5 rounded-md px-2.5 text-sm font-medium tracking-[0.01em] transition',
      isActive
        ? 'bg-[var(--sidebar-active)] text-white shadow-[inset_3px_0_0_rgba(255,255,255,0.28)]'
        : 'text-white/88 hover:bg-white/10 hover:text-white',
    ].join(' ');

  return (
    <>
      <div
        className={`fixed inset-0 z-30 bg-slate-950/40 transition-opacity lg:hidden ${
          open ? 'opacity-100' : 'pointer-events-none opacity-0'
        }`}
        onClick={onClose}
      />

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col px-3 py-4 text-white shadow-2xl transition-transform lg:w-[232px] lg:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
        style={{ background: 'linear-gradient(180deg, var(--sidebar-top) 0%, var(--sidebar-middle) 46%, var(--sidebar-bottom) 100%)' }}
      >
        <div className="mb-3 rounded-md border p-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]" style={{ background: 'color-mix(in srgb, var(--sidebar-bottom) 28%, transparent)', borderColor: 'color-mix(in srgb, var(--sidebar-border) 32%, transparent)' }}>
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-base font-medium tracking-wide text-white shadow-sm" style={{ background: 'var(--sidebar-avatar)' }}>
              {tenantInitial(tenant)}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-bold tracking-[0.01em] text-white">{tenant?.business_name || tenant?.name || 'Expressnet'}</p>
            </div>
            <ChevronDown size={14} className="text-white/75" />
          </div>
        </div>


        <nav className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1 tracking-[0.01em]">
          {sections.map((section, index) => {
            if (section.staffOnly && isTenantAdmin(tenant)) return null;
            const links = visibleLinks(section.links);
            if (!links.length) return null;
            const SectionIcon = section.icon;
            const groupActive = isGroupActive(links);
            const expanded = !(collapsedSections[section.title] ?? false);

            if (!section.title) {
              return (
                <div key={`single-${index}`} className={index ? 'border-t border-white/10 pt-2' : ''}>
                  {links.map(({ to, label, icon: Icon, trailing: Trailing }) => (
                    <NavLink key={`${label}-${to}`} to={to} className={navClass} onClick={onClose}>
                      <Icon size={16} strokeWidth={1.5} />
                      <span className="min-w-0 flex-1 truncate font-medium">{label}</span>
                      {Trailing && <Trailing size={15} />}
                    </NavLink>
                  ))}
                </div>
              );
            }

            return (
              <div key={section.title} className="border-t border-white/10 pt-2 first:border-t-0 first:pt-0">
                <button
                  type="button"
                  className={`tenant-sidebar-nav-button flex h-8 w-full items-center gap-2.5 rounded-md px-2.5 text-left text-sm font-medium tracking-[0.01em] transition hover:bg-white/10 ${groupActive ? 'text-white' : 'text-white/84'}`}
                  onClick={() => toggleSection(section.title)}
                  aria-expanded={expanded}
                >
                  {SectionIcon && <SectionIcon size={15} strokeWidth={1.5} />}
                  <span className="min-w-0 flex-1 truncate">{section.title}</span>
                  {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </button>
                {expanded && (
                  <div className="mt-0.5 space-y-0.5">
                    {links.map(({ to, label, icon: Icon }) => (
                      <NavLink
                        key={`${section.title}-${label}-${to}`}
                        to={to}
                        className={({ isActive }) => [
                          'tenant-sidebar-nav-button ml-6 flex h-8 items-center gap-2 rounded-md px-2 text-[13px] font-medium tracking-[0.01em] transition',
                          isActive ? 'bg-[var(--sidebar-active)] text-white' : 'text-white/84 hover:bg-white/10 hover:text-white',
                        ].join(' ')}
                        onClick={onClose}
                      >
                        <Icon size={12} strokeWidth={1.5} />
                        <span className="min-w-0 flex-1 truncate">{label}</span>
                      </NavLink>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </nav>

      </aside>
    </>
  );
}
