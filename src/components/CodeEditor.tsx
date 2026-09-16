import { useEffect, useState } from 'react';
import Editor from '@monaco-editor/react';
import { IconAlertCircle } from '@tabler/icons-react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Container,
  Grid,
  Group,
  Select,
  Stack,
  Switch,
  Text,
  Title,
  useMantineColorScheme,
} from '@mantine/core';
import logo from '../components/icon.png';
import { socket } from '../lib/socket';
import { problemDescriptions, ProblemKey } from './Problems';

const languageOptions = [
  { value: 'python', label: 'Python' },
  { value: 'java', label: 'Java' },
  { value: 'cpp', label: 'C++' },
  { value: 'javascript', label: 'JavaScript' },
  { value: 'typescript', label: 'TypeScript' },
];

const CodeEditor = () => {
  const [language, setLanguage] = useState('python');
  const { colorScheme, toggleColorScheme } = useMantineColorScheme();
  const monacoTheme = colorScheme === 'dark' ? 'vs-dark' : 'vs';
  const [interviewActive, setInterviewActive] = useState(true);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  type MessageStatus = {
    message: string;
    color: string;
  };
  const messageStatus: Record<string, MessageStatus> = {
    'Status 0': { message: 'AI Speaking.', color: '#6171C1' },
    'Status 1': { message: 'Speak now.', color: '#00FF00' },
    'Status 2': { message: 'AI Thinking.', color: '#FFA500' },
    'Status 3': { message: 'AI Speaking.', color: '#BF40BF' },
  };
  const [status, setStatus] = useState('Status 0');

  const navigate = useNavigate();
  const location = useLocation();
  // The Home page chose the problem and already sent it with start_interview.
  const problemName = ((location.state as { problem?: ProblemKey } | null)?.problem ??
    'Two Sum') as ProblemKey;
  const problemText = problemDescriptions[problemName] ?? '';

  useEffect(() => {
    const onStatus = (data: { status?: string }) => {
      if (data.status) {
        setStatus(data.status);
      }
    };
    const onFeedback = (data: { text?: string }) => setFeedback(data.text ?? null);
    const onEnded = () => setInterviewActive(false);
    const onError = (data: { message?: string }) => setError(data.message ?? 'Unknown error');
    socket.on('status_update', onStatus);
    socket.on('feedback', onFeedback);
    socket.on('interview_ended', onEnded);
    socket.on('error', onError);
    return () => {
      socket.off('status_update', onStatus);
      socket.off('feedback', onFeedback);
      socket.off('interview_ended', onEnded);
      socket.off('error', onError);
    };
  }, []);

  // Send code to the backend as the candidate types.
  const handleCodeChange = (newValue: string | undefined) => {
    socket.emit('send_code', { code: newValue ?? '' });
  };

  const endInterview = () => {
    socket.emit('end_interview');
  };

  return (
    <Container fluid px={0} style={{ height: '100vh' }}>
      {/* Title Section - Full Width */}

      <Box
        style={{
          width: '100%',
          padding: '5px',
          backgroundColor: '#2D3F93', // Corrected color
          borderBottom: '2px solid #ddd',
          marginBottom: '10px',
          color: 'gray',
        }}
      >
        <Group
          align="center"
          style={{
            width: '100%',
            justifyContent: 'center',
            paddingLeft: '20px',
            paddingRight: '20px',
          }}
        >
          {/* Left Side: Logo & Dropdown */}
          <Group>
            <Link to="/">
              <img src={logo} alt="Logo" style={{ height: '40px' }} />
            </Link>
          </Group>

          {/* Centered Title */}
          <Title style={{ color: '#FFFFFF' }} order={1}>
            codeverse
          </Title>
        </Group>
      </Box>

      {/* Main Layout - Two Columns */}
      <Grid grow gutter="xs">
        {/* Left Column - Problem Description */}
        <Grid.Col span={4}>
          <Container style={{ paddingTop: '20px' }}>
            <Title
              order={2}
              size="h2"
              style={{
                fontFamily: 'Verdana, sans-serif',
                fontWeight: '600',
                fontSize: '25px',
                color: colorScheme === 'dark' ? '#FFFFFF' : '#000000', // Dynamically change color
                lineHeight: '1.5',
                marginBottom: '10px',
              }}
            >
              {problemName}
            </Title>
            <Text
              size="xl"
              style={{
                fontFamily: 'Verdana, sans-serif',
                color: colorScheme === 'dark' ? '#FFFFFF' : '#000000', // Dynamically change color
                fontSize: '15px',
                lineHeight: '1.5',
                whiteSpace: 'pre-line',
              }}
            >
              {problemText}
            </Text>
            {feedback && (
              <Text mt="lg" size="md" fw={600}>
                Interviewer feedback: {feedback}
              </Text>
            )}
            {error && (
              <Text mt="lg" c="red">
                {error}
              </Text>
            )}
          </Container>
        </Grid.Col>

        {/* Right Column - Code Editor */}
        <Grid.Col span={8}>
          <Container fluid style={{ height: '100vh', padding: 0 }}>
            <Stack style={{ height: '100%', justifyContent: 'space-between' }}>
              {/* Controls: Language Selector & Dark Mode Toggle */}
              <Group style={{ justifyContent: 'space-between', padding: '10px' }}>
                <Switch
                  label="Dark Mode"
                  checked={colorScheme === 'dark'}
                  onChange={toggleColorScheme}
                />
                <Select
                  label="Select Language"
                  placeholder="Choose a language"
                  data={languageOptions}
                  value={language}
                  onChange={(value) => setLanguage(value || 'javascript')}
                  style={{ width: 150 }}
                />
                {/*<Select
                  label="Difficulty"
                  data={["Easy", "Medium", "Hard"]}
                  placeholder="Select difficulty"
                  style={{ width: 150 }}
                />*/}

                <Group>
                  <IconAlertCircle
                    size={24}
                    color={messageStatus[status]?.color}
                    style={{ marginRight: '10px' }}
                  />
                  <Text size="lg" style={{ color: messageStatus[status]?.color }}>
                    {messageStatus[status]?.message}
                  </Text>
                </Group>

                {interviewActive ? (
                  <Button
                    size="lg"
                    radius="xl"
                    variant="gradient"
                    gradient={{ from: '#2D3F93', to: '#1E3A8A' }}
                    onClick={endInterview}
                  >
                    Finish
                  </Button>
                ) : (
                  <Button size="lg" radius="xl" onClick={() => navigate('/')}>
                    Back to home
                  </Button>
                )}
              </Group>

              {/* Monaco Editor */}
              <div
                className="monaco-editor-wrapper"
                style={{ borderTop: '4px solid #888078', paddingTop: '5px' }}
              >
                <Editor
                  height="calc(100vh - 80px)"
                  language={language}
                  defaultValue="# Type your solution here"
                  onChange={handleCodeChange}
                  theme={monacoTheme}
                  options={{
                    lineNumbers: 'on',
                    minimap: { enabled: false },
                    fontSize: 14,
                    scrollBeyondLastLine: false,
                  }}
                />
              </div>
            </Stack>
          </Container>
        </Grid.Col>
      </Grid>
    </Container>
  );
};

export default CodeEditor;
