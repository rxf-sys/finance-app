import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ApiError, meQueryKey } from "@/api/client";
import { applyTheme, readTheme } from "@/lib/theme";
import { makeRouter } from "@/router";
import "./index.css";

applyTheme(readTheme());

// A 401 from any request means the session ended: back to the login page.
function handleError(error: Error) {
  if (error instanceof ApiError && error.status === 401) {
    queryClient.setQueryData(meQueryKey, null);
    void router.navigate({ to: "/login" });
  }
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: handleError }),
  mutationCache: new MutationCache({ onError: handleError }),
  defaultOptions: {
    queries: {
      // Client errors (401, 403, 404) will not fix themselves on retry.
      retry: (failureCount, error) => !(error instanceof ApiError && error.status < 500) && failureCount < 2,
    },
  },
});
const router = makeRouter(queryClient);

const root = document.getElementById("root");
if (!root) {
  throw new Error("Root element #root missing in index.html");
}

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
