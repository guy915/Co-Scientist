import {describe, it, expect} from 'vitest';
import {
  capitalizeTerm,
  conciseTitle,
  readableText,
  readableTextList,
  splitAbstractSections,
} from './text';

describe('text', () => {
  describe('conciseTitle', () => {
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
      expect(out).not.toMatch(/\b(in|of|to|a|the)…$/);
    });

    it('falls back for empty input', () => {
      expect(conciseTitle('')).toBe('Untitled session');
      expect(conciseTitle('   ')).toBe('Untitled session');
    });
  });

  describe('readableText', () => {
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

    it('leaves a string with a stray brace but invalid JSON intact', () => {
      expect(readableText('Targets {RelA} to resensitize cells')).toBe(
        'Targets {RelA} to resensitize cells',
      );
    });
  });

  describe('readableTextList', () => {
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
  });

  describe('capitalizeTerm', () => {
    it('capitalizes a lowercase noun phrase', () => {
      expect(capitalizeTerm('gut-brain axis')).toBe('Gut-brain axis');
    });

    it('leaves a Greek-letter prefix alone', () => {
      // Greek alpha stays lowercase in scientific literature.
      expect(capitalizeTerm('α-synuclein aggregation')).toBe(
        'α-synuclein aggregation',
      );
    });

    it('leaves an intentionally mixed-case term alone', () => {
      expect(capitalizeTerm('mRNA stability')).toBe('mRNA stability');
      expect(capitalizeTerm('pH-dependent binding')).toBe(
        'pH-dependent binding',
      );
    });
  });
});

describe('format abstract', () => {
  it('returns a single unlabeled section for unstructured text', () => {
    const result = splitAbstractSections('A plain abstract without labels.');
    expect(result).toEqual([
      {label: null, html: 'A plain abstract without labels.'},
    ]);
  });

  it('separates an all-caps label run into the body (real data)', () => {
    const raw =
      'SUMMARYThe global resurgence of drug-resistant tuberculosis (DR-TB) ' +
      'in <i>Mycobacterium tuberculosis</i> (Mtb) is a challenge.';
    const result = splitAbstractSections(raw);
    expect(result).toHaveLength(1);
    expect(result[0].label).toBe('Summary');
    expect(result[0].html).toBe(
      'The global resurgence of drug-resistant tuberculosis (DR-TB) in ' +
        '<i>Mycobacterium tuberculosis</i> (Mtb) is a challenge.',
    );
  });

  it('splits double-space title-case sections (real data)', () => {
    const raw =
      'Background  Major depressive disorder and ALS show comorbidity. ' +
      'Methods  Using large-scale GWAS we applied MAGMA. ' +
      'Results  Synaptic pruning emerged as the signal. ' +
      'Conclusions  These findings support a continuum model.';
    const result = splitAbstractSections(raw);
    expect(result.map(s => s.label)).toEqual([
      'Background',
      'Methods',
      'Results',
      'Conclusions',
    ]);
    expect(result[0].html).toBe(
      'Major depressive disorder and ALS show comorbidity.',
    );
    expect(result[3].html).toBe('These findings support a continuum model.');
  });

  it('does not treat ordinary prose as a header', () => {
    const raw = 'Results were significant across every tissue we examined.';
    const result = splitAbstractSections(raw);
    expect(result).toHaveLength(1);
    expect(result[0].label).toBeNull();
  });

  it('keeps section bodies XSS-safe', () => {
    const raw = 'Methods  We ran <script>alert(1)</script> analyses.';
    const [section] = splitAbstractSections(raw);
    expect(section.label).toBe('Methods');
    expect(section.html).not.toMatch(/<script/i);
    expect(section.html).toContain('&lt;script&gt;');
  });

  it('captures unlabeled lead-in text before the first label', () => {
    const raw = 'Intro sentence. Methods  We did things.';
    const result = splitAbstractSections(raw);
    expect(result.map(s => s.label)).toEqual([null, 'Methods']);
    expect(result[0].html).toBe('Intro sentence.');
  });
});
