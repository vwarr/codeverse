import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Alert, Button, Group, Radio, Select, Stack, Text, Title } from '@mantine/core';
import { AppHeader } from '../components/AppHeader';
import { fetchProblems, fetchTracks } from '../lib/api';
import { DEMO } from '../lib/env';
import type { Difficulty, Problem, Track, TrackId } from '../lib/types';
import { useInterview } from '../state/InterviewProvider';

const RANDOM = '__random__';
const DIFFICULTIES: { value: Difficulty | 'any'; label: string }[] = [
  { value: 'easy', label: 'Easy' },
  { value: 'medium', label: 'Medium' },
  { value: 'hard', label: 'Hard' },
  { value: 'any', label: 'Any' },
];

export function HomePage() {
  const navigate = useNavigate();
  const { state, start } = useInterview();
  const [tracks, setTracks] = useState<Track[]>([]);
  const [trackId, setTrackId] = useState<TrackId>('swe');
  const [difficulty, setDifficulty] = useState<Difficulty | 'any'>('easy');
  const [problems, setProblems] = useState<Problem[]>([]);
  const [problemId, setProblemId] = useState<string>(RANDOM);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchTracks()
      .then(setTracks)
      .catch((e: Error) => setLoadError(`Could not reach the server: ${e.message}`));
  }, []);

  useEffect(() => {
    setProblemId(RANDOM);
    fetchProblems(trackId, difficulty === 'any' ? undefined : difficulty)
      .then(setProblems)
      .catch((e: Error) => setLoadError(`Could not load problems: ${e.message}`));
  }, [trackId, difficulty]);

  const problemOptions = useMemo(
    () => [
      {
        value: RANDOM,
        label: difficulty === 'any' ? 'Random problem' : `Random ${difficulty} problem`,
      },
      ...problems.map((p) => ({ value: p.id, label: p.title })),
    ],
    [problems, difficulty]
  );

  const onStart = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    const ack = await start({
      track: trackId,
      problemId: problemId === RANDOM ? undefined : problemId,
      difficulty: difficulty === 'any' ? undefined : difficulty,
    });
    setBusy(false);
    if (ack.ok) {
      navigate('/interview');
    }
  };

  const error = loadError ?? state.error;

  return (
    <>
      <AppHeader width={1080}>
        <Link to="/history">History</Link>
      </AppHeader>
      <main className="cv-start">
        <form className="cv-start-form" onSubmit={onStart}>
          <Stack gap={8}>
            <Title order={1}>Start a mock interview</Title>
            <Text size="md" c="dimmed">
              An AI interviewer you talk to, for coding and debugging interviews in Python.
            </Text>
            {DEMO && (
              <Text size="sm" c="dimmed">
                Demo: scripted interviewer, no microphone.
              </Text>
            )}
          </Stack>

          <fieldset className="cv-fieldset">
            <legend className="cv-legend">Track</legend>
            <Radio.Group value={trackId} onChange={(v) => setTrackId(v as TrackId)} name="track">
              <div className="cv-track-list">
                {tracks.map((t) => (
                  <label
                    key={t.id}
                    className="cv-track-row"
                    data-checked={t.id === trackId || undefined}
                  >
                    <Radio value={t.id} aria-describedby={`track-desc-${t.id}`} mt={3} />
                    <Stack gap={2}>
                      <Text size="md" fw={500}>
                        {t.name}
                      </Text>
                      <Text size="sm" c="dimmed" id={`track-desc-${t.id}`}>
                        {t.description}
                      </Text>
                    </Stack>
                  </label>
                ))}
              </div>
            </Radio.Group>
          </fieldset>

          <fieldset className="cv-fieldset">
            <legend className="cv-legend">Difficulty</legend>
            <Radio.Group
              value={difficulty}
              onChange={(v) => setDifficulty(v as Difficulty | 'any')}
              name="difficulty"
            >
              <div className="cv-difficulty">
                {DIFFICULTIES.map((d) => (
                  <Radio key={d.value} value={d.value} label={d.label} />
                ))}
              </div>
            </Radio.Group>
          </fieldset>

          <Select
            id="home-problem"
            label="Problem"
            description="All problems are in Python."
            data={problemOptions}
            value={problemId}
            onChange={(v) => setProblemId(v ?? RANDOM)}
            allowDeselect={false}
            searchable
            maw={420}
          />

          {error && (
            <Alert color="accent.7" title="Cannot start" role="alert">
              {error}
            </Alert>
          )}

          <Group gap="lg">
            <Button
              type="submit"
              size="md"
              loading={busy || state.status === 'starting'}
              disabled={!state.connected || !!loadError}
            >
              Start interview
            </Button>
            {state.mic === 'requesting' && (
              <Text size="sm" c="dimmed" role="status">
                Waiting for microphone permission…
              </Text>
            )}
          </Group>
        </form>
      </main>
    </>
  );
}
