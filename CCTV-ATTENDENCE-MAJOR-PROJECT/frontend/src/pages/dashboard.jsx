import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import Modal from "@/components/Modal";
import { createClass, createFaculty, deleteClass, getClasses, getMe } from "@/lib/api";
import { clearToken } from "@/lib/auth";

const DashboardPage = () => {
  const navigate = useNavigate();

  const [user, setUser] = useState(null);
  const [classes, setClasses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newClass, setNewClass] = useState({ name: "", subject: "", grace_period_minutes: 10 });

  const [facultyOpen, setFacultyOpen] = useState(false);
  const [facultyBusy, setFacultyBusy] = useState(false);
  const [facultyForm, setFacultyForm] = useState({ name: "", email: "", password: "" });

  const isHod = user?.role === "hod";

  const loadData = async () => {
    setLoading(true);
    setError("");

    try {
      const [meResponse, classResponse] = await Promise.all([getMe(), getClasses()]);
      setUser(meResponse.user);
      setClasses(classResponse.classes || []);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleCreateClass = async (event) => {
    event.preventDefault();
    setCreating(true);

    try {
      await createClass(newClass);
      setCreateOpen(false);
      setNewClass({ name: "", subject: "", grace_period_minutes: 10 });
      await loadData();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setCreating(false);
    }
  };

  const handleCreateFaculty = async (event) => {
    event.preventDefault();
    setFacultyBusy(true);
    setError("");

    try {
      await createFaculty(facultyForm);
      setFacultyOpen(false);
      setFacultyForm({ name: "", email: "", password: "" });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setFacultyBusy(false);
    }
  };

  const handleDeleteClass = async (classId) => {
    const confirmed = window.confirm("Delete this class and all related attendance data?");
    if (!confirmed) {
      return;
    }

    try {
      await deleteClass(classId);
      await loadData();
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  const handleLogout = () => {
    clearToken();
    navigate("/login", { replace: true });
  };

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8 text-gray-900">
      <div className="mx-auto max-w-6xl">
        <header className="mb-8 flex flex-col gap-4 rounded-2xl bg-[#C10202] p-5 text-white shadow-sm md:flex-row md:items-center md:justify-between">
          <div className="flex flex-wrap items-center gap-4">
            <img src="/assets/image.png" alt="SPIT Logo" className="h-10" />
            <div>
              <p className="text-xs uppercase tracking-[0.28em] text-white/80">CCTV Attendance System</p>
              <h1 className="mt-2 text-2xl font-bold">Welcome, {user?.name || "Professor"}</h1>
              {isHod ? (
                <span className="mt-2 inline-flex rounded-full border border-white/50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-white">
                  HOD
                </span>
              ) : null}
            </div>
          </div>

          <div className="flex items-center gap-3">
            {isHod ? (
              <button
                type="button"
                onClick={() => setFacultyOpen(true)}
                className="rounded-lg border border-white/60 bg-white/10 px-4 py-2 font-semibold text-white shadow-sm transition hover:bg-white/20"
              >
                Add Faculty
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => setCreateOpen(true)}
              className="rounded-lg border border-white/60 bg-[#C10202] px-4 py-2 font-semibold text-white shadow-sm transition hover:bg-[#8B1A1A]"
            >
              Create Class
            </button>
            <button
              type="button"
              onClick={handleLogout}
              className="rounded-lg border border-white px-4 py-2 font-semibold text-white transition hover:bg-white/10"
            >
              Logout
            </button>
          </div>
        </header>

        {error ? (
          <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
        ) : null}

        {loading ? (
          <div className="rounded-2xl border border-gray-200 bg-white p-6 text-gray-600">Loading classes...</div>
        ) : null}

        {!loading && classes.length === 0 ? (
          <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center text-gray-600">
            No classes yet. Start by creating your first class.
          </div>
        ) : null}

        {!loading && classes.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {classes.map((classItem) => (
              <article
                key={classItem.id}
                className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm transition hover:border-l-4 hover:border-[#C10202]"
              >
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#C10202]">{classItem.subject}</p>
                <h2 className="mt-2 text-xl font-semibold text-gray-900">{classItem.name}</h2>

                <div className="mt-4 space-y-1 text-sm text-gray-600">
                  <p>Students: {classItem.student_count}</p>
                  <p>Grace Period: {classItem.grace_period_minutes} min</p>
                </div>

                <div className="mt-5 flex gap-2">
                  <Link
                    to={`/classes/${classItem.id}`}
                    className="rounded-lg bg-[#C10202] px-3 py-2 text-sm font-semibold text-white transition hover:bg-[#8B1A1A]"
                  >
                    View Class
                  </Link>

                  <button
                    type="button"
                    onClick={() => handleDeleteClass(classItem.id)}
                    className="rounded-lg border border-red-300 px-3 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-50"
                  >
                    Delete
                  </button>
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </div>

      <Modal
        open={facultyOpen}
        onClose={() => setFacultyOpen(false)}
        title="Add Faculty"
        footer={
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setFacultyOpen(false)}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 transition hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              form="create-faculty-form"
              disabled={facultyBusy}
              className="rounded-lg bg-[#C10202] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#8B1A1A] disabled:opacity-70"
            >
              {facultyBusy ? "Creating..." : "Create"}
            </button>
          </div>
        }
      >
        <form id="create-faculty-form" className="space-y-3" onSubmit={handleCreateFaculty}>
          <div>
            <label htmlFor="faculty_name" className="mb-1 block text-sm font-medium text-gray-700">
              Faculty Name
            </label>
            <input
              id="faculty_name"
              type="text"
              value={facultyForm.name}
              onChange={(event) => setFacultyForm((current) => ({ ...current, name: event.target.value }))}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 outline-none transition focus:border-[#C10202] focus:ring-2 focus:ring-[#C10202]"
              placeholder="Dr. Meera Shah"
              required
            />
          </div>

          <div>
            <label htmlFor="faculty_email" className="mb-1 block text-sm font-medium text-gray-700">
              Email / Username
            </label>
            <input
              id="faculty_email"
              type="text"
              value={facultyForm.email}
              onChange={(event) => setFacultyForm((current) => ({ ...current, email: event.target.value }))}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 outline-none transition focus:border-[#C10202] focus:ring-2 focus:ring-[#C10202]"
              placeholder="faculty@spit.ac.in"
              required
            />
          </div>

          <div>
            <label htmlFor="faculty_password" className="mb-1 block text-sm font-medium text-gray-700">
              Temporary Password
            </label>
            <input
              id="faculty_password"
              type="password"
              value={facultyForm.password}
              onChange={(event) => setFacultyForm((current) => ({ ...current, password: event.target.value }))}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 outline-none transition focus:border-[#C10202] focus:ring-2 focus:ring-[#C10202]"
              placeholder="Set a temporary password"
              required
            />
          </div>
        </form>
      </Modal>

      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Create New Class"
        footer={
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setCreateOpen(false)}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 transition hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              form="create-class-form"
              disabled={creating}
              className="rounded-lg bg-[#C10202] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#8B1A1A] disabled:opacity-70"
            >
              {creating ? "Creating..." : "Create"}
            </button>
          </div>
        }
      >
        <form id="create-class-form" className="space-y-3" onSubmit={handleCreateClass}>
          <div>
            <label htmlFor="class_name" className="mb-1 block text-sm font-medium text-gray-700">
              Class Name
            </label>
            <input
              id="class_name"
              type="text"
              value={newClass.name}
              onChange={(event) => setNewClass((current) => ({ ...current, name: event.target.value }))}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 outline-none transition focus:border-[#C10202] focus:ring-2 focus:ring-[#C10202]"
              placeholder="AIML Division A"
              required
            />
          </div>

          <div>
            <label htmlFor="class_subject" className="mb-1 block text-sm font-medium text-gray-700">
              Subject
            </label>
            <input
              id="class_subject"
              type="text"
              value={newClass.subject}
              onChange={(event) => setNewClass((current) => ({ ...current, subject: event.target.value }))}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 outline-none transition focus:border-[#C10202] focus:ring-2 focus:ring-[#C10202]"
              placeholder="Computer Vision"
              required
            />
          </div>

          <div>
            <label htmlFor="class_grace" className="mb-1 block text-sm font-medium text-gray-700">
              Grace Period (minutes)
            </label>
            <input
              id="class_grace"
              type="number"
              min="0"
              max="90"
              value={newClass.grace_period_minutes}
              onChange={(event) =>
                setNewClass((current) => ({
                  ...current,
                  grace_period_minutes: Number(event.target.value || 0),
                }))
              }
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 outline-none transition focus:border-[#C10202] focus:ring-2 focus:ring-[#C10202]"
            />
          </div>
        </form>
      </Modal>
    </div>
  );
};

export default DashboardPage;
