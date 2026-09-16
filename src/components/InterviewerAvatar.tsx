import pfp from './pfp.jpg';

import './pulsingCircle.css';

export function InterviewerAvatar({ speaking, size = 200 }: { speaking: boolean; size?: number }) {
  return (
    <div style={{ position: 'relative', width: size, height: size }}>
      <div className={speaking ? 'pulsing-circle active' : 'pulsing-circle'} />
      <img
        src={pfp}
        alt="Interviewer"
        style={{
          width: size,
          height: size,
          borderRadius: '50%',
          objectFit: 'cover',
          position: 'relative',
          zIndex: 1,
        }}
      />
    </div>
  );
}
