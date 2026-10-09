import ConfigProvider from "@douyinfe/semi-ui-19/lib/es/configProvider";
import zhCN from "@douyinfe/semi-ui-19/lib/es/locale/source/zh_CN";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { PropsWithChildren } from "react";
import { SessionRenewal } from "../shared/components/SessionRenewal";

export function Providers({ children }: PropsWithChildren) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            staleTime: 30_000,
            refetchOnWindowFocus: false,
          },
          mutations: { retry: false },
        },
      }),
  );
  return (
    <ConfigProvider locale={zhCN}>
      <QueryClientProvider client={client}>
        <SessionRenewal />
        {children}
      </QueryClientProvider>
    </ConfigProvider>
  );
}
