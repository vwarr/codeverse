import { useMemo } from 'react';
import { marked } from 'marked';
import { Code, Stack, Text, Title, TypographyStylesProvider } from '@mantine/core';
import type { Problem } from '../lib/types';

const DIFFICULTY: Record<Problem['difficulty'], string> = {
  easy: 'Easy',
  medium: 'Medium',
  hard: 'Hard',
};

/**
 * The left column. A coding problem shows its statement and examples. A debugging problem shows
 * the bug report (the same `statement` field) and the module under test.
 */
export function ProblemPanel({ problem }: { problem: Problem }) {
  const html = useMemo(
    () => marked.parse(problem.statement, { async: false }) as string,
    [problem.statement]
  );
  const isBug = problem.track === 'debug';
  const meta = [DIFFICULTY[problem.difficulty], ...problem.tags].join(' · ');

  return (
    <Stack gap={18} fz={15} lh={1.6}>
      <Stack gap={4}>
        {isBug && (
          <Text size="sm" fw={600} c="dimmed">
            Bug report
          </Text>
        )}
        <Title order={1} fz={22} lh={1.25}>
          {problem.title}
        </Title>
        <Text size="sm" c="dimmed">
          {meta}
        </Text>
      </Stack>
      {isBug && problem.module_name && (
        <Text size="sm">
          Module: <span className="cv-mono">{problem.module_name}.py</span>. Press Run tests to run
          the test suite against the code in the editor.
        </Text>
      )}
      <TypographyStylesProvider p={0} fz={15}>
        {/* Statement markdown comes from our own problem bank, not from users. */}
        <div dangerouslySetInnerHTML={{ __html: html }} />
      </TypographyStylesProvider>
      {problem.examples.map((ex, i) => (
        <Stack key={i} gap={6}>
          <Title order={2} fz={14}>
            Example {i + 1}
          </Title>
          <Code block>
            {`Input:  ${ex.input}\nOutput: ${ex.output}`}
            {ex.explanation ? `\n${ex.explanation}` : ''}
          </Code>
        </Stack>
      ))}
      {problem.constraints.length > 0 && (
        <Stack gap={6}>
          <Title order={2} fz={14}>
            Constraints
          </Title>
          <ul className="cv-list">
            {problem.constraints.map((c) => (
              <li key={c}>
                <Text size="sm" component="span" className="cv-mono">
                  {c}
                </Text>
              </li>
            ))}
          </ul>
        </Stack>
      )}
    </Stack>
  );
}
