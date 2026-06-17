import type { MouseEvent } from 'react';
import { Chip } from '@heroui/react';
import { TAB_CHAT, TAB_DASHBOARD } from '../lib/constants';
import { navigateToTab } from '../lib/routing';

export function TabBar({ activeTab }: { activeTab: string }) {
  function onTabClick(event: MouseEvent<HTMLAnchorElement>, tab: string) {
    event.preventDefault();
    if (tab === activeTab) return;
    navigateToTab(tab);
  }

  const renderTab = (tab: string, label: string, href: string) => (
    <a key={tab} href={href} onClick={(e) => onTabClick(e, tab)}>
      <Chip
        size="md"
        variant={activeTab === tab ? 'primary' : 'secondary'}
        color={activeTab === tab ? 'accent' : 'default'}
        className="app-tab-chip cursor-pointer"
      >
        <Chip.Label>{label}</Chip.Label>
      </Chip>
    </a>
  );

  return (
    <nav className="flex flex-nowrap items-center justify-center gap-1 sm:gap-1.5" aria-label="Sections">
      {renderTab(TAB_DASHBOARD, 'Dashboard', '?tab=dashboard')}
      {renderTab(TAB_CHAT, 'Chat', '?tab=chat')}
    </nav>
  );
}
