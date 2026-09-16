import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { FeedbackPage } from './pages/Feedback.page';
import { HomePage } from './pages/Home.page';
import { InterviewPage } from './pages/Interview.page';

const router = createBrowserRouter([
  { path: '/', element: <HomePage /> },
  { path: '/interview', element: <InterviewPage /> },
  { path: '/feedback', element: <FeedbackPage /> },
]);

export function Router() {
  return <RouterProvider router={router} />;
}
