import { useNavigate } from 'react-router-dom';
import { Button, Center, Container, Overlay, Stack, Text } from '@mantine/core';
import bgImage from '../components/background.png';
import { problemDescriptions, ProblemKey } from '../components/Problems';
import { socket } from '../lib/socket';

function pickRandomProblem(): ProblemKey {
  const keys = Object.keys(problemDescriptions) as ProblemKey[];
  return keys[Math.floor(Math.random() * keys.length)];
}

export function HomePage() {
  const navigate = useNavigate();

  const handleStartInterview = () => {
    // Choose the problem here and send it with start_interview, so the backend
    // builds its prompt from the right question before the editor even mounts.
    const problem = pickRandomProblem();
    socket.emit('start_interview', { track: 'swe', problem });
    navigate('/editor', { state: { problem } });
  };

  const handleStartBankInterview = () => {
    socket.emit('start_interview', { track: 'ib', problem: 'Investment Banking Interview' });
    navigate('/banking');
  };

  return (
    <div
      style={{
        position: 'relative',
        height: '100vh',
        backgroundImage: `url(${bgImage})`,
        backgroundSize: 'cover',
        backgroundPosition: 'bottom',
      }}
    >
      <Overlay opacity={0.0} color="#000" zIndex={1} />
      <Center
        style={{
          height: '100vh',
          position: 'relative',
          zIndex: 2,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'flex-end',
          padding: '0 20px',
        }}
      >
        <Container>
          <Stack align="center" style={{ marginTop: '-75%' }}>
            <Container>
              <Text size="lg" c="gray.3" style={{ maxWidth: 600, textAlign: 'center' }}>
                AI mock interviewer for SWE and finance roles
              </Text>
              <Button
                size="lg"
                radius="xl"
                variant="gradient"
                gradient={{ from: '#FF4500 ', to: '#FF4500' }}
                onClick={handleStartInterview}
                style={{ marginTop: '15px', marginRight: '20px' }}
              >
                Start SWE Interview
              </Button>
              <Button
                size="lg"
                radius="xl"
                variant="gradient"
                gradient={{ from: '#FF4500', to: '#FF4500' }}
                onClick={handleStartBankInterview}
                style={{ marginTop: '15px' }}
              >
                Start IB Interview
              </Button>
            </Container>
          </Stack>
        </Container>
      </Center>
    </div>
  );
}
