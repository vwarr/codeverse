import { Badge, Group, Text } from '@mantine/core';
import { InterviewState, STATUS_LABEL } from '../state/interview';

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

export function StatusBadge({
  status,
  connected,
}: {
  status: InterviewState['status'];
  connected: boolean;
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
    </Group>
  );
}
