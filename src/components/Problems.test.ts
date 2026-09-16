import { problemDescriptions } from './Problems';

describe('problem bank', () => {
  it('every problem has a statement with at least one example', () => {
    for (const [name, text] of Object.entries(problemDescriptions)) {
      expect(text.trim().length, name).toBeGreaterThan(40);
      expect(text, name).toContain('Example 1');
    }
  });

  it('max profit example is correct', () => {
    expect(problemDescriptions['Max Profit from Stock Prices']).toContain('Output: 5\n');
  });
});
