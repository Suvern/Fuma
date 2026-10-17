import { createBrowserRouter } from "react-router";
import { PublicLayout } from "./layouts/PublicLayout";
import { RouteError } from "../shared/components/RouteError";
import { RouteLoading } from "../shared/components/RouteLoading";
import { LoginPage, AuthErrorPage } from "../features/m1/Auth";
import { LegacyReleasesRedirect } from "./LegacyReleasesRedirect";
export const router = createBrowserRouter([
  {
    Component: PublicLayout,
    ErrorBoundary: RouteError,
    HydrateFallback: RouteLoading,
    children: [
      {
        path: "docs/github-actions",
        lazy: async () => ({
          Component: (await import("../features/m1/ActionsGuide"))
            .ActionsDocumentationPage,
        }),
      },
      {
        index: true,
        lazy: async () => ({
          Component: (await import("../features/m1/Debug")).CatalogPage,
        }),
      },
      {
        path: "releases",
        lazy: async () => ({
          Component: (await import("../features/library/Library"))
            .PublishedReleasesPage,
        }),
      },
      {
        path: "releases/:id",
        lazy: async () => ({
          Component: (await import("../features/library/Library"))
            .PublishedReleasePage,
        }),
      },
      { path: "login", Component: LoginPage },
      { path: "auth/error", Component: AuthErrorPage },
      {
        path: "apps/:id",
        lazy: async () => ({
          Component: (await import("../features/m1/Debug")).CatalogAppPage,
        }),
      },
      {
        path: "debug/:id",
        lazy: async () => ({
          Component: (await import("../features/m1/Debug")).CatalogEntryPage,
        }),
      },
      { path: "*", lazy: () => import("../shared/components/NotFoundPage") },
    ],
  },
  {
    path: "/admin",
    lazy: () => import("./layouts/AdminLayout"),
    ErrorBoundary: RouteError,
    HydrateFallback: RouteLoading,
    children: [
      {
        index: true,
        lazy: () => import("../features/system/pages/AdminHomePage"),
      },
      {
        path: "apps",
        lazy: async () => ({
          Component: (await import("../features/m1/Apps")).AppsPage,
        }),
      },
      {
        path: "apps/:id",
        lazy: async () => ({
          Component: (await import("../features/m1/Apps")).AppPage,
        }),
      },
      {
        path: "apps/:id/releases",
        Component: LegacyReleasesRedirect,
      },
      {
        path: "apps/:id/debug",
        lazy: async () => ({
          Component: (await import("../features/m1/Debug")).DebugListPage,
        }),
      },
      {
        path: "debug/:id",
        lazy: async () => ({
          Component: (await import("../features/m1/Debug")).DebugAdminPage,
        }),
      },
      {
        path: "apps/:id/packages",
        lazy: async () => ({
          Component: (await import("../features/library/Library")).PackagesPage,
        }),
      },
      {
        path: "apps/:id/versions",
        lazy: async () => ({
          Component: (await import("../features/library/Library")).VersionsPage,
        }),
      },
      {
        path: "versions/:id",
        lazy: async () => ({
          Component: (await import("../features/library/Library")).VersionPage,
        }),
      },
      {
        path: "settings/storage",
        lazy: async () => ({
          Component: (await import("../features/library/Storage")).StoragePage,
        }),
      },
      {
        path: "connectors",
        lazy: async () => ({
          Component: (await import("../features/m1/Connectors")).ConnectorsPage,
        }),
      },
      {
        path: "settings/feishu",
        lazy: async () => ({
          Component: (await import("../features/m1/Feishu")).FeishuPage,
        }),
      },
      {
        path: "apps/:id/actions",
        lazy: async () => ({
          Component: (await import("../features/m1/Actions")).ActionsPage,
        }),
      },
      {
        path: "apps/:id/notifications",
        lazy: async () => ({
          Component: (await import("../features/m1/NotificationTemplate")).AppNotificationTemplatePage,
        }),
      },
      {
        path: "apps/:id/events",
        lazy: async () => ({
          Component: (await import("../features/m1/Actions")).BuildEventsPage,
        }),
      },
      {
        path: "events/:id",
        lazy: async () => ({
          Component: (await import("../features/m1/Actions")).BuildEventPage,
        }),
      },
      {
        path: "notifications",
        lazy: async () => ({
          Component: (await import("../features/m1/Operations"))
            .NotificationsPage,
        }),
      },
      {
        path: "notifications/:id",
        lazy: async () => ({
          Component: (await import("../features/m1/Operations"))
            .NotificationPage,
        }),
      },
      {
        path: "tasks",
        lazy: async () => ({
          Component: (await import("../features/m1/Operations")).TasksPage,
        }),
      },
      {
        path: "tasks/:id",
        lazy: async () => ({
          Component: (await import("../features/m1/Operations")).TaskPage,
        }),
      },
      {
        path: "audit",
        lazy: async () => ({
          Component: (await import("../features/m1/Operations")).AuditPage,
        }),
      },
      {
        path: "settings/cache",
        lazy: async () => ({
          Component: (await import("../features/m1/Operations")).CachePage,
        }),
      },
      {
        path: "settings/account",
        lazy: async () => ({
          Component: (await import("../features/m1/Account")).AccountPage,
        }),
      },
      {
        path: "settings/members",
        lazy: async () => ({
          Component: (await import("../features/m1/Members")).MembersPage,
        }),
      },
      { path: "*", lazy: () => import("../shared/components/NotFoundPage") },
    ],
  },
]);
