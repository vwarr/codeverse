import { clientId } from './clientId';

describe('clientId', () => {
  beforeEach(() => window.localStorage.clear());

  it('makes one random UUID per browser and keeps it', () => {
    const id = clientId();
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(clientId()).toBe(id);
    window.localStorage.clear();
    expect(clientId()).not.toBe(id);
  });
});
