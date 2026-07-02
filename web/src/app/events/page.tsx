import { EventsView } from "./EventsView";
import {
  getEvents,
  getEventImpact,
  getTimeline,
  getTimelineYears,
  getCategoryBreakdown,
  getExtremes,
} from "@/lib/data";

// Always read fresh from the DB (no static caching of the dashboard).
export const dynamic = "force-dynamic";

export default async function EventsPage() {
  const [events, impact, timeline, years, catData, extremes] = await Promise.all([
    getEvents(),
    getEventImpact(),
    getTimeline(),
    getTimelineYears(),
    getCategoryBreakdown(),
    getExtremes(),
  ]);

  return (
    <EventsView
      events={events}
      impact={impact}
      timeline={timeline}
      years={years}
      cats={catData.rows}
      baseline={catData.baseline}
      extremes={extremes}
    />
  );
}
