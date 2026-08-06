import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {downloadTextFile} from './download';

/** Sentinel object URL returned by the stubbed `URL.createObjectURL`. */
const OBJECT_URL = 'blob:download-test';

function installObjectUrlAndAnchorSpies() {
  const createObjectURL = vi.fn((blob: Blob) => {
    expect(blob).toBeInstanceOf(Blob);
    return OBJECT_URL;
  });
  const revokeObjectURL = vi.fn();
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: createObjectURL,
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    value: revokeObjectURL,
  });
  const downloadedNames: string[] = [];
  const anchorClick = vi
    .spyOn(HTMLAnchorElement.prototype, 'click')
    .mockImplementation(function (this: HTMLAnchorElement) {
      downloadedNames.push(this.download);
    });
  return {createObjectURL, revokeObjectURL, downloadedNames, anchorClick};
}

describe('downloadTextFile', () => {
  let spies: ReturnType<typeof installObjectUrlAndAnchorSpies>;

  beforeEach(() => {
    spies = installObjectUrlAndAnchorSpies();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('hands the text to the browser as a file download', () => {
    downloadTextFile('goal-report.md', '# Report');

    expect(spies.createObjectURL).toHaveBeenCalledTimes(1);
    const blob = spies.createObjectURL.mock.calls[0][0];
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe('text/markdown;charset=utf-8');
    expect(spies.downloadedNames).toEqual(['goal-report.md']);
    expect(spies.anchorClick).toHaveBeenCalled();
  });

  it('revokes the object URL after the download is handed off', () => {
    downloadTextFile('goal-report.md', '# Report');

    expect(spies.revokeObjectURL).toHaveBeenCalledWith(OBJECT_URL);
  });

  it('honors a caller-supplied MIME type', () => {
    downloadTextFile('notes.txt', 'plain', 'text/plain;charset=utf-8');

    expect(spies.createObjectURL.mock.calls[0][0].type).toBe(
      'text/plain;charset=utf-8',
    );
  });
});
