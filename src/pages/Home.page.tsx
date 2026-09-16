import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Container,
  Group,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import bgImage from '../components/background.png';
import { LANGUAGES } from '../components/CodePane';
import { fetchProblems, fetchTracks } from '../lib/api';
import type { Difficulty, Problem, Track, TrackId } from '../lib/types';
import { useInterview } from '../state/InterviewProvider';

const RANDOM = '__random__';

export function HomePage() {
  const navigate = useNavigate();
  const { state, start } = useInterview();
  const [tracks, setTracks] = useState<Track[]>([]);
  const [trackId, setTrackId] = useState<TrackId>('swe');
  const [difficulty, setDifficulty] = useState<Difficulty | 'any'>('easy');
  const [problems, setProblems] = useState<Problem[]>([]);
  const [problemId, setProblemId] = useState<string>(RANDOM);
  const [language, setLanguage] = useState('python');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchTracks()
      .then(setTracks)
      .catch((e: Error) => setLoadError(`Could not reach the backend: ${e.message}`));
  }, []);

  useEffect(() => {
    setProblemId(RANDOM);
    fetchProblems(trackId, difficulty === 'any' ? undefined : difficulty)
      .then(setProblems)
      .catch((e: Error) => setLoadError(`Could not load problems: ${e.message}`));
  }, [trackId, difficulty]);

  const track = useMemo(() => tracks.find((t) => t.id === trackId), [tracks, trackId]);
  const problemOptions = useMemo(
    () => [
      {
        value: RANDOM,
        label: `Random ${difficulty === 'any' ? '' : difficulty} problem`.replace('  ', ' '),
      },
      ...problems.map((p) => ({ value: p.id, label: p.title })),
    ],
    [problems, difficulty]
  );

  const onStart = async () => {
    setBusy(true);
    const ack = await start({
      track: trackId,
      problemId: problemId === RANDOM ? undefined : problemId,
      difficulty: difficulty === 'any' ? undefined : difficulty,
      language,
    });
    setBusy(false);
    if (ack.ok) {
      navigate('/interview');
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        backgroundImage: `url(${bgImage})`,
        backgroundSize: 'cover',
        backgroundPosition: 'bottom',
        display: 'flex',
        alignItems: 'center',
      }}
    >
      <Container size="sm" py="xl">
        <Stack gap="lg">
          <div>
            <Title order={1} c="white">
              codeverse
            </Title>
            <Text c="gray.3">AI mock interviewer for software engineering and finance roles.</Text>
          </div>

          <Card withBorder radius="md" p="lg">
            <Stack gap="md">
              <SimpleGrid cols={{ base: 1, sm: 3 }}>
                {(tracks.length ? tracks : []).map((t) => (
                  <Card
                    key={t.id}
                    withBorder
                    radius="md"
                    p="sm"
                    onClick={() => setTrackId(t.id)}
                    style={{
                      cursor: 'pointer',
                      borderColor: t.id === trackId ? 'var(--mantine-color-blue-6)' : undefined,
                      borderWidth: t.id === trackId ? 2 : 1,
                    }}
                  >
                    <Text fw={600}>{t.name}</Text>
                    <Text size="xs" c="dimmed">
                      {t.description}
                    </Text>
                  </Card>
                ))}
              </SimpleGrid>

              <Group grow align="flex-end">
                <div>
                  <Text size="sm" fw={500} mb={4}>
                    Difficulty
                  </Text>
                  <SegmentedControl
                    fullWidth
                    value={difficulty}
                    onChange={(v) => setDifficulty(v as Difficulty | 'any')}
                    data={[
                      { value: 'easy', label: 'Easy' },
                      { value: 'medium', label: 'Medium' },
                      { value: 'hard', label: 'Hard' },
                      { value: 'any', label: 'Any' },
                    ]}
                  />
                </div>
                {track?.surface === 'editor' && (
                  <Select
                    id="home-language"
                    label="Language"
                    data={LANGUAGES}
                    value={language}
                    onChange={(v) => v && setLanguage(v)}
                    allowDeselect={false}
                  />
                )}
              </Group>

              <Select
                id="home-problem"
                label={track?.surface === 'editor' ? 'Problem' : 'Topic'}
                data={problemOptions}
                value={problemId}
                onChange={(v) => setProblemId(v ?? RANDOM)}
                allowDeselect={false}
                searchable
              />

              {(loadError || state.error) && (
                <Alert color="red" title="Cannot start">
                  {loadError ?? state.error}
                </Alert>
              )}

              <Button
                size="lg"
                radius="xl"
                onClick={onStart}
                loading={busy || state.status === 'starting'}
                disabled={!state.connected || !!loadError}
              >
                Start interview
              </Button>
              {!state.connected && (
                <Text size="xs" c="dimmed" ta="center">
                  Waiting for the backend…
                </Text>
              )}
            </Stack>
          </Card>
        </Stack>
      </Container>
    </div>
  );
}
