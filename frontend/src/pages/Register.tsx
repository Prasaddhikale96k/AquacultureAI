import { AuthLayout } from "../components/auth/AuthLayout";
import { RegisterWizard } from "../components/auth/RegisterWizard";

export default function Register() {
  return (
    <AuthLayout>
      <div className="w-full max-w-[460px]">
        <RegisterWizard />
      </div>
    </AuthLayout>
  );
}
