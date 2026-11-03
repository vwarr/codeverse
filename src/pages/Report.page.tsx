import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Button, Text } from '@mantine/core';
import { AppHeader } from '../components/AppHeader';
import { ReportView } from '../components/ReportView';
import { fetchProblem, fetchReport } from '../lib/api';
import type { Problem, ReportRecord } from '../lib/types';

/** A saved report, opened from the History page. */
export function ReportPage() {
  const { sessionId = '' } = useParams();
  const [record, setRecord] = useState<ReportRecord | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchReport(sessionId)
      .then((r) => {
        if (!alive) {
          return;
        }
        setRecord(r);
        fetchProblem(r.problemId)
          .then((p) => alive && setProblem(p))
          .catch(() => undefined);
      })
      .catch((e: Error) => alive && setError(`Could not load the report: ${e.message}`));
    return () => {
      alive = false;
    };
  }, [sessionId]);

  return (
    <>
      <AppHeader width={760}>
        <Link to="/history">History</Link>
      </AppHeader>
      {record ? (
        <ReportView
          title={problem?.title ?? record.problemId}
          track={record.track}
          difficulty={problem?.difficulty}
          report={record.report}
          finalRun={record.finalRun}
          metrics={record.metrics}
          transcript={record.transcript}
          createdAt={record.createdAt}
          error={
            record.status === 'failed'
              ? 'The report could not be written. The transcript is saved below.'
              : null
          }
          gradesFinalRun={record.track === 'debug'}
          actions={
            <Button component={Link} to="/" variant="default">
              New interview
            </Button>
          }
        />
      ) : (
        <main className="cv-page">
          <Text c={error ? 'accent.7' : 'dimmed'} role={error ? 'alert' : 'status'}>
            {error ?? 'Loading the report…'}
          </Text>
        </main>
      )}
    </>
  );
}
