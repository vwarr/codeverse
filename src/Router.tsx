import { createBrowserRouter, createHashRouter, RouterProvider } from 'react-router-dom';
import { DEMO } from './lib/env';
import { FeedbackPage } from './pages/Feedback.page';
import { HistoryPage } from './pages/History.page';
import { HomePage } from './pages/Home.page';
import { InterviewPage } from './pages/Interview.page';
import { ReportPage } from './pages/Report.page';

// Static hosts have no SPA rewrite, so the demo build uses hash routes.
const router = (DEMO ? createHashRouter : createBrowserRouter)([
  { path: '/', element: <HomePage /> },
  { path: '/interview', element: <InterviewPage /> },
  { path: '/feedback', element: <FeedbackPage /> },
  { path: '/history', element: <HistoryPage /> },
  { path: '/report/:sessionId', element: <ReportPage /> },
]);

export function Router() {
  return <RouterProvider router={router} />;
}
