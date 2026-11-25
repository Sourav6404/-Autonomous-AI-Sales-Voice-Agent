// FortiSales AI — Shared JS utilities (app.js)
// White-and-violet design system & shared client functions.

const TOKEN_KEY = 'fortisales_token';
const ROLE_KEY = 'fortisales_role';

function getToken() { return localStorage.getItem(TOKEN_KEY); }
function getRole() { return localStorage.getItem(ROLE_KEY) || ''; }

function requireAuth() {
  const token = getToken();
  if (!token) { window.location.href = '/'; return null; }
  return token;
}

function logout() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ROLE_KEY);
  window.location.href = '/';
}

async function apiFetch(path, options = {}) {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch('/api/v1' + path, { ...options, headers });
  if (res.status === 401) { logout(); return null; }
  return res;
}

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

function formatDateShort(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString();
}

function formatTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function statusBadge(status) {
  const map = {
    new: { bg: '#EDE9FE', color: '#6D28D9', label: 'New' },
    contacted: { bg: '#E0F2FE', color: '#0369A1', label: 'Contacted' },
    qualified: { bg: '#DCFCE7', color: '#15803D', label: 'Qualified' },
    unqualified: { bg: '#F1F5F9', color: '#64748B', label: 'Unqualified' },
    converted: { bg: '#D1FAE5', color: '#047857', label: 'Converted' },
    lost: { bg: '#FEE2E2', color: '#B91C1C', label: 'Lost' },
    open: { bg: '#EDE9FE', color: '#6D28D9', label: 'Open' },
    in_progress: { bg: '#E0F2FE', color: '#0284C7', label: 'In Progress' },
    resolved: { bg: '#DCFCE7', color: '#16A34A', label: 'Resolved' },
    closed: { bg: '#F1F5F9', color: '#475569', label: 'Closed' },
    scheduled: { bg: '#EDE9FE', color: '#7C3AED', label: 'Scheduled' },
    confirmed: { bg: '#DCFCE7', color: '#16A34A', label: 'Confirmed' },
    completed: { bg: '#F3F4F6', color: '#4B5563', label: 'Completed' },
    cancelled: { bg: '#FEE2E2', color: '#DC2626', label: 'Cancelled' },
    no_show: { bg: '#FEF3C7', color: '#D97706', label: 'No Show' },
    hot: { bg: '#FEE2E2', color: '#DC2626', label: 'Hot' },
    warm: { bg: '#FEF3C7', color: '#D97706', label: 'Warm' },
    cold: { bg: '#E2E8F0', color: '#475569', label: 'Cold' },
    urgent: { bg: '#FEE2E2', color: '#DC2626', label: 'Urgent' },
    high: { bg: '#FFEDD5', color: '#EA580C', label: 'High' },
    medium: { bg: '#FEF3C7', color: '#D97706', label: 'Medium' },
    low: { bg: '#F1F5F9', color: '#64748B', label: 'Low' },
    initiated: { bg: '#EDE9FE', color: '#7C3AED', label: 'Initiated' },
  };
  const item = map[status] || { bg: '#F1F5F9', color: '#64748B', label: status || '—' };
  return `<span style="background:${item.bg};color:${item.color};padding:3px 10px;border-radius:12px;font-size:0.75rem;font-weight:600;">${escapeHtml(item.label)}</span>`;
}

function showToast(msg, type = 'success') {
  let toast = document.getElementById('__toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = '__toast';
    toast.style.cssText = 'position:fixed;bottom:1.5rem;right:1.5rem;padding:0.75rem 1.25rem;border-radius:8px;font-size:0.875rem;font-weight:600;z-index:9999;box-shadow:0 10px 25px rgba(0,0,0,0.15);transition:opacity 0.3s';
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.style.background = type === 'success' ? '#7C3AED' : '#DC2626';
  toast.style.color = '#FFFFFF';
  toast.style.opacity = '1';
  setTimeout(() => { toast.style.opacity = '0'; }, 3000);
}
