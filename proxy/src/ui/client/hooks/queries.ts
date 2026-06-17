import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  checkBackendHealth,
  fetchAvailableModels,
  fetchBackendConfig,
  fetchDashboardData,
  fetchInvestmentData,
  saveBackendConfig,
  saveCostRates,
  saveInvestmentData,
} from '../lib/api';
import { TAB_DASHBOARD, TAB_QUERY_PARAM } from '../lib/constants';
import { queryKeys } from '../lib/query-keys';
import type {
  BackendConfigSaveBody,
  BackendHealthResult,
  CostRatesBody,
  DashboardData,
  InvestmentData,
  InvestmentSaveBody,
} from '../lib/types';
import { navigateToSearch } from '../lib/routing';
import { streamChatCompletion } from '../lib/chat';

export function useDashboardQuery(search: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.dashboard(search),
    queryFn: () => fetchDashboardData(search) as Promise<DashboardData>,
    enabled,
  });
}

export function useInvestmentQuery(enabled = true) {
  return useQuery({
    queryKey: queryKeys.investment,
    queryFn: () => fetchInvestmentData() as Promise<InvestmentData>,
    enabled,
  });
}

export function useModelsQuery(enabled = true) {
  return useQuery({
    queryKey: queryKeys.models,
    queryFn: fetchAvailableModels,
    enabled,
    staleTime: 60_000,
  });
}

export function useBackendConfigQuery(enabled = true) {
  return useQuery({
    queryKey: queryKeys.backendConfig,
    queryFn: fetchBackendConfig,
    enabled,
  });
}

export function useSaveBackendConfigMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: BackendConfigSaveBody) => saveBackendConfig(body),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.backendConfig, data);
    },
  });
}

export function useCheckBackendHealthMutation() {
  return useMutation({
    mutationFn: () => checkBackendHealth() as Promise<BackendHealthResult>,
  });
}

export function useSaveCostRatesMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: CostRatesBody) => saveCostRates(body),
    onSuccess: () => {
      const search = `?${TAB_QUERY_PARAM}=${TAB_DASHBOARD}&saved=1`;
      navigateToSearch(search);
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardAll });
    },
  });
}

export function useSaveInvestmentMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: InvestmentSaveBody) => saveInvestmentData(body) as Promise<InvestmentData>,
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.investment, data);
    },
  });
}

interface ChatStreamVariables {
  messages: Array<{ role: string; content: string }>;
  model: string;
  signal: AbortSignal;
  onChunk: (content: string) => void;
}

export function useChatCompletionMutation() {
  return useMutation({
    mutationFn: ({ messages, model, signal, onChunk }: ChatStreamVariables) =>
      streamChatCompletion(messages, model, onChunk, signal),
  });
}
