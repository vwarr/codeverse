import { Badge, Group, Text } from '@mantine/core';
import { InterviewState, MicState, STATUS_LABEL } from '../state/interview';

const COLOR: Record<InterviewState['status'], string> = {
  idle: 'gray',
  starting: 'gray',
  connecting: 'gray',
  listening: 'green',
  thinking: 'yellow',
  speaking: 'violet',
  wrapping_up: 'orange',
  ended: 'blue',
  error: 'red',
};

const MIC_LABEL: Record<MicState, string | null> = {
  off: null,
  requesting: 'asking for the microphone…',
  on: null,
  denied: 'microphone blocked',
  unsupported: 'no microphone support',
};

export function StatusBadge({
  status,
  connected,
  mic,
}: {
  status: InterviewState['status'];
  connected: boolean;
  mic: MicState;
}) {
  return (
    <Group gap="xs">
      <Badge color={COLOR[status]} variant="filled" size="lg" radius="sm">
        {STATUS_LABEL[status]}
      </Badge>
      {!connected && (
        <Text size="xs" c="red">
          backend offline
        </Text>
      )}
      {MIC_LABEL[mic] && (
        <Text size="xs" c={mic === 'requesting' ? 'dimmed' : 'red'}>
          {MIC_LABEL[mic]}
        </Text>
      )}
    </Group>
  );
}
