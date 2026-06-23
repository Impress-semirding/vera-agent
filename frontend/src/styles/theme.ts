import type { ThemeConfig } from 'antd';
import { color, shadow } from './tokens';

/**
 * Ant Design theme — values derived from the single source of truth in tokens.ts.
 * The glass/tech button *effects* (gradient, backdrop blur, glow) live in global.less
 * because antd tokens cannot express them. Token values here handle sizing, color
 * mapping, radius and base shadows.
 */
export const themeToken: ThemeConfig = {
  token: {
    colorPrimary: color.primary,
    colorInfo: color.info,
    colorSuccess: color.success,
    colorWarning: color.warning,
    colorError: color.danger,

    colorBgContainer: color.bgContainer,
    colorBgLayout: color.bg,
    colorBgSpotlight: color.bgContainer,

    colorText: color.text,
    colorTextSecondary: color.textSecondary,
    colorTextTertiary: color.textTertiary,
    colorTextQuaternary: color.textQuaternary,

    colorBorder: color.border,
    colorBorderSecondary: color.borderLight,

    borderRadius: 8,
    borderRadiusLG: 12,
    borderRadiusSM: 6,
    fontSize: 14,

    boxShadow: shadow.sm,
    boxShadowSecondary: shadow.md,

    wireframe: false,
  },
  components: {
    Button: {
      controlHeight: 36,
      controlHeightSM: 28,
      fontWeight: 500,
      primaryShadow: 'none', // glow added via global.less
      defaultBorderColor: color.border,
    },
    Card: {
      borderRadiusLG: 12,
      boxShadowTertiary: shadow.sm,
    },
    Input: {
      borderRadius: 8,
      controlHeight: 36,
    },
    Select: {
      borderRadius: 8,
      controlHeight: 36,
    },
    Modal: {
      borderRadiusLG: 12,
    },
    Segmented: {
      borderRadius: 8,
      itemSelectedBg: color.primarySoft,
      itemSelectedColor: color.primary,
    },
    Menu: {
      itemBorderRadius: 8,
      itemSelectedBg: color.primarySoft,
      itemSelectedColor: color.primary,
    },
    Table: {
      borderRadius: 12,
      headerBg: color.bgSubtle,
      headerColor: color.textSecondary,
      rowHoverBg: color.bgSubtle,
    },
    Tag: {
      borderRadiusSM: 6,
    },
    Tabs: {
      itemSelectedColor: color.primary,
      inkBarColor: color.primary,
    },
  },
};
