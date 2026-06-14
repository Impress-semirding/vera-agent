import s from '../index.module.less';

interface ConfigNavProps {
  activePanel: string;
  onPanelChange: (panel: string) => void;
}

const NAV_GROUPS = [
  {
    label: '配置',
    items: [
      { key: 'info', icon: 'fa-id-card-o', label: '基本信息' },
      { key: 'base', icon: 'fa-file-code-o', label: '基础配置' },
    ],
  },
  {
    label: '能力扩展',
    items: [
      { key: 'tool', icon: 'fa-wrench', label: '工具配置' },
      { key: 'skill', icon: 'fa-puzzle-piece', label: '技能Skill' },
    ],
  },
  {
    label: '交互设置',
    items: [
      { key: 'session', icon: 'fa-sliders', label: '会话设置' },
      { key: 'wecom', icon: 'fa-wechat', label: '微信连接' },
    ],
  },
];

export default function ConfigNav({ activePanel, onPanelChange }: ConfigNavProps) {
  return (
    <div className={s.sidebarBody}>
      {NAV_GROUPS.map((group) => (
        <div key={group.label} className={s.navGroup}>
          <div className={s.navGroupLabel}>{group.label}</div>
          {group.items.map((item) => (
            <div
              key={item.key}
              className={`${s.navItem} ${activePanel === item.key ? s.active : ''}`}
              onClick={() => onPanelChange(item.key)}
            >
              <span className={s.navIcon}><i className={`fa ${item.icon}`} /></span>
              <span>{item.label}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
