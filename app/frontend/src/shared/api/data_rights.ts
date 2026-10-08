import {browserSettings} from '@/shared/lib/browser_data';
import {API_BASE_URL, clientHeaders, fetchJson, fetchWithSession} from './runs';

export async function exportMyData(): Promise<Blob> {
  const response = await fetchWithSession(`${API_BASE_URL}/api/data/export`, {
    method: 'POST',
    headers: {...clientHeaders(), 'Content-Type': 'application/json'},
    body: JSON.stringify(browserSettings()),
  });
  if (!response.ok)
    throw new Error(
      'The export could not be prepared. Please try again shortly.',
    );
  return response.blob();
}

export function deleteMyData(): Promise<{deleted: boolean}> {
  return fetchJson('/api/data/delete', {
    method: 'POST',
    headers: {...clientHeaders(), 'Content-Type': 'application/json'},
    body: JSON.stringify({confirmation: 'DELETE'}),
  });
}
