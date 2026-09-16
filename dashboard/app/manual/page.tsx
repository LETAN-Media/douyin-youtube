import { Shell } from "@/components/Shell";
import { getManualPublications, listAllDestinations } from "@/lib/api";
import type { Destination, ManualPublicationItem } from "@/lib/types";
import { ManualPublishClient } from "./ManualPublishClient";

export const dynamic = "force-dynamic";

export default async function ManualPublishPage() {
  let destinations: Destination[] = [];
  let history: ManualPublicationItem[] = [];

  try {
    destinations = await listAllDestinations();
  } catch (e) {
    console.error("Failed to load destinations on server:", e);
  }

  try {
    history = await getManualPublications(30);
  } catch (e) {
    console.error("Failed to load history on server:", e);
  }

  return (
    <Shell>
      <ManualPublishClient
        initialDestinations={destinations}
        initialHistory={history}
      />
    </Shell>
  );
}
