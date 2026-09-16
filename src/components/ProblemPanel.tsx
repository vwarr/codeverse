import { useMemo } from 'react';
import { marked } from 'marked';
import { Badge, Code, Group, Stack, Text, Title, TypographyStylesProvider } from '@mantine/core';
import type { Problem } from '../lib/types';

const DIFFICULTY_COLOR: Record<Problem['difficulty'], string> = {
  easy: 'teal',
  medium: 'yellow',
  hard: 'red',
};

export function ProblemPanel({ problem }: { problem: Problem }) {
  const html = useMemo(
    () => marked.parse(problem.statement, { async: false }) as string,
    [problem.statement]
  );

  return (
    <Stack gap="sm">
      <Group gap="xs" align="center">
        <Title order={3}>{problem.title}</Title>
        <Badge color={DIFFICULTY_COLOR[problem.difficulty]} variant="light">
          {problem.difficulty}
        </Badge>
      </Group>
      {problem.tags.length > 0 && (
        <Group gap={6}>
          {problem.tags.map((t) => (
            <Badge key={t} size="sm" variant="outline" color="gray">
              {t}
            </Badge>
          ))}
        </Group>
      )}
      <TypographyStylesProvider>
        {/* Statement markdown comes from our own problem bank, not from users. */}
        <div dangerouslySetInnerHTML={{ __html: html }} />
      </TypographyStylesProvider>
      {problem.examples.map((ex, i) => (
        <Stack key={i} gap={2}>
          <Text fw={600} size="sm">
            Example {i + 1}
          </Text>
          <Code block>
            {`Input: ${ex.input}\nOutput: ${ex.output}`}
            {ex.explanation ? `\nExplanation: ${ex.explanation}` : ''}
          </Code>
        </Stack>
      ))}
      {problem.constraints.length > 0 && (
        <Stack gap={2}>
          <Text fw={600} size="sm">
            Constraints
          </Text>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {problem.constraints.map((c) => (
              <li key={c}>
                <Text size="sm" component="span">
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
