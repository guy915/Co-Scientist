import {describe, expect, it} from 'vitest';
import {splitAbstractSections} from './format_abstract';

describe('splitAbstractSections', () => {
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
    // Single space + lowercase continuation is normal prose, not a section.
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
