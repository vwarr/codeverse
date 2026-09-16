import { useEffect, useRef } from 'react';
import { Box, ScrollArea, Stack, Text } from '@mantine/core';
import type { TranscriptTurn } from '../lib/types';

interface Props {
  turns: TranscriptTurn[];
  live: { candidate: string; interviewer: string };
  height?: number | string;
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
  const isYou = speaker === 'candidate';
  return (
    <Box style={{ opacity: partial ? 0.6 : 1 }}>
      <Text size="xs" c="dimmed" fw={600} tt="uppercase" style={{ letterSpacing: '.06em' }}>
        {isYou ? 'You' : 'Interviewer'}
      </Text>
      <Text size="sm">{text}</Text>
    </Box>
  );
}

export function Transcript({ turns, live, height = 320 }: Props) {
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' });
  }, [turns.length, live.candidate, live.interviewer]);

  return (
    <ScrollArea h={height} type="auto" offsetScrollbars>
      <Stack gap="sm" pr="xs">
        {turns.length === 0 && !live.candidate && !live.interviewer && (
          <Text size="sm" c="dimmed">
            The conversation will appear here.
          </Text>
        )}
        {turns.map((t, i) => (
          <Line key={`${i}-${t.t}`} speaker={t.role} text={t.text} />
        ))}
        {live.interviewer && <Line speaker="interviewer" text={live.interviewer} partial />}
        {live.candidate && <Line speaker="candidate" text={live.candidate} partial />}
        <div ref={bottom} />
      </Stack>
    </ScrollArea>
  );
}
