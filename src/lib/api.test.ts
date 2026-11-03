import { apiUrl } from './api';

describe('apiUrl', () => {
  it('puts the API under the app base path', () => {
    expect(import.meta.env.BASE_URL).toBe('/codeverse/');
    expect(apiUrl('session')).toBe('/codeverse/api/session');
    expect(apiUrl('run_tests')).toBe('/codeverse/api/run_tests');
  });
});
