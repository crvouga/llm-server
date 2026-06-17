import { useEffect, useState } from 'react';
import { getTabFromUrl, subscribeToRouteChanges } from '../lib/routing';

export function useTab() {
  const [tab, setTab] = useState(getTabFromUrl);

  useEffect(
    () =>
      subscribeToRouteChanges(() => {
        setTab(getTabFromUrl());
      }),
    [],
  );

  return tab;
}
