import {describe, it, expect} from 'vitest';
import {
  capitalizeTerm,
  conciseTitle,
  filenameSlug,
  readableText,
  readableTextList,
} from './text';

describe('conciseTitle', () => {
  it('returns a short goal unchanged', () => {
    expect(conciseTitle('Cellular aging therapies')).toBe(
      'Cellular aging therapies',
    );
  });

  it('takes the first clause of a multi-clause goal', () => {
    expect(
      conciseTitle('Reversing liver fibrosis; detail the mechanism.'),
    ).toBe('Reversing liver fibrosis');
  });

  it('truncates a long goal on a word boundary with an ellipsis', () => {
    const out = conciseTitle(
      'Identify novel mechanisms of selective autophagy in aging neural ' +
        'tissue.',
    );
    expect(out.endsWith('…')).toBe(true);
    expect(out.length).toBeLessThanOrEqual(53);
    expect(out.startsWith('Identify novel mechanisms')).toBe(true);
    // No dangling short connector word before the ellipsis.
    expect(out).not.toMatch(/\b(in|of|to|a|the)…$/);
  });

  it('falls back for empty input', () => {
    expect(conciseTitle('')).toBe('Untitled session');
    expect(conciseTitle('   ')).toBe('Untitled session');
  });
});

describe('readableText', () => {
  it('passes a well-formed string through unchanged', () => {
    expect(readableText('Guards against assay-specific artefacts.')).toBe(
      'Guards against assay-specific artefacts.',
    );
  });

  it('flattens a JSON-string field into plain text', () => {
    const raw =
      '{"significance": "Confirms the core assumption", "gap": "None"}';
    expect(readableText(raw)).toBe('Confirms the core assumption - None');
  });

  it('flattens an object field into plain text', () => {
    expect(
      readableText({significance: 'Blocks a redundant pathway', priority: 3}),
    ).toBe('Blocks a redundant pathway - 3');
  });

  it('returns an empty string for nullish input', () => {
    expect(readableText(null)).toBe('');
    expect(readableText(undefined)).toBe('');
  });

  it('leaves a string with a stray brace but invalid JSON intact', () => {
    expect(readableText('Targets {RelA} to resensitize cells')).toBe(
      'Targets {RelA} to resensitize cells',
    );
  });
});

describe('readableTextList', () => {
  it('keeps a normal list of strings', () => {
    expect(
      readableTextList(['Run a perturbation series.', 'Quantify it.']),
    ).toEqual(['Run a perturbation series.', 'Quantify it.']);
  });

  it('flattens list items that are objects', () => {
    expect(
      readableTextList([
        {experiment: 'Delete relA', rationale: 'test tolerance'},
      ]),
    ).toEqual(['Delete relA - test tolerance']);
  });

  it('parses a JSON-array string into items', () => {
    expect(readableTextList('["Assay A", "Assay B"]')).toEqual([
      'Assay A',
      'Assay B',
    ]);
  });

  it('treats a plain string as a single item and nullish as empty', () => {
    expect(readableTextList('Just one experiment')).toEqual([
      'Just one experiment',
    ]);
    expect(readableTextList(null)).toEqual([]);
    expect(readableTextList(undefined)).toEqual([]);
  });
});

describe('capitalizeTerm', () => {
  it('capitalizes a lowercase noun phrase', () => {
    // The model capitalizes its preference sentences and leaves focus-area
    // terms lowercase, so the two lists in one specification card disagreed
    // about their own house style.
    expect(capitalizeTerm('gut-brain axis')).toBe('Gut-brain axis');
  });

  it('leaves a Greek-letter prefix alone', () => {
    // Uppercasing it yields a Greek capital alpha, which is a different
    // character and not how the term is set anywhere in the literature.
    expect(capitalizeTerm('α-synuclein aggregation')).toBe(
      'α-synuclein aggregation',
    );
  });

  it('leaves an intentionally mixed-case term alone', () => {
    expect(capitalizeTerm('mRNA stability')).toBe('mRNA stability');
    expect(capitalizeTerm('pH-dependent binding')).toBe('pH-dependent binding');
  });

  it('leaves an already-capitalized sentence unchanged', () => {
    expect(capitalizeTerm('Prioritize mechanistic novelty.')).toBe(
      'Prioritize mechanistic novelty.',
    );
  });
});

describe('filenameSlug', () => {
  it('lowercases and dash-separates words', () => {
    expect(filenameSlug('Glucose Homeostasis Study')).toBe(
      'glucose-homeostasis-study',
    );
  });

  it('strips punctuation and collapses separator runs', () => {
    expect(filenameSlug('Cold stress: a  model?!')).toBe('cold-stress-a-model');
  });

  it('caps the slug length on a separator boundary', () => {
    const slug = filenameSlug('word '.repeat(60).trim());
    expect(slug.length).toBeLessThanOrEqual(80);
    expect(slug.endsWith('-')).toBe(false);
  });

  it('returns an empty string when nothing slug-worthy remains', () => {
    expect(filenameSlug('')).toBe('');
    expect(filenameSlug('  ')).toBe('');
    expect(filenameSlug('///')).toBe('');
  });
});
