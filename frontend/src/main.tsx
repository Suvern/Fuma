import "./app/semi";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router/dom";
import { Providers } from "./app/providers";
import { router } from "./app/router";
import "@douyinfe/semi-ui-19/lib/es/_base/base.css";
import "./app/styles.css";
import "./app/app-tabs.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Providers>
      <RouterProvider router={router} />
    </Providers>
  </StrictMode>,
);
