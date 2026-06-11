import type { ReactNode } from 'react';

/** Shared layout primitives used by the EditAgent config panels.
 *  Extracted so each panel file can stay self-contained and consistent. */

export function FormCard({ children }: { children: ReactNode }) {
  return (
    <div style={{ background: '#fff', border: '1px solid #d9d9d9', borderRadius: 8, padding: 20, marginBottom: 16 }}>
      {children}
    </div>
  );
}

export function FormRow({ label, required, children }: { label: string; required?: boolean; children: ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: required ? 'center' : 'flex-start', gap: 16 }}>
      <span style={{ width: 80, flexShrink: 0, fontSize: 14, paddingTop: required ? 0 : 8 }}>
        {label}
        {required && <span style={{ color: '#ff4d4f', marginLeft: 2 }}>*</span>}
      </span>
      <div style={{ flex: 1 }}>{children}</div>
    </div>
  );
}
