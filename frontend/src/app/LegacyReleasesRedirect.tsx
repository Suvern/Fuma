import { Navigate, useParams } from "react-router";

/** Redirect old GitHub Releases bookmarks to the COS-first versions page. */
export function LegacyReleasesRedirect() {
  const { id = "" } = useParams();
  return <Navigate to={`/admin/apps/${id}/versions`} replace />;
}
