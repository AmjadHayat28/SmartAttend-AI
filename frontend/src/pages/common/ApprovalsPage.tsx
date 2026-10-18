import { PendingApprovals } from "../../components/accounts/PendingApprovals";
import { PageHeader } from "../../components/layout/PageHeader";

export function ApprovalsPage() {
  return (
    <>
      <PageHeader title="Student approvals" description="Review new student registrations before they can sign in." />
      <PendingApprovals pageSize={20} />
    </>
  );
}
