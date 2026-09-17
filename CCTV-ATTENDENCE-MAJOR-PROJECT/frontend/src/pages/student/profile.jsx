import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { getStudentProfile } from "@/lib/api";
import { clearToken } from "@/lib/auth";

const StudentProfilePage = () => {
  const navigate = useNavigate();

  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notLinked, setNotLinked] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError("");
      setNotLinked(false);
      try {
        const data = await getStudentProfile();
        if (!cancelled) {
          setProfile(data);
        }
      } catch (requestError) {
        if (cancelled) return;
        if (/no student profile/i.test(requestError.message)) {
          setNotLinked(true);
        } else {
          setError(requestError.message);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLogout = () => {
    clearToken();
    navigate("/login", { replace: true });
  };

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8 text-gray-900">
      <div className="mx-auto max-w-2xl">
        <header className="mb-8 flex flex-col gap-4 rounded-2xl bg-[#C10202] p-5 text-white shadow-sm md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.28em] text-white/80">CCTV Attendance System</p>
            <h1 className="mt-2 text-2xl font-bold">My Profile</h1>
          </div>
          <button
            type="button"
            onClick={handleLogout}
            className="rounded-lg border border-white px-4 py-2 font-semibold text-white transition hover:bg-white/10"
          >
            Logout
          </button>
        </header>

        {loading ? (
          <div className="rounded-2xl border border-gray-200 bg-white p-6 text-gray-600">Loading profile...</div>
        ) : null}

        {!loading && error ? (
          <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-sm text-red-700">{error}</div>
        ) : null}

        {!loading && notLinked ? (
          <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center text-gray-600">
            No student profile is linked to this account yet. Contact your faculty or HOD to have your
            record linked.
          </div>
        ) : null}

        {!loading && profile ? (
          <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
            <dl className="space-y-4 text-sm">
              <div className="flex justify-between border-b border-gray-100 pb-3">
                <dt className="font-medium text-gray-500">Name</dt>
                <dd className="text-gray-900">{profile.name}</dd>
              </div>
              <div className="flex justify-between border-b border-gray-100 pb-3">
                <dt className="font-medium text-gray-500">Roll Number</dt>
                <dd className="text-gray-900">{profile.roll_number}</dd>
              </div>
              <div className="flex justify-between border-b border-gray-100 pb-3">
                <dt className="font-medium text-gray-500">PRN</dt>
                <dd className="text-gray-900">{profile.prn_number || "Not set"}</dd>
              </div>
              <div className="flex justify-between border-b border-gray-100 pb-3">
                <dt className="font-medium text-gray-500">Email</dt>
                <dd className="text-gray-900">{profile.email || "Not set"}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="font-medium text-gray-500">Status</dt>
                <dd className="text-gray-900">{profile.is_active ? "Active" : "Inactive"}</dd>
              </div>
            </dl>
          </div>
        ) : null}
      </div>
    </div>
  );
};

export default StudentProfilePage;
