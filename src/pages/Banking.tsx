import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Center, Text } from '@mantine/core';
import pfp from '../components/pfp.jpg';
import { socket } from '../lib/socket';

import './pulsingCircle.css';

// The interview is started from the Home page (one start_interview emit). This
// page only reflects state and offers Finish.
function IBInterview() {
  const navigate = useNavigate();
  const [audioPlaying, setAudioPlaying] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onStatus = (data: { status?: string }) => setAudioPlaying(data.status === 'Status 3');
    const onFeedback = (data: { text?: string }) => setFeedback(data.text ?? null);
    const onError = (data: { message?: string }) => setError(data.message ?? 'Unknown error');
    socket.on('status_update', onStatus);
    socket.on('feedback', onFeedback);
    socket.on('error', onError);
    return () => {
      socket.off('status_update', onStatus);
      socket.off('feedback', onFeedback);
      socket.off('error', onError);
    };
  }, []);

  const endInterview = () => {
    socket.emit('end_interview');
  };

  return (
    <div style={{ position: 'relative', height: '100vh' }}>
      <div style={{ position: 'absolute', top: '20px', right: '20px', zIndex: 2 }}>
        {feedback ? (
          <Button size="lg" radius="xl" onClick={() => navigate('/')}>
            Back to home
          </Button>
        ) : (
          <Button
            size="lg"
            radius="xl"
            variant="gradient"
            gradient={{ from: '#266181', to: '#58D3E3' }}
            onClick={endInterview}
          >
            Finish Interview
          </Button>
        )}
      </div>

      <Center style={{ height: '100%', flexDirection: 'column' }}>
        <div style={{ position: 'relative', width: 200, height: 200, marginBottom: 40 }}>
          <div className={audioPlaying ? 'pulsing-circle active' : 'pulsing-circle'} />
          <img
            src={pfp}
            alt="Interviewer"
            style={{
              width: '200px',
              height: '200px',
              borderRadius: '50%',
              objectFit: 'cover',
              position: 'relative',
              zIndex: 1,
            }}
          />
        </div>
        {feedback && (
          <Text size="lg" style={{ maxWidth: 640, textAlign: 'center' }}>
            {feedback}
          </Text>
        )}
        {error && (
          <Text c="red" style={{ maxWidth: 640, textAlign: 'center' }}>
            {error}
          </Text>
        )}
      </Center>
    </div>
  );
}

export default IBInterview;
