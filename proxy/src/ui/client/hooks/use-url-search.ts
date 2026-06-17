import { useEffect, useState } from 'react';
import { subscribeToRouteChanges } from '../lib/routing';

export function useUrlSearch() {
  const [search, setSearch] = useState(() => window.location.search);

  useEffect(
    () =>
      subscribeToRouteChanges(() => {
        setSearch(window.location.search);
      }),
    [],
  );

  return search;
}
