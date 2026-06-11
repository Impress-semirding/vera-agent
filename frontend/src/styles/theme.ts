import type { ThemeConfig } from 'antd';

export const themeToken: ThemeConfig = {
  token: {
    colorPrimary: '#1677ff',
    borderRadius: 8,
    colorBgContainer: '#ffffff',
    colorBorder: '#d9d9d9',
    colorText: '#000000e0',
    colorTextSecondary: '#00000073',
    fontSize: 14,
  },
  components: {
    Menu: {
      itemBorderRadius: 6,
    },
    Card: {
      borderRadiusLG: 12,
    },
  },
};
