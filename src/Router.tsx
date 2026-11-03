import { createBrowserRouter, createHashRouter, RouterProvider } from 'react-router-dom';
import { DEMO } from './lib/env';
import { FeedbackPage } from './pages/Feedback.page';
import { HistoryPage } from './pages/History.page';
import { HomePage } from './pages/Home.page';
import { InterviewPage } from './pages/Interview.page';
import { ReportPage } from './pages/Report.page';

const routes = [
  { path: '/', element: <HomePage /> },
  { path: '/interview', element: <InterviewPage /> },
  { path: '/feedback', element: <FeedbackPage /> },
  { path: '/history', element: <HistoryPage /> },
  { path: '/report/:sessionId', element: <ReportPage /> },
];

// The app is served under Vite's base (/codeverse/), so browser routes carry it as the basename:
// <Link to="/history"> and navigate('/feedback') resolve to /codeverse/history and /codeverse/feedback.
const basename = import.meta.env.BASE_URL.replace(/\/$/, '') || '/';

// Static hosts have no SPA rewrite, so the demo build uses hash routes. Hash routes live after the
// '#', so they need no basename.
const router = DEMO ? createHashRouter(routes) : createBrowserRouter(routes, { basename });

export function Router() {
  return <RouterProvider router={router} />;
}
