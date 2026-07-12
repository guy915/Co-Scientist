/** Public scientific-use boundary shown on every workspace surface. */
export function IntendedUseNotice() {
  return (
    <aside
      aria-label="Intended use"
      className="mx-auto mt-8 mb-5 w-[min(100%_-_2rem,58rem)] border-t border-cosci-border pt-4 text-xs leading-5 text-cosci-muted"
    >
      <strong className="font-medium text-cosci-fg">Research use only.</strong>{' '}
      Co-Scientist outputs are starting points for scientific researchers and
      require independent verification. Do not rely on them for clinical
      decisions or applications that place people at risk.
      <a className="ml-2 underline" href="/access">
        Researcher access
      </a>
    </aside>
  );
}
