const colors = {
  LOGIN: 'bg-blue-100 text-blue-700',
  CREATE: 'bg-green-100 text-green-700',
  UPDATE: 'bg-yellow-100 text-yellow-700',
  SUSPEND: 'bg-orange-100 text-orange-700',
  VIEW: 'bg-slate-100 text-slate-700',
  DELETE: 'bg-red-100 text-red-700',
};

export default function AdminActionBadge({ action }) {
  const label = String(action || 'UNKNOWN').toUpperCase();
  const key = Object.keys(colors).find((prefix) => label.startsWith(prefix)) || 'VIEW';

  return (
    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${colors[key]}`}>
      {label}
    </span>
  );
}
