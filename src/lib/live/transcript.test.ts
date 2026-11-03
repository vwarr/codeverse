import { cleanText, TranscriptBuilder } from './transcript';

describe('cleanText', () => {
  it('keeps the server spacing without doubled or missing spaces', () => {
    expect(cleanText('  Hello  there. ')).toBe('Hello there.');
    expect(cleanText('Okay.Next one?Yes')).toBe('Okay. Next one? Yes');
    expect(cleanText('Use arr.length and 3.5')).toBe('Use arr.length and 3.5');
  });
});

describe('TranscriptBuilder', () => {
  it('joins streamed fragments as they come', () => {
    const b = new TranscriptBuilder();
    b.input('I would ', 0);
    b.input(' run', 0.1);
    b.input(' the tests.', 0.2);
    expect(b.final()).toEqual([{ role: 'candidate', text: 'I would run the tests.', t: 0 }]);
  });

  it('adds a space where a tool call splits the interviewer line', () => {
    const b = new TranscriptBuilder();
    b.input('Look at it.', 0);
    b.output('Let me look.', 1);
    b.toolCall(1.1);
    b.turnComplete(1.2);
    b.output('Your loop', 1.5);
    b.output(', though, is fine.', 1.6);
    b.turnComplete(2);
    expect(b.final().map((t) => t.text)).toEqual([
      'Look at it.',
      'Let me look. Your loop, though, is fine.',
    ]);
  });

  it('closes the candidate turn when the transcription is finished', () => {
    const b = new TranscriptBuilder();
    b.input('One.', 0, true);
    expect(b.input('Two.', 0.1)).toBe(true);
    expect(b.final().map((t) => t.text)).toEqual(['One.', 'Two.']);
  });

  it('dates a late candidate line no later than the reply it caused', () => {
    const b = new TranscriptBuilder();
    b.modelOutput(5);
    b.output('Sure.', 5);
    b.turnComplete(6);
    b.input('Can I?', 6.5);
    expect(b.final()).toEqual([
      { role: 'candidate', text: 'Can I?', t: 5 },
      { role: 'interviewer', text: 'Sure.', t: 5 },
    ]);
  });

  it('drops empty lines', () => {
    const b = new TranscriptBuilder();
    b.modelOutput(0);
    b.interrupted();
    expect(b.hasContent()).toBe(false);
    expect(b.final()).toEqual([]);
  });
});
