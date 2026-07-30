import { redirect } from "next/navigation";

import { ROUTES } from "@/utils/constants";

// Unauthenticated requests never reach this point — middleware.ts redirects
// them to /login first. An authenticated visit to "/" lands on the dashboard.
export default function Home() {
  redirect(ROUTES.dashboard);
}
