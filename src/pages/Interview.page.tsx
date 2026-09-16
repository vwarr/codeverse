import { useEffect } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Center,
  Group,
  ScrollArea,
  Stack,
  Switch,
  Text,
  Title,
  useMantineColorScheme,
} from '@mantine/core';
import { CodePane } from '../components/CodePane';
import logo from '../components/icon.png';
import { InterviewerAvatar } from '../components/InterviewerAvatar';
import { ProblemPanel } from '../components/ProblemPanel';
import { StatusBadge } from '../components/StatusBadge';
import { Transcript } from '../components/Transcript';
import { useInterview } from '../state/InterviewProvider';

const HEADER_H = 56;

export function InterviewPage() {
  const navigate = useNavigate();
  const { state, finish, sendCode } = useInterview();
  const { colorScheme, toggleColorScheme } = useMantineColorScheme();
  const { session, status } = state;

  useEffect(() => {
    if (status === 'ended') {
      navigate('/feedback');
    }
  }, [status, navigate]);

  if (!session) {
    return <Navigate to="/" replace />;
  }

  const isEditor = session.problem.track === 'swe';
  const speaking = status === 'speaking' || (status === 'wrapping_up' && !!state.live.interviewer);
  const canFinish = status !== 'ended' && status !== 'error' && status !== 'wrapping_up';

  return (
    <Box style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Group
        px="md"
        justify="space-between"
        style={{ height: HEADER_H, backgroundColor: '#2D3F93', color: 'white', flex: '0 0 auto' }}
      >
        <Group gap="sm">
          <Link to="/">
            <img src={logo} alt="codeverse" style={{ height: 32, display: 'block' }} />
          </Link>
          <Title order={4} c="white">
            codeverse
          </Title>
        </Group>
        <StatusBadge status={status} connected={state.connected} />
        <Group gap="md">
          <Switch
            label="Dark"
            checked={colorScheme === 'dark'}
            onChange={toggleColorScheme}
            styles={{ label: { color: 'white' } }}
          />
          <Button
            size="sm"
            radius="xl"
            variant="white"
            color="dark"
            onClick={finish}
            disabled={!canFinish}
          >
            {status === 'wrapping_up' ? 'Wrapping up…' : 'Finish'}
          </Button>
        </Group>
      </Group>

      {state.error && (
        <Alert color="red" m="sm">
          {state.error}
        </Alert>
      )}

      {isEditor ? (
        <Box
          style={{
            flex: 1,
            minHeight: 0,
            display: 'grid',
            gridTemplateColumns: 'minmax(280px, 1fr) 2fr',
          }}
        >
          <ScrollArea
            p="md"
            style={{ borderRight: '1px solid var(--mantine-color-default-border)' }}
          >
            <Stack gap="lg">
              <ProblemPanel problem={session.problem} />
              <div>
                <Text fw={600} size="sm" mb={6}>
                  Transcript
                </Text>
                <Transcript turns={state.transcript} live={state.live} height={260} />
              </div>
            </Stack>
          </ScrollArea>
          <CodePane
            initialLanguage={session.language}
            starterCode={session.problem.starter_code}
            onChange={sendCode}
          />
        </Box>
      ) : (
        <Center style={{ flex: 1, minHeight: 0 }} p="md">
          <Stack align="center" gap="lg" style={{ width: 'min(720px, 100%)' }}>
            <InterviewerAvatar speaking={speaking} />
            <Text fw={600}>{session.problem.title}</Text>
            <Box style={{ width: '100%' }}>
              <Transcript turns={state.transcript} live={state.live} height={300} />
            </Box>
          </Stack>
        </Center>
      )}
    </Box>
  );
}
