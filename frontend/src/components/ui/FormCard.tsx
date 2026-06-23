import type { ReactNode, CSSProperties } from 'react';

/**
 * Surface card used to group form / config content.
 * Shared design-system primitive — consumed across all config panels
 * and the create-agent flow for consistent spacing, radius and borders.
 */
export function FormCard({
  children,
  style,
  title,
}: {
  children: ReactNode;
  style?: CSSProperties;
  title?: ReactNode;
}) {
  return (
    <div
      style={{
        background: 'var(--color-bg-container)',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-lg)',
        padding: 'var(--space-6)',
        marginBottom: 'var(--space-4)',
        boxShadow: 'var(--shadow-xs)',
        ...style,
      }}
    >
      {title ? (
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 'var(--space-6)',
          }}
        >
          {typeof title === 'string' ? (
            <h4 style={{ fontSize: 15, fontWeight: 600, color: 'var(--color-text)', margin: 0 }}>{title}</h4>
          ) : (
            title
          )}
        </div>
      ) : null}
      {children}
    </div>
  );
}

export default FormCard;
