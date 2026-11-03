import '@mantine/core/styles.css';
import './global.css';

import { MantineProvider } from '@mantine/core';
import { Router } from './Router';
import { InterviewProvider } from './state/InterviewProvider';
import { theme } from './theme';

export default function App() {
  return (
    <MantineProvider theme={theme} forceColorScheme="light">
      <InterviewProvider>
        <Router />
      </InterviewProvider>
    </MantineProvider>
  );
}
