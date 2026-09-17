import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { login } from "@/lib/api";
import { decodeJwt, setToken } from "@/lib/auth";

const LoginPage = () => {
  const navigate = useNavigate();

  const [form, setForm] = useState({ email: "", password: "" });
  const [loginRole, setLoginRole] = useState("faculty");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const onSubmit = async (event) => {
    event.preventDefault();
    setError("");
    setLoading(true);

    try {
      const response = await login({ ...form, role: loginRole });
      setToken(response.token);

      // Route by the role actually issued in the token, not the tab the
      // user clicked, so a stale/mismatched selection can't send anyone
      // to a screen their account doesn't back.
      const payload = decodeJwt(response.token);
      if (payload?.role === "student") {
        navigate("/student/profile", { replace: true });
      } else {
        navigate("/dashboard", { replace: true });
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-12">
      <div className="mx-auto w-full max-w-md rounded-2xl border border-gray-200 bg-white shadow-lg">
        <div className="border-t-4 border-[#C10202] px-6 py-8">
          <img src="/assets/image.png" alt="SPIT Logo" className="h-16 mx-auto mb-2" />
          <h2 className="text-center font-bold text-gray-800">Sardar Patel Institute of Technology</h2>
          <p className="text-center text-sm text-gray-500">Professor Attendance Portal</p>
          <hr className="my-4 border-gray-200" />

          <div className="mb-4">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-gray-500">Login As</p>
            <div className="mt-2 grid grid-cols-3 gap-2 rounded-lg bg-gray-100 p-1">
              <button
                type="button"
                onClick={() => setLoginRole("faculty")}
                className={`rounded-md px-3 py-2 text-sm font-semibold transition ${
                  loginRole === "faculty"
                    ? "bg-[#C10202] text-white"
                    : "border border-[#C10202] text-[#C10202] hover:bg-red-50"
                }`}
              >
                Faculty
              </button>
              <button
                type="button"
                onClick={() => setLoginRole("hod")}
                className={`rounded-md px-3 py-2 text-sm font-semibold transition ${
                  loginRole === "hod"
                    ? "bg-[#C10202] text-white"
                    : "border border-[#C10202] text-[#C10202] hover:bg-red-50"
                }`}
              >
                HOD
              </button>
              <button
                type="button"
                onClick={() => setLoginRole("student")}
                className={`rounded-md px-3 py-2 text-sm font-semibold transition ${
                  loginRole === "student"
                    ? "bg-[#C10202] text-white"
                    : "border border-[#C10202] text-[#C10202] hover:bg-red-50"
                }`}
              >
                Student
              </button>
            </div>
          </div>

          <form className="space-y-4" onSubmit={onSubmit}>
            <div>
              <label htmlFor="email" className="mb-1 block text-sm font-medium text-gray-700">
                Email / Username
              </label>
              <input
                id="email"
                type="text"
                value={form.email}
                onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 placeholder-gray-400 outline-none transition focus:border-[#C10202] focus:ring-2 focus:ring-[#C10202]"
                placeholder="professor@college.edu"
                required
              />
            </div>

            <div>
              <label htmlFor="password" className="mb-1 block text-sm font-medium text-gray-700">
                Password
              </label>
              <input
                id="password"
                type="password"
                value={form.password}
                onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 placeholder-gray-400 outline-none transition focus:border-[#C10202] focus:ring-2 focus:ring-[#C10202]"
                placeholder="Enter your password"
                required
              />
            </div>

            {error ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
            ) : null}

            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-lg bg-[#C10202] py-2.5 font-semibold text-white transition hover:bg-[#8B1A1A] disabled:cursor-not-allowed disabled:opacity-70"
            >
              {loading ? "Signing in..." : "Login"}
            </button>
          </form>

          {loginRole === "student" ? (
            <p className="mt-6 text-sm text-gray-600">
              New here?{" "}
              <Link to="/register" className="font-semibold text-[#C10202] hover:text-[#8B1A1A]">
                Create account
              </Link>
              . Your HOD still needs to link it to your class record before your profile shows data.
            </p>
          ) : (
            <p className="mt-6 text-sm text-gray-600">
              {loginRole === "faculty"
                ? "Faculty accounts are created by your HOD."
                : "HOD accounts are provisioned by the admin."}
            </p>
          )}
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
