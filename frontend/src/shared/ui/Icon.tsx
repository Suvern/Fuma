import {
  IconApps,
  IconGridStroked,
  IconGithubLogo,
  IconCommentStroked,
  IconBellStroked,
  IconList,
  IconArchive,
  IconHistory,
  IconShieldStroked,
  IconArrowRight,
  IconExternalOpen,
  IconPlus,
  IconSearch,
  IconChevronRight,
  IconSidebar,
  IconBox,
  IconRefresh,
  IconTick,
  IconServerStroked,
  IconUser,
  IconExit,
  IconClose,
  IconLock,
} from "@douyinfe/semi-icons";
const icons = {
  grid: IconGridStroked,
  apps: IconApps,
  branch: IconGithubLogo,
  chat: IconCommentStroked,
  bell: IconBellStroked,
  tasks: IconList,
  disk: IconArchive,
  history: IconHistory,
  shield: IconShieldStroked,
  arrow: IconArrowRight,
  external: IconExternalOpen,
  plus: IconPlus,
  search: IconSearch,
  chevron: IconChevronRight,
  sidebar: IconSidebar,
  package: IconBox,
  refresh: IconRefresh,
  check: IconTick,
  server: IconServerStroked,
  user: IconUser,
  logout: IconExit,
  close: IconClose,
  lock: IconLock,
};
export type IconName = keyof typeof icons;
export function Icon({
  name,
  size = 20,
  className = "",
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  const Component = icons[name];
  return (
    <Component
      className={className}
      style={{ fontSize: size, flexShrink: 0 }}
      aria-hidden
    />
  );
}
export function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden>
      <Icon name="package" size={24} />
    </span>
  );
}
