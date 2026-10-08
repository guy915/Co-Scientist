import {useEffect} from 'react';
import {Link} from 'react-router-dom';
import {PrivacyContent} from './privacy_content';
import {TermsContent} from './terms_content';

export function LegalPage({kind}: {kind: 'privacy' | 'terms'}) {
  const title = kind === 'privacy' ? 'Privacy notice' : 'Terms of use';
  useEffect(() => {
    document.title = `${title} - Open Co-Scientist`;
    const updates = [
      ['meta[name="robots"]', 'content', 'index, follow'],
      ['meta[name="googlebot"]', 'content', 'index, follow'],
      [
        'meta[name="description"]',
        'content',
        `${title} for Open Co-Scientist.`,
      ],
      ['link[rel="canonical"]', 'href', `https://open-coscientist.com/${kind}`],
    ];
    const previous = updates.map(([selector, attribute, value]) => {
      const element = document.head.querySelector(selector);
      const oldValue = element?.getAttribute(attribute);
      element?.setAttribute(attribute, value);
      return {element, attribute, oldValue};
    });
    return () => {
      previous.forEach(({element, attribute, oldValue}) => {
        if (oldValue !== null && oldValue !== undefined)
          element?.setAttribute(attribute, oldValue);
      });
    };
  }, [kind, title]);
  return (
    <article className="mx-auto w-full max-w-3xl box-border px-6 py-8 leading-relaxed text-cosci-ink wrap-anywhere phone:px-4 [&_h2]:mt-8 [&_h2]:font-gsans [&_h2]:text-xl [&_p]:my-4">
      <nav aria-label="Legal pages" className="flex flex-wrap gap-5">
        <Link to="/">Research workspace</Link>
        <Link
          to="/privacy"
          aria-current={kind === 'privacy' ? 'page' : undefined}
        >
          Privacy
        </Link>
        <Link to="/terms" aria-current={kind === 'terms' ? 'page' : undefined}>
          Terms
        </Link>
      </nav>
      <h1 className="font-gsans text-3xl font-medium">{title}</h1>
      <p className="text-cosci-muted">Updated · 8 October 2026</p>
      <p>This text is not legal advice.</p>
      {kind === 'privacy' ? <PrivacyContent /> : <TermsContent />}
    </article>
  );
}
