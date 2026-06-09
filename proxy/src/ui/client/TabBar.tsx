/** @jsxImportSource hono/jsx/dom */
import { TAB_CHAT, TAB_DASHBOARD } from '../../shared/constants';
import type { TabParam } from '../../shared/types';
import { navigateToTab } from './routing';

function onTabClick(event: Event, tab: TabParam) {
  event.preventDefault();
  if (tab === getCurrentTabFromEvent(event)) {
    return;
  }
  navigateToTab(tab);
}

function getCurrentTabFromEvent(event: Event): TabParam | null {
  const target = event.currentTarget as HTMLAnchorElement | null;
  const tab = target?.dataset.tab;
  return tab === TAB_CHAT || tab === TAB_DASHBOARD ? tab : null;
}

export function TabBar({ activeTab }: { activeTab: TabParam }) {
  return (
    <nav class="tab-bar" aria-label="Sections">
      <a
        href={`?tab=${TAB_DASHBOARD}`}
        data-tab={TAB_DASHBOARD}
        class={`tab-link${activeTab === TAB_DASHBOARD ? ' active' : ''}`}
        aria-current={activeTab === TAB_DASHBOARD ? 'page' : undefined}
        onClick={(event: Event) => onTabClick(event, TAB_DASHBOARD)}
      >
        Dashboard
      </a>
      <a
        href={`?tab=${TAB_CHAT}`}
        data-tab={TAB_CHAT}
        class={`tab-link${activeTab === TAB_CHAT ? ' active' : ''}`}
        aria-current={activeTab === TAB_CHAT ? 'page' : undefined}
        onClick={(event: Event) => onTabClick(event, TAB_CHAT)}
      >
        Chat
      </a>
    </nav>
  );
}
