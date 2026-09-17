import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import {
  createAcademicYear,
  createDivision,
  createFaculty,
  createFacultyAssignment,
  createSemester,
  createSubject,
  deleteAcademicYear,
  deleteDivision,
  deleteFacultyAssignment,
  deleteSemester,
  deleteSubject,
  getAcademicYears,
  getDivisions,
  getFacultyAccounts,
  getFacultyAssignments,
  getSemesters,
  getSubjects,
  linkStudentAccount,
  setFacultyAccountStatus,
} from "@/lib/api";
import { clearToken, getTokenUser } from "@/lib/auth";

const TABS = [
  { key: "years", label: "Academic Years" },
  { key: "semesters", label: "Semesters" },
  { key: "divisions", label: "Divisions" },
  { key: "subjects", label: "Subjects" },
  { key: "assignments", label: "Faculty Assignments" },
  { key: "faculty_accounts", label: "Faculty Accounts" },
  { key: "student_linking", label: "Student Accounts" },
];

const inputClass =
  "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 outline-none transition focus:border-[#C10202] focus:ring-2 focus:ring-[#C10202]";

const AcademicManagementPage = () => {
  const navigate = useNavigate();
  const [tab, setTab] = useState("years");
  const [forbidden, setForbidden] = useState(false);

  const [years, setYears] = useState([]);
  const [semesters, setSemesters] = useState([]);
  const [divisions, setDivisions] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [facultyAccounts, setFacultyAccounts] = useState([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [yearForm, setYearForm] = useState({ name: "", start_date: "", end_date: "" });
  const [semesterForm, setSemesterForm] = useState({ academic_year_id: "", number: 1, name: "" });
  const [divisionForm, setDivisionForm] = useState({ semester_id: "", name: "", program: "", batch_year: "" });
  const [subjectForm, setSubjectForm] = useState({ semester_id: "", code: "", name: "", credits: 0 });
  const [assignmentForm, setAssignmentForm] = useState({ faculty_id: "", subject_id: "", division_id: "" });
  const [facultyAccountForm, setFacultyAccountForm] = useState({ name: "", email: "", password: "" });
  const [studentLinkForm, setStudentLinkForm] = useState({ student_id: "", user_id: "" });
  const [studentLinkResult, setStudentLinkResult] = useState(null);

  const loadAll = async () => {
    setLoading(true);
    setError("");
    try {
      const [y, s, d, sub, a, fa] = await Promise.all([
        getAcademicYears(),
        getSemesters(),
        getDivisions(),
        getSubjects(),
        getFacultyAssignments(),
        getFacultyAccounts(),
      ]);
      setYears(y);
      setSemesters(s);
      setDivisions(d);
      setSubjects(sub);
      setAssignments(a);
      setFacultyAccounts(fa);
    } catch (requestError) {
      if (/forbidden/i.test(requestError.message)) {
        setForbidden(true);
      } else {
        setError(requestError.message);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const tokenUser = getTokenUser();
    if (tokenUser && tokenUser.role !== "hod") {
      setForbidden(true);
      setLoading(false);
      return;
    }
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const semesterOptions = useMemo(
    () =>
      semesters.map((s) => {
        const year = years.find((y) => y.id === s.academic_year_id);
        return { ...s, label: `${year ? year.name : "Year " + s.academic_year_id} - Sem ${s.number} (${s.name})` };
      }),
    [semesters, years]
  );

  const handleLogout = () => {
    clearToken();
    navigate("/login", { replace: true });
  };

  const submitYear = async (event) => {
    event.preventDefault();
    try {
      await createAcademicYear(yearForm);
      toast.success("Academic year created");
      setYearForm({ name: "", start_date: "", end_date: "" });
      loadAll();
    } catch (requestError) {
      toast.error(requestError.message);
    }
  };

  const submitSemester = async (event) => {
    event.preventDefault();
    try {
      await createSemester({ ...semesterForm, number: Number(semesterForm.number) });
      toast.success("Semester created");
      setSemesterForm({ academic_year_id: "", number: 1, name: "" });
      loadAll();
    } catch (requestError) {
      toast.error(requestError.message);
    }
  };

  const submitDivision = async (event) => {
    event.preventDefault();
    try {
      await createDivision({ ...divisionForm, batch_year: Number(divisionForm.batch_year) });
      toast.success("Division created");
      setDivisionForm({ semester_id: "", name: "", program: "", batch_year: "" });
      loadAll();
    } catch (requestError) {
      toast.error(requestError.message);
    }
  };

  const submitSubject = async (event) => {
    event.preventDefault();
    try {
      await createSubject({ ...subjectForm, credits: Number(subjectForm.credits) });
      toast.success("Subject created");
      setSubjectForm({ semester_id: "", code: "", name: "", credits: 0 });
      loadAll();
    } catch (requestError) {
      toast.error(requestError.message);
    }
  };

  const submitAssignment = async (event) => {
    event.preventDefault();
    try {
      await createFacultyAssignment({
        faculty_id: Number(assignmentForm.faculty_id),
        subject_id: Number(assignmentForm.subject_id),
        division_id: Number(assignmentForm.division_id),
      });
      toast.success("Faculty assignment created");
      setAssignmentForm({ faculty_id: "", subject_id: "", division_id: "" });
      loadAll();
    } catch (requestError) {
      toast.error(requestError.message);
    }
  };

  const deactivate = async (label, action, id) => {
    const confirmed = window.confirm(`Deactivate this ${label}? This cannot be undone through this screen.`);
    if (!confirmed) return;
    try {
      await action(id);
      toast.success(`${label} deactivated`);
      loadAll();
    } catch (requestError) {
      toast.error(requestError.message);
    }
  };

  const submitFacultyAccount = async (event) => {
    event.preventDefault();
    try {
      await createFaculty(facultyAccountForm);
      toast.success("Faculty account created");
      setFacultyAccountForm({ name: "", email: "", password: "" });
      loadAll();
    } catch (requestError) {
      toast.error(requestError.message);
    }
  };

  const toggleFacultyStatus = async (account) => {
    const nextActive = !account.is_active;
    const confirmed = window.confirm(
      nextActive ? "Reactivate this faculty account?" : "Deactivate this faculty account? They will not be able to log in."
    );
    if (!confirmed) return;
    try {
      await setFacultyAccountStatus(account.id, nextActive);
      toast.success(nextActive ? "Faculty account reactivated" : "Faculty account deactivated");
      loadAll();
    } catch (requestError) {
      toast.error(requestError.message);
    }
  };

  const submitStudentLink = async (event) => {
    event.preventDefault();
    setStudentLinkResult(null);
    try {
      const linked = await linkStudentAccount(
        Number(studentLinkForm.student_id),
        Number(studentLinkForm.user_id)
      );
      toast.success("Student account linked");
      setStudentLinkResult(linked);
      setStudentLinkForm({ student_id: "", user_id: "" });
    } catch (requestError) {
      toast.error(requestError.message);
    }
  };

  if (forbidden) {
    return (
      <div className="min-h-screen bg-gray-50 px-4 py-12">
        <div className="mx-auto max-w-md rounded-2xl border border-gray-200 bg-white p-8 text-center shadow-sm">
          <h2 className="text-lg font-semibold text-gray-900">Access denied</h2>
          <p className="mt-2 text-sm text-gray-600">
            Only an HOD account can manage the academic structure. Ask your HOD for access.
          </p>
          <button
            type="button"
            onClick={() => navigate("/dashboard")}
            className="mt-6 rounded-lg bg-[#C10202] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#8B1A1A]"
          >
            Back to dashboard
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8 text-gray-900">
      <div className="mx-auto max-w-6xl">
        <header className="mb-8 flex flex-col gap-4 rounded-2xl bg-[#C10202] p-5 text-white shadow-sm md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.28em] text-white/80">CCTV Attendance System</p>
            <h1 className="mt-2 text-2xl font-bold">Academic Management</h1>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => navigate("/dashboard")}
              className="rounded-lg border border-white/60 px-4 py-2 font-semibold text-white transition hover:bg-white/10"
            >
              Back to Dashboard
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

        <div className="mb-6 flex flex-wrap gap-2 rounded-lg bg-gray-100 p-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={`rounded-md px-3 py-2 text-sm font-semibold transition ${
                tab === t.key ? "bg-[#C10202] text-white" : "text-gray-700 hover:bg-white"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {error ? (
          <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
        ) : null}

        {loading ? (
          <div className="rounded-2xl border border-gray-200 bg-white p-6 text-gray-600">Loading academic data...</div>
        ) : null}

        {!loading && tab === "years" ? (
          <div className="grid gap-6 lg:grid-cols-3">
            <form onSubmit={submitYear} className="space-y-3 rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
              <h2 className="font-semibold text-gray-900">New Academic Year</h2>
              <input
                className={inputClass}
                placeholder="Name (e.g. 2026-27)"
                value={yearForm.name}
                onChange={(e) => setYearForm((c) => ({ ...c, name: e.target.value }))}
                required
              />
              <input
                type="date"
                className={inputClass}
                value={yearForm.start_date}
                onChange={(e) => setYearForm((c) => ({ ...c, start_date: e.target.value }))}
                required
              />
              <input
                type="date"
                className={inputClass}
                value={yearForm.end_date}
                onChange={(e) => setYearForm((c) => ({ ...c, end_date: e.target.value }))}
                required
              />
              <button className="w-full rounded-lg bg-[#C10202] py-2 font-semibold text-white transition hover:bg-[#8B1A1A]">
                Create
              </button>
            </form>

            <div className="lg:col-span-2">
              {years.length === 0 ? (
                <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center text-gray-600">
                  No academic years yet. Create the first one.
                </div>
              ) : (
                <div className="space-y-3">
                  {years.map((y) => (
                    <div key={y.id} className="flex items-center justify-between rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                      <div>
                        <p className="font-semibold text-gray-900">
                          {y.name} {y.is_current ? <span className="ml-2 rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">Current</span> : null}
                        </p>
                        <p className="text-sm text-gray-500">
                          {y.start_date} to {y.end_date} - {y.is_active ? "Active" : "Inactive"}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => deactivate("academic year", deleteAcademicYear, y.id)}
                        className="rounded-lg border border-red-300 px-3 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-50"
                      >
                        Deactivate
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : null}

        {!loading && tab === "semesters" ? (
          <div className="grid gap-6 lg:grid-cols-3">
            <form onSubmit={submitSemester} className="space-y-3 rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
              <h2 className="font-semibold text-gray-900">New Semester</h2>
              <select
                className={inputClass}
                value={semesterForm.academic_year_id}
                onChange={(e) => setSemesterForm((c) => ({ ...c, academic_year_id: e.target.value }))}
                required
              >
                <option value="">Select academic year</option>
                {years.map((y) => (
                  <option key={y.id} value={y.id}>
                    {y.name}
                  </option>
                ))}
              </select>
              <input
                type="number"
                min="1"
                max="8"
                className={inputClass}
                placeholder="Semester number (1-8)"
                value={semesterForm.number}
                onChange={(e) => setSemesterForm((c) => ({ ...c, number: e.target.value }))}
                required
              />
              <input
                className={inputClass}
                placeholder="Name"
                value={semesterForm.name}
                onChange={(e) => setSemesterForm((c) => ({ ...c, name: e.target.value }))}
                required
              />
              <button className="w-full rounded-lg bg-[#C10202] py-2 font-semibold text-white transition hover:bg-[#8B1A1A]">
                Create
              </button>
            </form>

            <div className="lg:col-span-2">
              {semesters.length === 0 ? (
                <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center text-gray-600">
                  No semesters yet.
                </div>
              ) : (
                <div className="space-y-3">
                  {semesterOptions.map((s) => (
                    <div key={s.id} className="flex items-center justify-between rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                      <div>
                        <p className="font-semibold text-gray-900">{s.label}</p>
                        <p className="text-sm text-gray-500">{s.is_active ? "Active" : "Inactive"}</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => deactivate("semester", deleteSemester, s.id)}
                        className="rounded-lg border border-red-300 px-3 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-50"
                      >
                        Deactivate
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : null}

        {!loading && tab === "divisions" ? (
          <div className="grid gap-6 lg:grid-cols-3">
            <form onSubmit={submitDivision} className="space-y-3 rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
              <h2 className="font-semibold text-gray-900">New Division</h2>
              <select
                className={inputClass}
                value={divisionForm.semester_id}
                onChange={(e) => setDivisionForm((c) => ({ ...c, semester_id: e.target.value }))}
                required
              >
                <option value="">Select semester</option>
                {semesterOptions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
              <input
                className={inputClass}
                placeholder="Program (e.g. CSE)"
                value={divisionForm.program}
                onChange={(e) => setDivisionForm((c) => ({ ...c, program: e.target.value }))}
                required
              />
              <input
                className={inputClass}
                placeholder="Division name (e.g. A)"
                value={divisionForm.name}
                onChange={(e) => setDivisionForm((c) => ({ ...c, name: e.target.value }))}
                required
              />
              <input
                type="number"
                className={inputClass}
                placeholder="Batch year"
                value={divisionForm.batch_year}
                onChange={(e) => setDivisionForm((c) => ({ ...c, batch_year: e.target.value }))}
                required
              />
              <button className="w-full rounded-lg bg-[#C10202] py-2 font-semibold text-white transition hover:bg-[#8B1A1A]">
                Create
              </button>
            </form>

            <div className="lg:col-span-2">
              {divisions.length === 0 ? (
                <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center text-gray-600">
                  No divisions yet.
                </div>
              ) : (
                <div className="space-y-3">
                  {divisions.map((d) => (
                    <div key={d.id} className="flex items-center justify-between rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                      <div>
                        <p className="font-semibold text-gray-900">
                          {d.program} - {d.name} ({d.batch_year})
                        </p>
                        <p className="text-sm text-gray-500">{d.is_active ? "Active" : "Inactive"}</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => deactivate("division", deleteDivision, d.id)}
                        className="rounded-lg border border-red-300 px-3 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-50"
                      >
                        Deactivate
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : null}

        {!loading && tab === "subjects" ? (
          <div className="grid gap-6 lg:grid-cols-3">
            <form onSubmit={submitSubject} className="space-y-3 rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
              <h2 className="font-semibold text-gray-900">New Subject</h2>
              <select
                className={inputClass}
                value={subjectForm.semester_id}
                onChange={(e) => setSubjectForm((c) => ({ ...c, semester_id: e.target.value }))}
                required
              >
                <option value="">Select semester</option>
                {semesterOptions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
              <input
                className={inputClass}
                placeholder="Code (e.g. CS301)"
                value={subjectForm.code}
                onChange={(e) => setSubjectForm((c) => ({ ...c, code: e.target.value }))}
                required
              />
              <input
                className={inputClass}
                placeholder="Name"
                value={subjectForm.name}
                onChange={(e) => setSubjectForm((c) => ({ ...c, name: e.target.value }))}
                required
              />
              <input
                type="number"
                min="0"
                className={inputClass}
                placeholder="Credits"
                value={subjectForm.credits}
                onChange={(e) => setSubjectForm((c) => ({ ...c, credits: e.target.value }))}
                required
              />
              <button className="w-full rounded-lg bg-[#C10202] py-2 font-semibold text-white transition hover:bg-[#8B1A1A]">
                Create
              </button>
            </form>

            <div className="lg:col-span-2">
              {subjects.length === 0 ? (
                <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center text-gray-600">
                  No subjects yet.
                </div>
              ) : (
                <div className="space-y-3">
                  {subjects.map((s) => (
                    <div key={s.id} className="flex items-center justify-between rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                      <div>
                        <p className="font-semibold text-gray-900">
                          {s.code} - {s.name}
                        </p>
                        <p className="text-sm text-gray-500">
                          {s.credits} credits - {s.is_active ? "Active" : "Inactive"}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => deactivate("subject", deleteSubject, s.id)}
                        className="rounded-lg border border-red-300 px-3 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-50"
                      >
                        Deactivate
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : null}

        {!loading && tab === "assignments" ? (
          <div className="grid gap-6 lg:grid-cols-3">
            <form onSubmit={submitAssignment} className="space-y-3 rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
              <h2 className="font-semibold text-gray-900">New Faculty Assignment</h2>
              <input
                type="number"
                className={inputClass}
                placeholder="Faculty user id"
                value={assignmentForm.faculty_id}
                onChange={(e) => setAssignmentForm((c) => ({ ...c, faculty_id: e.target.value }))}
                required
              />
              <select
                className={inputClass}
                value={assignmentForm.subject_id}
                onChange={(e) => setAssignmentForm((c) => ({ ...c, subject_id: e.target.value }))}
                required
              >
                <option value="">Select subject</option>
                {subjects.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.code} - {s.name}
                  </option>
                ))}
              </select>
              <select
                className={inputClass}
                value={assignmentForm.division_id}
                onChange={(e) => setAssignmentForm((c) => ({ ...c, division_id: e.target.value }))}
                required
              >
                <option value="">Select division</option>
                {divisions.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.program} - {d.name}
                  </option>
                ))}
              </select>
              <button className="w-full rounded-lg bg-[#C10202] py-2 font-semibold text-white transition hover:bg-[#8B1A1A]">
                Create
              </button>
            </form>

            <div className="lg:col-span-2">
              {assignments.length === 0 ? (
                <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center text-gray-600">
                  No faculty assignments yet.
                </div>
              ) : (
                <div className="space-y-3">
                  {assignments.map((a) => (
                    <div key={a.id} className="flex items-center justify-between rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                      <div>
                        <p className="font-semibold text-gray-900">
                          Faculty #{a.faculty_id} - Subject #{a.subject_id} - Division #{a.division_id}
                        </p>
                        <p className="text-sm text-gray-500">{a.is_active ? "Active" : "Inactive"}</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => deactivate("assignment", deleteFacultyAssignment, a.id)}
                        className="rounded-lg border border-red-300 px-3 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-50"
                      >
                        Deactivate
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : null}

        {!loading && tab === "faculty_accounts" ? (
          <div className="grid gap-6 lg:grid-cols-3">
            <form
              onSubmit={submitFacultyAccount}
              className="space-y-3 rounded-2xl border border-gray-200 bg-white p-5 shadow-sm"
            >
              <h2 className="font-semibold text-gray-900">New Faculty Account</h2>
              <input
                className={inputClass}
                placeholder="Name"
                value={facultyAccountForm.name}
                onChange={(e) => setFacultyAccountForm((c) => ({ ...c, name: e.target.value }))}
                required
              />
              <input
                type="email"
                className={inputClass}
                placeholder="Email"
                value={facultyAccountForm.email}
                onChange={(e) => setFacultyAccountForm((c) => ({ ...c, email: e.target.value }))}
                required
              />
              <input
                type="password"
                className={inputClass}
                placeholder="Temporary password"
                value={facultyAccountForm.password}
                onChange={(e) => setFacultyAccountForm((c) => ({ ...c, password: e.target.value }))}
                required
              />
              <button className="w-full rounded-lg bg-[#C10202] py-2 font-semibold text-white transition hover:bg-[#8B1A1A]">
                Create
              </button>
            </form>

            <div className="lg:col-span-2">
              {facultyAccounts.length === 0 ? (
                <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center text-gray-600">
                  No faculty accounts yet.
                </div>
              ) : (
                <div className="space-y-3">
                  {facultyAccounts.map((f) => (
                    <div
                      key={f.id}
                      className="flex items-center justify-between rounded-xl border border-gray-200 bg-white p-4 shadow-sm"
                    >
                      <div>
                        <p className="font-semibold text-gray-900">{f.name}</p>
                        <p className="text-sm text-gray-500">
                          {f.email} - {f.is_active ? "Active" : "Deactivated"}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => toggleFacultyStatus(f)}
                        className={`rounded-lg border px-3 py-2 text-sm font-semibold transition ${
                          f.is_active
                            ? "border-red-300 text-red-700 hover:bg-red-50"
                            : "border-green-300 text-green-700 hover:bg-green-50"
                        }`}
                      >
                        {f.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : null}

        {!loading && tab === "student_linking" ? (
          <div className="grid gap-6 lg:grid-cols-3">
            <form
              onSubmit={submitStudentLink}
              className="space-y-3 rounded-2xl border border-gray-200 bg-white p-5 shadow-sm"
            >
              <h2 className="font-semibold text-gray-900">Link Student Account</h2>
              <p className="text-xs text-gray-500">
                Links an existing Student record (enrolled via class roster) to a "student" role user
                account, so that student can sign in and see their own profile.
              </p>
              <input
                type="number"
                className={inputClass}
                placeholder="Student ID (from class roster)"
                value={studentLinkForm.student_id}
                onChange={(e) => setStudentLinkForm((c) => ({ ...c, student_id: e.target.value }))}
                required
              />
              <input
                type="number"
                className={inputClass}
                placeholder="User ID (registered with student role)"
                value={studentLinkForm.user_id}
                onChange={(e) => setStudentLinkForm((c) => ({ ...c, user_id: e.target.value }))}
                required
              />
              <button className="w-full rounded-lg bg-[#C10202] py-2 font-semibold text-white transition hover:bg-[#8B1A1A]">
                Link Account
              </button>
            </form>

            <div className="lg:col-span-2">
              {studentLinkResult ? (
                <div className="rounded-2xl border border-green-200 bg-green-50 p-5 text-sm text-green-800">
                  <p className="font-semibold">Linked successfully</p>
                  <p className="mt-1">
                    Student "{studentLinkResult.name}" (roll {studentLinkResult.roll_number}) is now linked
                    to user #{studentLinkResult.id}.
                  </p>
                </div>
              ) : (
                <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center text-gray-600">
                  Enter a student ID and a user ID (registered with the student role via the login
                  page's Student tab) to link them.
                </div>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
};

export default AcademicManagementPage;
