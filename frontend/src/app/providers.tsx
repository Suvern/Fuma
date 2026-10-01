import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import type { PropsWithChildren } from 'react'

export function Providers({ children }: PropsWithChildren) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 30_000, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  }))
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}
