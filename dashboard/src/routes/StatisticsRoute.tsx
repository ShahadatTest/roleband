import { StatisticsView } from "../features/statistics/StatisticsView";
import { useJobActions } from "../context/JobWorkspace";

export function StatisticsRoute() {
  const { openJob } = useJobActions();
  return <StatisticsView onOpen={openJob} />;
}
