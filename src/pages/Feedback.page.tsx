import { Link, Navigate } from 'react-router-dom';
import { Button } from '@mantine/core';
import { AppHeader } from '../components/AppHeader';
import { ReportView } from '../components/ReportView';
import { useInterview } from '../state/InterviewProvider';

/** The report for the interview that just ended (state from InterviewProvider). */
export function FeedbackPage() {
  const { state, reset } = useInterview();
  const { session } = state;

  if (!session) {
    return <Navigate to="/" replace />;
  }

  return (
    <>
      <AppHeader width={760}>
        <Link to="/history">History</Link>
      </AppHeader>
      <ReportView
        title={session.problem.title}
        track={session.track}
        difficulty={session.problem.difficulty}
        report={state.report}
        finalRun={state.finalRun}
        metrics={state.metrics}
        transcript={state.transcript}
        error={state.error}
        notice={
          state.wrapUpReason === 'quota'
            ? 'The interview ended early because the interviewer hit a usage limit. The report uses the conversation up to that point.'
            : state.wrapUpReason === 'connection_lost'
              ? 'The interview ended early because the voice connection was lost. The report uses the conversation up to that point.'
              : null
        }
        gradesFinalRun={session.track === 'debug'}
        actions={
          <Button component={Link} to="/" onClick={reset} variant="default">
            New interview
          </Button>
        }
      />
    </>
  );
}
