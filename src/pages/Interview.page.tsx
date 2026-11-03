import { useEffect, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { Button, Text, Title, Tooltip } from '@mantine/core';
import { AppHeader } from '../components/AppHeader';
import { CodePane } from '../components/CodePane';
import { ProblemPanel } from '../components/ProblemPanel';
import { TestResults } from '../components/TestResults';
import { Transcript } from '../components/Transcript';
import { DEMO } from '../lib/env';
import { formatClock, isLive, secondsLeft, statusLine } from '../state/interview';
import { useInterview } from '../state/InterviewProvider';

const WARN_SECONDS = 5 * 60;

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) {
      return undefined;
    }
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

export function InterviewPage() {
  const navigate = useNavigate();
  const { state, finish, sendCode, runTests, setMuted } = useInterview();
  const { session, status } = state;
  const running = status !== 'ended' && status !== 'error' && status !== 'idle';
  const now = useNow(running);

  useEffect(() => {
    if (status === 'ended') {
      navigate('/feedback');
    }
  }, [status, navigate]);

  if (!session) {
    return <Navigate to="/" replace />;
  }

  const live = isLive(status) && status !== 'wrapping_up' && !state.reconnecting;
  const canFinish = running && status !== 'wrapping_up';
  const left = secondsLeft(state, now);
  const micOn = state.mic === 'on';
  const fileName = session.problem.module_name
    ? `${session.problem.module_name}.py`
    : 'solution.py';

  return (
    <div className="cv-interview">
      <AppHeader>
        <Text role="status" size="sm" fw={500}>
          {statusLine(state)}
        </Text>
        {left != null && (
          <Text size="sm" c="dimmed" ff="monospace" aria-label={`Time left: ${formatClock(left)}`}>
            {formatClock(left)} left
          </Text>
        )}
        {micOn ? (
          <Button
            variant="default"
            size="sm"
            h={36}
            aria-pressed={state.muted}
            onClick={() => setMuted(!state.muted)}
          >
            {state.muted ? 'Unmute' : 'Mute'}
          </Button>
        ) : (
          // Same layout as a live interview; the demo (and a stopped mic) has nothing to mute.
          <Tooltip label={DEMO ? 'The demo does not use the microphone' : 'The microphone is off'}>
            <Button
              variant="default"
              size="sm"
              h={36}
              data-disabled
              aria-disabled="true"
              onClick={(e) => e.preventDefault()}
            >
              Mute
            </Button>
          </Tooltip>
        )}
        <Button size="sm" h={36} onClick={finish} disabled={!canFinish}>
          {status === 'wrapping_up' ? 'Wrapping up…' : 'Finish'}
        </Button>
      </AppHeader>

      <div aria-live="polite">
        {state.reconnecting && (
          <div className="cv-banner" data-tone="alert">
            The voice connection dropped. Reconnecting to the same interview; your code and the
            transcript are kept.
          </div>
        )}
        {status === 'wrapping_up' && state.wrapUpReason === 'interviewer' && (
          <div className="cv-banner">
            The interviewer has started the wrap-up. Listen to the summary; your written report
            follows.
          </div>
        )}
        {status === 'wrapping_up' && state.wrapUpReason === 'time_limit' && (
          <div className="cv-banner">Time is up. The interviewer is wrapping up.</div>
        )}
        {left != null && left > 0 && left <= WARN_SECONDS && status !== 'wrapping_up' && (
          <div className="cv-banner">
            {Math.ceil(left / 60)} minutes left. The interviewer will start the wrap-up at 0:00.
          </div>
        )}
        {state.muted && live && (
          <div className="cv-banner">
            Your microphone is muted. The interviewer cannot hear you.
          </div>
        )}
      </div>
      {(state.error || state.mic === 'denied' || state.mic === 'unsupported') && (
        <div className="cv-banner" data-tone="alert" role="alert">
          {state.error ??
            'The microphone is not available. Allow it for this site in the browser settings.'}
        </div>
      )}

      <div className="cv-columns">
        <section
          aria-label={session.track === 'debug' ? 'Bug report' : 'Problem'}
          className="cv-col cv-col-problem"
        >
          <ProblemPanel problem={session.problem} />
        </section>

        <section aria-label="Editor" className="cv-col cv-col-editor">
          <CodePane
            starterCode={session.problem.starter_code}
            onChange={sendCode}
            fileName={fileName}
            onRun={session.canRun ? (code) => void runTests(code) : undefined}
            running={state.running}
            runDisabled={!live}
          />
          <div className="cv-output" aria-live="polite">
            <Title order={2} fz={13} mb={6}>
              Output
            </Title>
            {session.canRun ? (
              <TestResults
                result={state.lastRun}
                running={state.running}
                error={state.runError}
                emptyText={
                  session.track === 'debug'
                    ? 'Press Run tests to run the test suite against your code.'
                    : 'Press Run tests to run the hidden test cases against your code.'
                }
              />
            ) : (
              <Text size="sm" c="dimmed">
                This problem has no automatic tests. Walk the interviewer through an example
                instead.
              </Text>
            )}
          </div>
        </section>

        <section aria-label="Transcript" className="cv-col cv-col-transcript">
          <Title order={2} fz={14} mb={20}>
            Transcript
          </Title>
          <Transcript turns={state.transcript} live={state.live} follow />
        </section>
      </div>
    </div>
  );
}
