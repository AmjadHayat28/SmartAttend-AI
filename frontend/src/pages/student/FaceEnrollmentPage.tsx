import { FaceEnrollmentPanel } from "../../components/face/FaceEnrollmentPanel";
import { PageHeader } from "../../components/layout/PageHeader";
import { myEnrollment } from "../../services/faceEnrollmentService";

export function FaceEnrollmentPage() {
  return (
    <>
      <PageHeader title="My Face Enrollment" description="These photos let the system recognise you in classroom photos. They are only visible to you and your department." />
      <FaceEnrollmentPanel client={myEnrollment} />
    </>
  );
}
