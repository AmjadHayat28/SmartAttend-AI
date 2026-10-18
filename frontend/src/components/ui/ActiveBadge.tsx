import { Badge } from "./Feedback";

export function ActiveBadge({ active }: { active: boolean }) {
  return <Badge tone={active ? "green" : "gray"}>{active ? "Active" : "Inactive"}</Badge>;
}
