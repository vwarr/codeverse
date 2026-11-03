import { Code, Group, Stack, Text } from '@mantine/core';
import type { RunResult, TestOutcome } from '../lib/types';

const STATUS_LABEL: Record<TestOutcome['status'], string> = {
  passed: 'Passed',
  failed: 'Failed',
  error: 'Error',
  skipped: 'Skipped',
};

interface Props {
  result: RunResult | null;
  running?: boolean;
  error?: string | null;
  emptyText?: string;
}

/** Results of the hidden test suite. Names and failure messages only; the tests stay hidden. */
export function TestResults({ result, running, error, emptyText }: Props) {
  if (error) {
    return (
      <Text size="sm" c="accent.7" role="alert">
        {error}
      </Text>
    );
  }
  if (!result) {
    return (
      <Text size="sm" c="dimmed">
        {running ? 'Running tests…' : (emptyText ?? 'No test run yet.')}
      </Text>
    );
  }

  const failing = result.outcomes.filter((o) => o.status === 'failed' || o.status === 'error');
  const passing = result.outcomes.filter((o) => o.status === 'passed');
  const headline = result.timed_out
    ? 'Timed out: the code ran for too long'
    : result.load_error
      ? 'The code did not load, so no tests ran'
      : `${result.passed} of ${result.total} tests passed`;

  return (
    <Stack gap="xs">
      <Group gap="sm" align="baseline">
        <Text size="sm" fw={600} c={result.ok ? undefined : 'accent.7'}>
          {headline}
        </Text>
        <Text size="xs" c="dimmed">
          {result.duration_ms} ms{running ? ' · running again…' : ''}
        </Text>
      </Group>
      {result.load_error && <Code block>{result.load_error}</Code>}
      {failing.map((o) => (
        <Stack key={o.name} gap={4}>
          <Text size="sm">
            <Text span fw={600} size="sm">
              {STATUS_LABEL[o.status]}
            </Text>{' '}
            <Text span ff="monospace" size="sm">
              {o.name}
            </Text>
          </Text>
          <Code block>{o.message}</Code>
        </Stack>
      ))}
      {passing.length > 0 && (
        <Text size="xs" c="dimmed">
          Passed: <span className="cv-mono">{passing.map((o) => o.name).join(', ')}</span>
        </Text>
      )}
      {result.stdout.trim() && (
        <Stack gap={2}>
          <Text size="xs" fw={600}>
            Printed output
          </Text>
          <Code block>{result.stdout}</Code>
        </Stack>
      )}
      {result.stderr.trim() && (
        <Stack gap={2}>
          <Text size="xs" fw={600}>
            Errors
          </Text>
          <Code block>{result.stderr}</Code>
        </Stack>
      )}
    </Stack>
  );
}
