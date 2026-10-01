import { createBrowserRouter } from "react-router";
import { PublicLayout } from "./layouts/PublicLayout";
import { RouteError } from "../shared/components/RouteError";
import { RouteLoading } from "../shared/components/RouteLoading";
import { LoginPage, AuthErrorPage, PasswordPage } from "../features/m1/Auth";
import { AppsPage, AppPage } from "../features/m1/Apps";
import { ConnectorsPage, ReleasesPage } from "../features/m1/GitHub";
import {
  CatalogPage,
  CatalogAppPage,
  CatalogEntryPage,
  DebugListPage,
  DebugAdminPage,
} from "../features/m1/Debug";
import { FeishuPage } from "../features/m1/Feishu";
import {
  ActionsPage,
  BuildEventsPage,
  BuildEventPage,
} from "../features/m1/Actions";
import {
  SystemPage,
  TasksPage,
  TaskPage,
  NotificationsPage,
  NotificationPage,
  AuditPage,
  CachePage,
} from "../features/m1/Operations";
export const router = createBrowserRouter([
  {
    Component: PublicLayout,
    ErrorBoundary: RouteError,
    HydrateFallback: RouteLoading,
    children: [
      { index: true, Component: CatalogPage },
      { path: "login", Component: LoginPage },
      { path: "auth/error", Component: AuthErrorPage },
      { path: "apps/:id", Component: CatalogAppPage },
      { path: "debug/:id", Component: CatalogEntryPage },
      { path: "*", lazy: () => import("../shared/components/NotFoundPage") },
    ],
  },
  {
    path: "/admin",
    lazy: () => import("./layouts/AdminLayout"),
    ErrorBoundary: RouteError,
    HydrateFallback: RouteLoading,
    children: [
      { index: true, Component: SystemPage },
      { path: "apps", Component: AppsPage },
      { path: "apps/:id", Component: AppPage },
      { path: "apps/:id/releases", Component: ReleasesPage },
      { path: "apps/:id/debug", Component: DebugListPage },
      { path: "debug/:id", Component: DebugAdminPage },
      { path: "connectors", Component: ConnectorsPage },
      { path: "settings/feishu", Component: FeishuPage },
      { path: "apps/:id/actions", Component: ActionsPage },
      { path: "apps/:id/events", Component: BuildEventsPage },
      { path: "events/:id", Component: BuildEventPage },
      { path: "notifications", Component: NotificationsPage },
      { path: "notifications/:id", Component: NotificationPage },
      { path: "tasks", Component: TasksPage },
      { path: "tasks/:id", Component: TaskPage },
      { path: "audit", Component: AuditPage },
      { path: "settings/cache", Component: CachePage },
      { path: "settings/account", Component: PasswordPage },
      { path: "*", lazy: () => import("../shared/components/NotFoundPage") },
    ],
  },
]);
