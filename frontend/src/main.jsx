import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { Toaster } from 'react-hot-toast'
import { BrowserRouter } from 'react-router-dom'

import App from '@/App'
import '@/lib/i18n'
import '@/styles/index.css'
import 'nprogress/nprogress.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Video metadata changes rarely; a minute of staleness saves a lot of
      // refetching while browsing back and forth.
      staleTime: 60_000,
      retry: (failureCount, error) => {
        const status = error?.response?.status
        // Never retry an auth/permission/not-found answer — it will not change.
        if (status && status >= 400 && status < 500) return false
        return failureCount < 2
      },
      refetchOnWindowFocus: false,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
        <Toaster
          position="bottom-right"
          toastOptions={{
            duration: 4000,
            style: {
              background: '#1a1a27',
              color: '#e9e9f2',
              border: '1px solid #262637',
              fontSize: '0.875rem',
            },
            success: { iconTheme: { primary: '#22c55e', secondary: '#0b0b12' } },
            error: { iconTheme: { primary: '#ef4444', secondary: '#0b0b12' } },
          }}
        />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
