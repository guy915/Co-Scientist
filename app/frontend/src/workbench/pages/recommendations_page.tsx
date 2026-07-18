import {GOOGLE_RECOMMENDATIONS} from '../audience_content';

/** Static recommendations page linked from the Google team header control. */
export function RecommendationsPage() {
  return (
    <main className="mx-auto grid w-[min(100%_-_2rem,44rem)] gap-6 py-12">
      <h1 className="font-gsans text-4xl font-normal">
        {GOOGLE_RECOMMENDATIONS.heading}
      </h1>
      <ul className="grid list-disc gap-3 pl-6 text-lg">
        {GOOGLE_RECOMMENDATIONS.points.map(point => (
          <li key={point}>{point}</li>
        ))}
      </ul>
    </main>
  );
}
