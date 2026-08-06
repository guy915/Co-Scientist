// Pre-run document staging (`/api/documents`).
//
// A document attached in the composer is uploaded here, before any run
// exists: the chat quotes it while scoping the goal, and creating the run
// carries it into that run's private corpus. Uploading only after the run
// existed put the scientist's own material behind the plan it was meant to
// shape, and made run setup a sequence whose middle step could fail.

import {clientHeaders, fetchJson} from './runs_http';

/** A document staged against the caller, before any run exists. */
export interface StagedDocument {
  id: string;
  title: string;
  sha256: string;
  byte_size: number;
  mime_type: string;
  extraction_tool: string;
}

/**
 * Uploads and extracts one document, staged against the calling client.
 *
 * @param file The document to stage.
 * @returns The staged document's id and extraction provenance.
 */
export function stageDocument(file: File): Promise<StagedDocument> {
  const body = new FormData();
  body.set('file', file);
  body.set('consent', 'true');
  return fetchJson('/api/documents', {
    method: 'POST',
    headers: clientHeaders(),
    body,
  });
}
