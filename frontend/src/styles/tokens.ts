/**
 * Design tokens — the SINGLE SOURCE OF TRUTH for Vera's design system.
 *
 * These values are mirrored as CSS custom properties in `global.less` (:root).
 * When you change a value here, update the matching `--*` variable there too.
 *
 * Consumption:
 *  - antd theme (`theme.ts`) reads the `color` / `radius` / `shadow` consts.
 *  - Less modules and TSX read the CSS variables (`var(--color-*)`).
 *  - TSX may import these consts directly when a literal value is required
 *    (e.g. canvas/echarts colors that cannot read CSS vars at render time).
 */

/* ── Brand / primary ─────────────────────────────── */
export const color = {
  primary: '#1677ff',
  primaryHover: '#4096ff',
  primaryActive: '#0958d9',
  primarySoft: '#e8f1ff', // selected / tinted backgrounds

  // Text scale — tuned for ≥4.5:1 contrast on white (replaces raw #000000XX alphas)
  text: '#1f2937',
  textSecondary: '#4b5563',
  textTertiary: '#6b7280',
  textQuaternary: '#9ca3af', // non-essential only

  // Backgrounds
  bg: '#f5f7fa',
  bgContainer: '#ffffff',
  bgSubtle: '#f9fafb',
  bgMuted: '#f3f4f6',

  // Borders
  border: '#e5e7eb',
  borderLight: '#eef0f3',

  // Status
  success: '#16a34a',
  warning: '#f59e0b',
  danger: '#ef4444',
  info: '#1677ff',

  // Thinking / reasoning blocks (token-izes the stray #6b5ce7)
  thinking: '#6b5ce7',
  thinkingBg: '#f5f3ff',
  thinkingBorder: '#e8e0ff',
} as const;

/* ── Spacing (4px base) ──────────────────────────── */
export const space = {
  1: '4px',
  2: '8px',
  3: '12px',
  4: '16px',
  5: '20px',
  6: '24px',
  8: '32px',
  10: '40px',
  12: '48px',
} as const;

/* ── Radius ──────────────────────────────────────── */
export const radius = {
  sm: '6px',
  md: '8px',
  lg: '12px',
  xl: '16px',
  pill: '999px',
} as const;

/* ── Shadows (layered soft + tech glow) ──────────── */
export const shadow = {
  xs: '0 1px 2px 0 rgba(16, 24, 40, 0.04)',
  sm: '0 1px 3px 0 rgba(16, 24, 40, 0.06), 0 1px 2px -1px rgba(16, 24, 40, 0.04)',
  md: '0 4px 12px 0 rgba(16, 24, 40, 0.06), 0 2px 4px -1px rgba(16, 24, 40, 0.04)',
  lg: '0 12px 24px 0 rgba(16, 24, 40, 0.08), 0 4px 8px -2px rgba(16, 24, 40, 0.04)',
  glow: '0 4px 14px 0 rgba(22, 119, 255, 0.32)',
  glowHover: '0 6px 20px 0 rgba(22, 119, 255, 0.42)',
} as const;

/* ── Glass (light mode — ≥0.7 opacity for visibility) ── */
export const glass = {
  bg: 'rgba(255, 255, 255, 0.72)',
  borderHighlight: 'rgba(255, 255, 255, 0.6)',
  blur: '12px',
} as const;

/* ── Motion ──────────────────────────────────────── */
export const motion = {
  fast: '150ms',
  base: '200ms',
  slow: '300ms',
  ease: 'cubic-bezier(0.4, 0, 0.2, 1)',
} as const;

/* ── Typography ──────────────────────────────────── */
export const fontFamily =
  "system-ui, -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', Roboto, 'Helvetica Neue', Arial, sans-serif";
