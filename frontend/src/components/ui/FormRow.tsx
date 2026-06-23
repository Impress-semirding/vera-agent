import type { ReactNode } from 'react';

/**
 * Label + control row for vertical forms.
 * Shared design-system primitive.
 */
export function FormRow({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: required ? 'center' : 'flex-start',
        gap: 'var(--space-4)',
      }}
    >
      <span
        style={{
          width: 80,
          flexShrink: 0,
          fontSize: 14,
          color: 'var(--color-text-secondary)',
          paddingTop: required ? 0 : 'var(--space-2)',
        }}
      >
        {label}
        {required && <span style={{ color: 'var(--color-danger)', marginLeft: 2 }}>*</span>}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
    </div>
  );
}

export default FormRow;
