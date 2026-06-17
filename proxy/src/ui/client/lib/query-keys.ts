export const queryKeys = {
  dashboard: (search: string) => ['dashboard', search] as const,
  dashboardAll: ['dashboard'] as const,
  investment: ['investment'] as const,
  models: ['models'] as const,
  backendConfig: ['backendConfig'] as const,
};
