import { ReactNode } from 'react';
import { Group, Loader, Stack, Text, Title } from '@mantine/core';
import type {
  Difficulty,
  FeedbackReport,
  RunResult,
  SessionMetrics,
  TrackId,
  TranscriptTurn,
} from '../lib/types';
import { TestResults } from './TestResults';
import { Transcript } from './Transcript';

export const TRACK_NAME: Record<TrackId, string> = {
  swe: 'Software engineering',
  debug: 'Debugging',
};

const DIFFICULTY_NAME: Record<Difficulty, string> = {
  easy: 'Easy',
  medium: 'Medium',
  hard: 'Hard',
};

export interface ReportViewProps {
  title: string;
  track: TrackId;
  difficulty?: Difficulty | null;
  report: FeedbackReport | null;
  finalRun: RunResult | null;
  metrics: SessionMetrics | null;
  transcript: TranscriptTurn[];
  createdAt?: string | null;
  error?: string | null;
  // Why the interview ended early, if it did (usage limit, lost connection).
  notice?: string | null;
  // Debugging track: the grader runs the suite again on the final code.
  gradesFinalRun: boolean;
  actions?: ReactNode;
}

function Section({
  title,
  children,
  rule,
}: {
  title: string;
  children: ReactNode;
  rule?: boolean;
}) {
  return (
    <section className={rule ? 'cv-section cv-section-rule' : 'cv-section'}>
      <Title order={2}>{title}</Title>
      {children}
    </section>
  );
}

/** The quiet report: summary line, rubric table, went well / work on, then the detail. */
export function ReportView(props: ReportViewProps) {
  const { report, metrics, finalRun } = props;
  const facts = [
    TRACK_NAME[props.track],
    props.difficulty ? DIFFICULTY_NAME[props.difficulty] : null,
    report ? `Overall ${report.overall_score}/5` : null,
    props.createdAt ? new Date(props.createdAt).toLocaleString() : null,
  ].filter(Boolean);

  return (
    <main className="cv-page">
      <Group justify="space-between" align="flex-start" gap={16}>
        <Stack gap={4}>
          <Title order={1} fz={28}>
            {props.title}
          </Title>
          <Text c="dimmed">{facts.join(' · ')}</Text>
        </Stack>
        {props.actions}
      </Group>

      {props.notice && (
        <div className="cv-banner" data-tone="alert" role="status">
          {props.notice}
        </div>
      )}

      {props.error && (
        <Text c="accent.7" role="alert">
          {props.error}
        </Text>
      )}

      {!report ? (
        !props.error && (
          <Stack gap="sm" align="flex-start" role="status">
            <Loader size="sm" color="ink.8" />
            <Text>Writing your report…</Text>
          </Stack>
        )
      ) : (
        <>
          <Text fz={17} lh={1.6} maw={640}>
            {report.summary}
          </Text>

          <Section title="Rubric">
            <table className="cv-table">
              <caption className="cv-visually-hidden">
                Scores for the {TRACK_NAME[props.track]} rubric, 1 to 5
              </caption>
              <thead>
                <tr>
                  <th scope="col">Dimension</th>
                  <th scope="col">Why</th>
                  <th scope="col" className="cv-num">
                    Score
                  </th>
                </tr>
              </thead>
              <tbody>
                {report.dimensions.map((d) => (
                  <tr key={d.name}>
                    <td className="cv-dim-name">{d.name}</td>
                    <td>
                      <Text size="sm" c="dimmed">
                        {d.justification}
                      </Text>
                    </td>
                    <td className="cv-num">{d.score}/5</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          <div className="cv-two-col">
            <Section title="Went well">
              <ul className="cv-list">
                {report.strengths.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </Section>
            <Section title="Work on">
              <ul className="cv-list">
                {report.improvements.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </Section>
          </div>
        </>
      )}

      {props.gradesFinalRun && (
        <Section title="Tests on your final code">
          <TestResults
            result={finalRun}
            emptyText={report ? 'The tests did not run on the final code.' : 'Running the tests…'}
          />
        </Section>
      )}

      {report && (
        <>
          <Section title="What a strong answer looks like">
            <Text className="cv-pre">{report.model_answer_sketch}</Text>
          </Section>

          {report.notable_moments.length > 0 && (
            <Section title="Notable moments">
              <Stack gap="md">
                {report.notable_moments.map((m, i) => (
                  <Stack key={i} gap={2}>
                    <Text component="blockquote" m={0} fs="italic">
                      “{m.quote}”
                    </Text>
                    <Text size="sm" c="dimmed">
                      {m.comment}
                    </Text>
                  </Stack>
                ))}
              </Stack>
            </Section>
          )}
        </>
      )}

      {metrics && (
        <Section title="Timing">
          <Text size="sm" c="dimmed">
            Median response time{' '}
            <Text span size="sm" c="var(--cv-text)" fw={500}>
              {metrics.response_latency_ms_p50 != null
                ? `${metrics.response_latency_ms_p50} ms`
                : 'not measured'}
            </Text>
            {metrics.response_latency_ms_max != null &&
              ` (slowest ${metrics.response_latency_ms_max} ms)`}{' '}
            · {metrics.model_turns} interviewer turns · you spoke for {metrics.audio_in_seconds} s
          </Text>
        </Section>
      )}

      <Section title="Transcript" rule>
        <Transcript turns={props.transcript} />
      </Section>
    </main>
  );
}
