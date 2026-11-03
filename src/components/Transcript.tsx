import { useEffect, useRef } from 'react';
import { Stack, Text } from '@mantine/core';
import type { LiveTranscriptTurn } from '../lib/live/transcript';
import type { TranscriptTurn } from '../lib/types';

interface Props {
  turns: LiveTranscriptTurn[];
  live?: { candidate: string; interviewer: string };
  // Follow new lines (the interview); the report shows a static transcript.
  follow?: boolean;
}

function Line({
  speaker,
  text,
  partial,
}: {
  speaker: TranscriptTurn['role'];
  text: string;
  partial?: boolean;
}) {
  return (
    <Stack gap={4} opacity={partial ? 0.75 : 1}>
      <span className="cv-speaker" data-role={speaker}>
        {speaker === 'candidate' ? 'You' : 'Interviewer'}
      </span>
      <Text size="md" lh={1.55}>
        {text}
      </Text>
    </Stack>
  );
}

export function Transcript({ turns, live, follow = false }: Props) {
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (follow) {
      bottom.current?.scrollIntoView({ block: 'end' });
    }
  }, [follow, turns.length, live?.candidate, live?.interviewer]);

  const empty = turns.length === 0 && !live?.candidate && !live?.interviewer;
  return (
    <Stack gap={20}>
      {empty && (
        <Text size="sm" c="dimmed">
          The conversation will appear here.
        </Text>
      )}
      {turns.map((t, i) => (
        <Line key={`${i}-${t.t}`} speaker={t.role} text={t.text} partial={t.partial} />
      ))}
      {live?.interviewer && <Line speaker="interviewer" text={live.interviewer} partial />}
      {live?.candidate && <Line speaker="candidate" text={live.candidate} partial />}
      <div ref={bottom} />
    </Stack>
  );
}
