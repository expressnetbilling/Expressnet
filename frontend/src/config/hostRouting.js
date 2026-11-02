function normalizeDomain(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, '')
    .split(/[/?#]/)[0]
    .replace(/:\d+$/, '')
    .replace(/^\.+|\.+$/g, '');
}

const configuredTenantDomain = normalizeDomain(import.meta.env.VITE_TENANT_BASE_DOMAIN);
const configuredPublicDomain = normalizeDomain(import.meta.env.VITE_PUBLIC_BASE_DOMAIN);
const isLocalDomain = (domain) => domain === 'localhost' || domain.endsWith('.localhost');
// A local tenant base (for example localhost:8000) must not mask the public
// production domain when the same frontend build is deployed.
const PUBLIC_BASE_DOMAIN = [configuredPublicDomain, configuredTenantDomain]
  .find((domain) => domain && !isLocalDomain(domain)) || 'expressnetbilling.com';
const PRODUCTION_TENANT_DOMAINS = [...new Set(
  [configuredTenantDomain, configuredPublicDomain, PUBLIC_BASE_DOMAIN]
    .filter((domain) => domain && !isLocalDomain(domain)),
)];
const APP_SUBDOMAIN = String(import.meta.env.VITE_APP_SUBDOMAIN || 'app').trim().toLowerCase();
const ADMIN_SUBDOMAIN = String(import.meta.env.VITE_ADMIN_SUBDOMAIN || 'admin').trim().toLowerCase();

function hostnameForSubdomain(label) {
  if (window.location.hostname === 'localhost' || window.location.hostname.endsWith('.localhost')) {
    return `${label}.localhost`;
  }
  return `${label}.${PUBLIC_BASE_DOMAIN}`;
}

export function isAdminHost() {
  const hostname = window.location.hostname.toLowerCase();
  return hostname === `${ADMIN_SUBDOMAIN}.localhost`
    || hostname === `${ADMIN_SUBDOMAIN}.${PUBLIC_BASE_DOMAIN}`;
}

export function isAppHost() {
  const hostname = window.location.hostname.toLowerCase();
  return hostname === `${APP_SUBDOMAIN}.localhost`
    || hostname === `${APP_SUBDOMAIN}.${PUBLIC_BASE_DOMAIN}`;
}

export function isTenantHost() {
  const hostname = window.location.hostname.toLowerCase();
  const isLocalSubdomain = hostname.endsWith('.localhost')
    && hostname.split('.').length === 2;
  const isProductionSubdomain = PRODUCTION_TENANT_DOMAINS.some((domain) => {
    if (hostname === domain || hostname === `www.${domain}`) return false;
    const domainSuffix = `.${domain}`;
    return hostname.endsWith(domainSuffix)
      && hostname.slice(0, -domainSuffix.length).split('.').length === 1;
  });
  if (!isLocalSubdomain && !isProductionSubdomain) return false;

  const label = hostname.slice(0, hostname.indexOf('.'));
  return ![APP_SUBDOMAIN, ADMIN_SUBDOMAIN, 'www'].includes(label);
}

function subdomainRootUrl(label) {
  const url = new URL(window.location.href);
  url.hostname = hostnameForSubdomain(label);
  url.pathname = '/';
  url.search = '';
  url.hash = '';
  return url.toString();
}

export function appLoginUrl() {
  return subdomainRootUrl(APP_SUBDOMAIN);
}

export function adminHostLoginUrl() {
  return subdomainRootUrl(ADMIN_SUBDOMAIN);
}
