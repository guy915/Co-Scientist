import { Seo } from "./Seo";

export function NoIndex({ title }: { title: string }) {
  return (
    <Seo
      title={`${title} - Co-Scientist`}
      description="Co-Scientist research workbench."
      path={window.location.pathname}
      robots="noindex, nofollow"
    />
  );
}
