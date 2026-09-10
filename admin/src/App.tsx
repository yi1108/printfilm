import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { AdminLayout } from "@/components/layout/AdminLayout";
import { getCachedUser, getToken, isAdminUser } from "@/lib/auth";
import { FinanceListPage } from "@/pages/FinanceListPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { LoginPage } from "@/pages/LoginPage";
import { OrdersPage } from "@/pages/OrdersPage";
import { ProjectsPage } from "@/pages/ProjectsPage";
import { DramaProjectsPage } from "@/pages/DramaProjectsPage";
import { DramaAssetDetailPage } from "@/pages/drama/DramaAssetDetailPage";
import { DramaAssetsPage } from "@/pages/drama/DramaAssetsPage";
import { DramaEpisodeDetailPage } from "@/pages/drama/DramaEpisodeDetailPage";
import { DramaEpisodesPage } from "@/pages/drama/DramaEpisodesPage";
import { DramaFragmentDetailPage } from "@/pages/drama/DramaFragmentDetailPage";
import { DramaFragmentsPage } from "@/pages/drama/DramaFragmentsPage";
import { DramaProjectDetailPage } from "@/pages/drama/DramaProjectDetailPage";
import { QueuesPage } from "@/pages/QueuesPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { TemplatesPage } from "@/pages/TemplatesPage";
import { UsersPage } from "@/pages/UsersPage";
import { WorksPage } from "@/pages/WorksPage";

// Guard: require JWT + admin role
function RequireAdmin() {
  const token = getToken();
  const user = getCachedUser();
  if (!token || !isAdminUser(user)) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}

// Admin app routes
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAdmin />}>
        <Route element={<AdminLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="users" element={<UsersPage />} />
          <Route path="orders" element={<OrdersPage />} />
          <Route path="finance" element={<FinanceListPage />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="drama-projects" element={<DramaProjectsPage />} />
          <Route path="drama-projects/:projectId" element={<DramaProjectDetailPage />} />
          <Route path="drama-assets" element={<DramaAssetsPage />} />
          <Route path="drama-assets/:assetId" element={<DramaAssetDetailPage />} />
          <Route path="drama-episodes" element={<DramaEpisodesPage />} />
          <Route path="drama-episodes/:episodeId" element={<DramaEpisodeDetailPage />} />
          <Route path="drama-fragments" element={<DramaFragmentsPage />} />
          <Route path="drama-fragments/:fragmentId" element={<DramaFragmentDetailPage />} />
          <Route path="works" element={<WorksPage />} />
          <Route path="templates" element={<TemplatesPage />} />
          <Route path="queues" element={<QueuesPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
