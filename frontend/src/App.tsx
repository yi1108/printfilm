import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import { useI18n } from './i18n'
import DialogHost from './components/ui/DialogHost'
import BillingAlertHost from './components/billing/BillingAlertHost'
import { DramaGenQueuePanel } from './components/drama/DramaGenQueuePanel'
import WeChatGroupFab from './components/layout/WeChatGroupFab'
import AuthPage from './pages/AuthPage'
import HistoryPage from './pages/HistoryPage'
import HomePage from './pages/HomePage'
import MethodPage from './pages/MethodPage'
import GenerationPage from './pages/GenerationPage'
import GenerationTasksPage from './pages/GenerationTasksPage'
import HelpPage from './pages/HelpPage'
import ContactPage from './pages/ContactPage'
import { PrivacyPage, TermsPage } from './pages/LegalDocPage'
import SettingsPage from './pages/SettingsPage'
import PricingPage from './pages/PricingPage'
import StudioPage from './pages/StudioPage'
import TemplatesPage from './pages/TemplatesPage'
import CreateProjectPage from './pages/studio/CreateProjectPage'
import CreationSessionEditorBridge from './pages/studio/CreationSessionEditorBridge'
import StyleConfigPage from './pages/studio/StyleConfigPage'
import StoryboardPage from './pages/studio/StoryboardPage'
import EditorPage from './pages/studio/EditorPage'
import DramaListPage from './pages/drama/DramaListPage'
import CanvasListPage from './pages/drama/CanvasListPage'
import AssetLibraryPage from './pages/drama/AssetLibraryPage'
import ProjectWorkspacePage from './pages/drama/ProjectWorkspacePage'
import EpisodeEditPage from './pages/drama/EpisodeEditPage'
import EpisodesPage from './pages/drama/EpisodesPage'
import PrintfilmStudioPage from './features/printfilm-studio/PrintfilmStudioPage'
import EpisodeStoryboardPage from './pages/drama/episodeCanvas/EpisodeStoryboardPage'
import ProjectInvitationPage from './features/printfilm-studio/ProjectInvitationPage'
import RequireAuth from './pages/drama/RequireAuth'
import './styles/printfilm.css'
import './App.css'

const Marketplace = lazy(() => import('./features/marketplace/Marketplace'))

/** 生成和余额均属于当前登录用户。 */
function PersonalBusinessOverlays() {
  return <><DramaGenQueuePanel /><BillingAlertHost /></>
}

/** 用户端路由及全局交互宿主；旧团队书签转向项目团队。 */
export default function App() {
  const { locale } = useI18n()
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/marketplace/*" element={<Suspense fallback={<p>{locale === 'en' ? 'Loading marketplace…' : '正在加载作品与招募…'}</p>}><Marketplace /></Suspense>} />
        <Route path="/" element={<HomePage />} />
        <Route path="/method" element={<MethodPage />} />
        <Route path="/auth" element={<AuthPage />} />
        <Route path="/templates" element={<TemplatesPage />} />
        <Route path="/tools/video" element={<RequireAuth><GenerationPage kind="video" /></RequireAuth>} />
        <Route path="/tools/image" element={<RequireAuth><GenerationPage kind="image" /></RequireAuth>} />
        <Route path="/tools/audio" element={<RequireAuth><GenerationPage kind="audio" /></RequireAuth>} />
        <Route path="/tasks" element={<RequireAuth><GenerationTasksPage /></RequireAuth>} />
        <Route path="/assets" element={<AssetLibraryPage />} />
        <Route path="/help" element={<HelpPage />} />
        <Route path="/contact" element={<ContactPage />} />
        <Route path="/terms" element={<TermsPage />} />
        <Route path="/privacy" element={<PrivacyPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/teams" element={<Navigate to="/settings?tab=team" replace />} />
        <Route path="/teams/join" element={<Navigate to="/settings?tab=team" replace />} />
        <Route path="/team-invitations" element={<Navigate to="/settings?tab=team" replace />} />
        <Route path="/teams/:teamId" element={<Navigate to="/settings?tab=team" replace />} />
        <Route path="/pricing" element={<PricingPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/studio/new" element={<CreateProjectPage />} />
        <Route path="/studio/sessions/:sessionId" element={<CreationSessionEditorBridge />} />
        <Route path="/studio/:id/style" element={<StyleConfigPage />} />
        <Route path="/studio/:id/editor" element={<EditorPage />} />
        <Route path="/studio/:id" element={<StoryboardPage />} />
        <Route path="/studio" element={<StudioPage />} />
        {/* Agent home (mirrors novel agent entry) */}
        <Route path="/drama" element={<DramaListPage />} />
        <Route path="/canvas" element={<CanvasListPage />} />
        <Route path="/canvas/join" element={<ProjectInvitationPage />} />
        <Route path="/drama/dramas" element={<DramaListPage />} />
        <Route path="/drama/assets" element={<AssetLibraryPage />} />
        <Route path="/drama/projects/:projectId" element={<ProjectWorkspacePage />} />
        <Route path="/drama/projects/:projectId/episodes" element={<EpisodesPage />} />
        <Route path="/drama/projects/:projectId/episodes/:episodeId" element={<EpisodeEditPage />} />
        <Route
          path="/drama/projects/:projectId/episodes/:episodeId/canvas"
          element={<EpisodeStoryboardPage />}
        />
        {/* Legacy URL remains routable for bookmarks but opens the new workspace. */}
        <Route path="/drama/projects/:projectId/canvas" element={<RequireAuth><PrintfilmStudioPage /></RequireAuth>} />
        <Route path="/drama/projects/:projectId/printfilm-studio" element={<RequireAuth><PrintfilmStudioPage /></RequireAuth>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <WeChatGroupFab />
      <PersonalBusinessOverlays />
      <DialogHost />
    </BrowserRouter>
  )
}
