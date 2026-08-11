import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { register } from "@/lib/api";

const RegisterPage = () => {
  const navigate = useNavigate();

  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const onSubmit = async (event) => {
    event.preventDefault();
    setError("");
    setLoading(true);

    try {
      await register(form);
      navigate("/login", { replace: true });
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

          <form className="space-y-4" onSubmit={onSubmit}>
            <div>
              <label htmlFor="name" className="mb-1 block text-sm font-medium text-gray-700">
                Name
              </label>
              <input
                id="name"
                type="text"
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 placeholder-gray-400 outline-none transition focus:border-[#C10202] focus:ring-2 focus:ring-[#C10202]"
                placeholder="Dr. Aarav Shah"
                required
              />
            </div>

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
                placeholder="Choose a strong password"
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
              {loading ? "Creating account..." : "Register"}
            </button>
          </form>

          <p className="mt-6 text-sm text-gray-600">
            Already registered?{" "}
            <Link to="/login" className="font-semibold text-[#C10202] hover:text-[#8B1A1A]">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
};

export default RegisterPage;
