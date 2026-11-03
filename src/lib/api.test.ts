import { apiUrl, endSession } from './api';

describe('apiUrl', () => {
  it('puts the API under the app base path', () => {
    expect(import.meta.env.BASE_URL).toBe('/codeverse/');
    expect(apiUrl('session')).toBe('/codeverse/api/session');
    expect(apiUrl('run_tests')).toBe('/codeverse/api/run_tests');
  });
});

describe('endSession', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('sends a JSON beacon to /api/end when asked', async () => {
    const beacon = vi.fn((_url: string, _data?: BodyInit | null) => true);
    Object.defineProperty(navigator, 'sendBeacon', { value: beacon, configurable: true });
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    endSession('s1', { beacon: true });
    expect(beacon).toHaveBeenCalledTimes(1);
    const [url, blob] = beacon.mock.calls[0];
    expect(url).toBe('/codeverse/api/end');
    expect((blob as Blob).type).toBe('application/json');
    const text = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blob as Blob);
    });
    expect(JSON.parse(text)).toEqual({ sessionId: 's1' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('falls back to a keepalive POST, and swallows errors', async () => {
    Object.defineProperty(navigator, 'sendBeacon', { value: () => false, configurable: true });
    const fetchMock = vi.fn(async () => {
      throw new Error('offline');
    });
    vi.stubGlobal('fetch', fetchMock);
    endSession('s1', { beacon: true });
    endSession('s2');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenLastCalledWith('/codeverse/api/end', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId: 's2' }),
      keepalive: true,
    });
    await Promise.resolve();
  });
});
