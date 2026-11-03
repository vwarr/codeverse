import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button, Group, Stack, Text, Title } from '@mantine/core';
import { AppHeader } from '../components/AppHeader';
import { TRACK_NAME } from '../components/ReportView';
import { fetchHistory } from '../lib/api';
import type { HistoryItem } from '../lib/types';

/** Past reports. There are no accounts: the list is the reports saved from this address. */
export function HistoryPage() {
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchHistory()
      .then(setItems)
      .catch((e: Error) => setError(`Could not load your reports: ${e.message}`));
  }, []);

  return (
    <>
      <AppHeader width={760} />
      <main className="cv-page">
        <Group justify="space-between" align="flex-start" gap={16}>
          <Stack gap={4}>
            <Title order={1} fz={28}>
              History
            </Title>
            <Text c="dimmed">Reports from interviews in this browser, newest first.</Text>
          </Stack>
          <Button component={Link} to="/" variant="default">
            New interview
          </Button>
        </Group>

        {error && (
          <Text c="accent.7" role="alert">
            {error}
          </Text>
        )}
        {!error && items === null && (
          <Text c="dimmed" role="status">
            Loading…
          </Text>
        )}
        {items?.length === 0 && (
          <Text>
            No reports yet. <Link to="/">Start an interview</Link>. Its report is saved here when it
            ends.
          </Text>
        )}
        {items && items.length > 0 && (
          <table className="cv-table">
            <caption className="cv-visually-hidden">Past interview reports</caption>
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">Problem</th>
                <th scope="col">Track</th>
                <th scope="col" className="cv-num">
                  Overall
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.sessionId}>
                  <td>
                    <Text size="sm" c="dimmed" span>
                      {new Date(it.createdAt).toLocaleDateString(undefined, {
                        day: 'numeric',
                        month: 'short',
                        year: 'numeric',
                      })}
                    </Text>
                  </td>
                  <td>
                    <Link to={`/report/${encodeURIComponent(it.sessionId)}`}>
                      {it.problemTitle}
                    </Link>
                  </td>
                  <td>{TRACK_NAME[it.track] ?? it.track}</td>
                  <td className="cv-num">
                    {it.overallScore != null ? `${it.overallScore}/5` : 'Pending'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </main>
    </>
  );
}
