import { Link, Navigate } from 'react-router-dom';
import {
  Badge,
  Button,
  Card,
  Container,
  Group,
  List,
  Loader,
  Progress,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Transcript } from '../components/Transcript';
import { useInterview } from '../state/InterviewProvider';

function Score({ value }: { value: number }) {
  const color = value >= 4 ? 'teal' : value >= 3 ? 'yellow' : 'red';
  return (
    <Group gap="xs" wrap="nowrap">
      <Progress value={(value / 5) * 100} color={color} w={90} size="sm" />
      <Text size="sm" fw={600} style={{ fontVariantNumeric: 'tabular-nums' }}>
        {value}/5
      </Text>
    </Group>
  );
}

export function FeedbackPage() {
  const { state, reset } = useInterview();
  const { session, report, metrics } = state;

  if (!session) {
    return <Navigate to="/" replace />;
  }

  return (
    <Container size="md" py="xl">
      <Stack gap="lg">
        <Group justify="space-between" align="flex-start">
          <div>
            <Title order={2}>Interview report</Title>
            <Text c="dimmed">
              {session.problem.title} · {session.track.toUpperCase()}
            </Text>
          </div>
          <Button component={Link} to="/" onClick={reset} variant="light">
            New interview
          </Button>
        </Group>

        {state.error && (
          <Card withBorder c="red">
            {state.error}
          </Card>
        )}

        {!report ? (
          <Card withBorder>
            <Group>
              <Loader size="sm" />
              <Text>Writing your report…</Text>
            </Group>
          </Card>
        ) : (
          <>
            <Card withBorder>
              <Group justify="space-between" mb="sm">
                <Title order={3}>Overall</Title>
                <Badge
                  size="xl"
                  variant="filled"
                  color={
                    report.overall_score >= 4
                      ? 'teal'
                      : report.overall_score >= 3
                        ? 'yellow'
                        : 'red'
                  }
                >
                  {report.overall_score} / 5
                </Badge>
              </Group>
              <Text>{report.summary}</Text>
            </Card>

            <Card withBorder>
              <Title order={4} mb="sm">
                Rubric
              </Title>
              <Stack gap="sm">
                {report.dimensions.map((d) => (
                  <Group key={d.name} justify="space-between" align="flex-start" wrap="nowrap">
                    <div style={{ flex: 1 }}>
                      <Text fw={600} size="sm">
                        {d.name}
                      </Text>
                      <Text size="sm" c="dimmed">
                        {d.justification}
                      </Text>
                    </div>
                    <Score value={d.score} />
                  </Group>
                ))}
              </Stack>
            </Card>

            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <Card withBorder>
                <Title order={4} mb="xs">
                  Strengths
                </Title>
                <List size="sm">
                  {report.strengths.map((s) => (
                    <List.Item key={s}>{s}</List.Item>
                  ))}
                </List>
              </Card>
              <Card withBorder>
                <Title order={4} mb="xs">
                  Work on next
                </Title>
                <List size="sm">
                  {report.improvements.map((s) => (
                    <List.Item key={s}>{s}</List.Item>
                  ))}
                </List>
              </Card>
            </SimpleGrid>

            <Card withBorder>
              <Title order={4} mb="xs">
                What a strong answer looks like
              </Title>
              <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                {report.model_answer_sketch}
              </Text>
            </Card>

            {report.notable_moments.length > 0 && (
              <Card withBorder>
                <Title order={4} mb="xs">
                  Notable moments
                </Title>
                <Stack gap="sm">
                  {report.notable_moments.map((m, i) => (
                    <div key={i}>
                      <Text size="sm" fs="italic">
                        “{m.quote}”
                      </Text>
                      <Text size="sm" c="dimmed">
                        {m.comment}
                      </Text>
                    </div>
                  ))}
                </Stack>
              </Card>
            )}
          </>
        )}

        <Card withBorder>
          <Title order={4} mb="xs">
            Transcript
          </Title>
          <Transcript
            turns={state.transcript}
            live={{ candidate: '', interviewer: '' }}
            height={360}
          />
        </Card>

        {metrics && (
          <Text size="xs" c="dimmed">
            {metrics.model_turns} interviewer turns · {metrics.audio_in_seconds}s spoken by you ·{' '}
            {metrics.audio_out_seconds}s by the interviewer
            {metrics.response_latency_ms_p50 != null &&
              ` · median response ${metrics.response_latency_ms_p50} ms`}
          </Text>
        )}
      </Stack>
    </Container>
  );
}
