import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import Modal from "@/components/Modal";
import StatusBadge from "@/components/StatusBadge";
import {
  deleteStudent,
  enrollZip,
  getClass,
  getClassAtRiskStudents,
  getSessionStatus,
  getSessions,
  getStudentRiskProfile,
  getStudents,
  updateClass,
  uploadVideo,
} from "@/lib/api";

const ClassDetailPage = () => {
  const navigate = useNavigate();
  const { id } = useParams();
  const classId = Number(id);

  const [classInfo, setClassInfo] = useState(null);
  const [students, setStudents] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [activeTab, setActiveTab] = useState("students");

  const [atRiskData, setAtRiskData] = useState(null);
  const [atRiskLoading, setAtRiskLoading] = useState(false);
  const [atRiskFilter, setAtRiskFilter] = useState("ALL");
  const [onlyFinalised, setOnlyFinalised] = useState(false);
  const [selectedRiskStudent, setSelectedRiskStudent] = useState(null);
  const [riskProfileLoading, setRiskProfileLoading] = useState(false);
  const [riskModalOpen, setRiskModalOpen] = useState(false);

  const [editGrace, setEditGrace] = useState(false);
  const [graceInput, setGraceInput] = useState("10");

  const [enrollOpen, setEnrollOpen] = useState(false);
  const [zipFile, setZipFile] = useState(null);
  const [enrollBusy, setEnrollBusy] = useState(false);
  const [enrollResults, setEnrollResults] = useState([]);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [videoFile, setVideoFile] = useState(null);
  const [uploadBusy, setUploadBusy] = useState(false);

  const [pollSessionId, setPollSessionId] = useState(null);
  const [pollStatus, setPollStatus] = useState({ status: "pending", progress: 0 });

  const loadAtRiskData = useCallback(async (filter = atRiskFilter, finalisedOnly = onlyFinalised) => {
    if (!Number.isInteger(classId)) return;
    setAtRiskLoading(true);
    try {
      const params = {};
      if (filter && filter !== "ALL") params.risk_level = filter;
      if (finalisedOnly) params.only_finalised = "true";
      const data = await getClassAtRiskStudents(classId, params);
      setAtRiskData(data);
    } catch (err) {
      console.error("Failed to load at-risk students", err);
    } finally {
      setAtRiskLoading(false);
    }
  }, [classId, atRiskFilter, onlyFinalised]);

  const handleViewRiskProfile = async (studentId) => {
    setRiskProfileLoading(true);
    setRiskModalOpen(true);
    try {
      const profile = await getStudentRiskProfile(studentId, {
        class_id: classId,
        only_finalised: onlyFinalised ? "true" : "false",
      });
      setSelectedRiskStudent(profile);
    } catch (err) {
      console.error("Failed to load student risk profile", err);
    } finally {
      setRiskProfileLoading(false);
    }
  };

  const refreshData = useCallback(async () => {
    if (!Number.isInteger(classId)) {
      return;
    }

    setLoading(true);
    setError("");

    try {
      const [classResponse, studentsResponse, sessionsResponse] = await Promise.all([
        getClass(classId),
        getStudents(classId),
        getSessions(classId),
      ]);

      setClassInfo(classResponse.class);

      setGraceInput(String(classResponse.class?.grace_period_minutes ?? 10));
      setStudents(studentsResponse.students || []);
      setSessions(sessionsResponse.sessions || []);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }, [classId]);

  useEffect(() => {
    refreshData();
  }, [refreshData]);

  useEffect(() => {
    if (!pollSessionId) {
      return undefined;
    }

    let active = true;

    const poll = async () => {
      try {
        const statusResponse = await getSessionStatus(pollSessionId);
        if (!active) {
          return;
        }

        setPollStatus(statusResponse);

        setSessions((current) =>
          current.map((session) =>
            session.id === pollSessionId
              ? {
                  ...session,
                  processing_status: statusResponse.status,
                  progress_pct: statusResponse.progress,
                  error_message: statusResponse.error,
                }
              : session,
          ),
        );

        if (statusResponse.status === "done" || statusResponse.status === "error") {
          setPollSessionId(null);
          await refreshData();
        }
      } catch (_error) {
        if (active) {
          setPollSessionId(null);
        }
      }
    };

    poll();
    const timer = setInterval(poll, 3000);

    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [pollSessionId, refreshData]);

  const saveGracePeriod = async () => {
    try {
      await updateClass(classId, Number(graceInput || 0));
      setEditGrace(false);
      await refreshData();
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  const handleDeleteStudent = async (studentId) => {
    const confirmed = window.confirm("Unenroll this student?");
    if (!confirmed) {
      return;
    }

    try {
      await deleteStudent(classId, studentId);
      await refreshData();
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  const handleEnrollZip = async (event) => {
    event.preventDefault();
    if (!zipFile) {
      return;
    }

    setEnrollBusy(true);
    setError("");

    try {
      const response = await enrollZip(classId, zipFile);
      setEnrollResults(response.results || []);
      await refreshData();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setEnrollBusy(false);
    }
  };

  const handleUploadVideo = async (event) => {
    event.preventDefault();
    if (!videoFile) {
      return;
    }

    setUploadBusy(true);
    setError("");

    try {
      const response = await uploadVideo({
        classId,
        file: videoFile,
      });

      setUploadOpen(false);
      setVideoFile(null);
      setPollSessionId(response.session_id);

      await refreshData();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setUploadBusy(false);
    }
  };


  if (!Number.isInteger(classId)) {
    return <div className="p-6 text-red-700">Invalid class ID.</div>;
  }

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8 text-gray-900">
      <div className="mx-auto max-w-6xl">
        <div className="mb-5 flex items-center justify-between">
          <Link to="/dashboard" className="text-sm font-semibold text-[#C10202] hover:text-[#8B1A1A]">
            &larr; Back to Dashboard
          </Link>
          {pollSessionId ? (
            <p className="text-xs uppercase tracking-[0.2em] text-gray-600">Live Processing Active</p>
          ) : null}
        </div>

        {error ? (
          <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
        ) : null}

        {loading ? (
          <div className="rounded-xl border border-gray-200 bg-white p-6 text-gray-600">Loading class data...</div>
        ) : null}

        {!loading && classInfo ? (
          <>
            <header className="rounded-2xl bg-[#C10202] p-5 text-white shadow-sm">
              <div className="flex flex-wrap items-center gap-4">
                <img src="/assets/image.png" alt="SPIT Logo" className="h-10" />
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.25em] text-white/80">Class Detail</p>
                  <h1 className="mt-2 text-3xl font-bold">{classInfo.name}</h1>
                  <p className="mt-1 text-white/80">{classInfo.subject}</p>
                </div>
              </div>

              <div className="mt-5 flex flex-wrap items-center gap-3 rounded-xl border border-gray-200 bg-white p-3 text-gray-900">
                <span className="text-sm text-gray-600">Grace Period:</span>
                {editGrace ? (
                  <>
                    <input
                      type="number"
                      min="0"
                      max="90"
                      value={graceInput}
                      onChange={(event) => setGraceInput(event.target.value)}
                      className="w-24 rounded-md border border-gray-300 bg-white px-2 py-1 text-sm text-gray-900 outline-none focus:border-[#C10202] focus:ring-2 focus:ring-[#C10202]"
                    />
                    <button
                      type="button"
                      onClick={saveGracePeriod}
                      className="rounded-md bg-[#C10202] px-3 py-1 text-sm font-semibold text-white transition hover:bg-[#8B1A1A]"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setEditGrace(false);
                        setGraceInput(String(classInfo.grace_period_minutes || 10));
                      }}
                      className="rounded-md border border-[#C10202] px-3 py-1 text-sm font-semibold text-[#C10202] transition hover:bg-red-50"
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <span className="rounded-md bg-red-50 px-3 py-1 text-sm font-semibold text-[#C10202]">
                      {classInfo.grace_period_minutes} min
                    </span>
                    <button
                      type="button"
                      onClick={() => setEditGrace(true)}
                      className="rounded-md border border-[#C10202] px-3 py-1 text-sm font-semibold text-[#C10202] transition hover:bg-red-50"
                    >
                      Edit
                    </button>
                  </>
                )}
              </div>
            </header>

            <div className="mt-6">
              <div className="mb-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setActiveTab("students")}
                  className={`rounded-lg px-4 py-2 text-sm font-semibold transition ${
                    activeTab === "students"
                      ? "bg-[#C10202] text-white"
                      : "border border-[#C10202] text-[#C10202] hover:bg-red-50"
                  }`}
                >
                  Students
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("sessions")}
                  className={`rounded-lg px-4 py-2 text-sm font-semibold transition ${
                    activeTab === "sessions"
                      ? "bg-[#C10202] text-white"
                      : "border border-[#C10202] text-[#C10202] hover:bg-red-50"
                  }`}
                >
                  Attendance Sessions
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setActiveTab("at-risk");
                    loadAtRiskData();
                  }}
                  className={`rounded-lg px-4 py-2 text-sm font-semibold transition ${
                    activeTab === "at-risk"
                      ? "bg-[#C10202] text-white"
                      : "border border-[#C10202] text-[#C10202] hover:bg-red-50"
                  }`}
                >
                  At-Risk & Shortage Prediction
                </button>
              </div>


              {activeTab === "students" ? (
                <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
                  <div className="mb-4 flex items-center justify-between">
                    <h2 className="text-lg font-semibold">Enrolled Students</h2>
                    <button
                      type="button"
                      onClick={() => {
                        setEnrollResults([]);
                        setEnrollOpen(true);
                      }}
                      className="rounded-lg bg-[#C10202] px-3 py-2 text-sm font-semibold text-white transition hover:bg-[#8B1A1A]"
                    >
                      Enroll Students
                    </button>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead>
                        <tr className="border-b border-gray-200 text-left text-gray-600">
                          <th className="px-3 py-2">Roll No</th>
                          <th className="px-3 py-2">Name</th>
                          <th className="px-3 py-2">Enrolled At</th>
                          <th className="px-3 py-2">Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {students.map((student) => (
                          <tr key={student.id} className="border-b border-gray-100">
                            <td className="px-3 py-2 text-[#C10202]">{student.roll_number}</td>
                            <td className="px-3 py-2">{student.name}</td>
                            <td className="px-3 py-2 text-gray-500">{new Date(student.enrolled_at).toLocaleString()}</td>
                            <td className="px-3 py-2">
                              <button
                                type="button"
                                onClick={() => handleDeleteStudent(student.id)}
                                className="rounded-md border border-red-300 px-2 py-1 text-xs font-semibold text-red-700 transition hover:bg-red-50"
                              >
                                Delete
                              </button>
                            </td>
                          </tr>
                        ))}
                        {students.length === 0 ? (
                          <tr>
                            <td colSpan={4} className="px-3 py-6 text-center text-gray-500">
                              No students enrolled yet.
                            </td>
                          </tr>
                        ) : null}
                      </tbody>
                    </table>
                  </div>
                </section>
              ) : activeTab === "sessions" ? (
                <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
                  <div className="mb-4 flex items-center justify-between">
                    <h2 className="text-lg font-semibold">Attendance Sessions</h2>

                    <button
                      type="button"
                      onClick={() => {
                        setUploadOpen(true);
                      }}
                      className="rounded-lg bg-[#C10202] px-3 py-2 text-sm font-semibold text-white transition hover:bg-[#8B1A1A]"
                    >
                      Upload CCTV Video
                    </button>
                  </div>

                  {pollSessionId ? (
                    <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-3">
                      <div className="mb-2 flex items-center justify-between text-xs uppercase tracking-[0.2em] text-red-700">
                        <span>
                          {pollStatus.status === "processing"
                            ? "Processing complete lecture"
                            : `Current Session: ${pollStatus.status}`}
                        </span>
                        <span>{pollStatus.progress || 0}%</span>
                      </div>
                      <div className="h-2 rounded-full bg-gray-200">
                        <div
                          className="h-2 rounded-full bg-[#C10202] transition-all"
                          style={{ width: `${pollStatus.progress || 0}%` }}
                        />
                      </div>
                      {pollStatus.status === "error" && pollStatus.error ? (
                        <p className="mt-2 text-xs text-red-700">{pollStatus.error}</p>
                      ) : null}
                    </div>
                  ) : null}

                  {!pollSessionId && pollStatus.students_requiring_reenrollment > 0 ? (
                    <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                      Attendance was not generated for {pollStatus.students_requiring_reenrollment} student
                      {pollStatus.students_requiring_reenrollment === 1 ? "" : "s"} because compatible face
                      templates are unavailable. Re-enrolment is required.
                    </div>
                  ) : null}

                  <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead>
                        <tr className="border-b border-gray-200 text-left text-gray-600">
                          <th className="px-3 py-2">Date</th>
                          <th className="px-3 py-2">Status</th>
                          <th className="px-3 py-2">Progress</th>
                          <th className="px-3 py-2">Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sessions.map((session) => (
                          <tr key={session.id} className="border-b border-gray-100">
                            <td className="px-3 py-2">{session.session_date}</td>
                            <td className="px-3 py-2">
                              <StatusBadge status={session.processing_status} />
                            </td>
                            <td className="px-3 py-2">{session.progress_pct || 0}%</td>
                            <td className="px-3 py-2">
                              <button
                                type="button"
                                onClick={() => navigate(`/attendance/${session.id}`)}
                                className="rounded-md border border-[#C10202] px-2 py-1 text-xs font-semibold text-[#C10202] transition hover:bg-red-50"
                              >
                                View
                              </button>
                            </td>
                          </tr>
                        ))}
                        {sessions.length === 0 ? (
                          <tr>
                            <td colSpan={4} className="px-3 py-6 text-center text-gray-500">
                              No sessions uploaded yet.
                            </td>
                          </tr>
                        ) : null}
                      </tbody>
                    </table>
                  </div>
                </section>
              ) : (
                <section className="space-y-6">
                  {/* Summary Header & Cards */}
                  <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
                    <div className="flex flex-wrap items-center justify-between gap-4 border-b border-gray-100 pb-4">
                      <div>
                        <span className="text-xs font-semibold uppercase tracking-[0.2em] text-[#C10202]">
                          Prediction & Early Warning Engine
                        </span>
                        <h2 className="mt-1 text-xl font-bold text-gray-900">At-Risk & Shortage Analysis</h2>
                        <p className="mt-1 text-xs text-gray-500">
                          Institutional minimum attendance threshold:{" "}
                          <span className="font-bold text-gray-800">
                            {atRiskData?.threshold_percentage ?? 75}%
                          </span>
                        </p>
                      </div>

                      <div className="flex flex-wrap items-center gap-3">
                        <label className="flex items-center gap-2 text-xs font-medium text-gray-600">
                          <input
                            type="checkbox"
                            checked={onlyFinalised}
                            onChange={(e) => {
                              setOnlyFinalised(e.target.checked);
                              loadAtRiskData(atRiskFilter, e.target.checked);
                            }}
                            className="rounded border-gray-300 text-[#C10202] focus:ring-[#C10202]"
                          />
                          Finalised Sessions Only
                        </label>

                        <button
                          type="button"
                          onClick={() => loadAtRiskData(atRiskFilter, onlyFinalised)}
                          disabled={atRiskLoading}
                          className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 shadow-sm transition hover:bg-gray-50"
                        >
                          {atRiskLoading ? "Refreshing..." : "↻ Refresh"}
                        </button>
                      </div>
                    </div>

                    {/* Metric Cards */}
                    <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                      <div className="rounded-xl border border-red-200 bg-red-50/70 p-3.5">
                        <div className="flex items-center justify-between text-xs font-bold text-red-700">
                          <span>HIGH RISK</span>
                          <span className="rounded-full bg-red-200/80 px-1.5 py-0.5 text-[10px]">CRITICAL</span>
                        </div>
                        <p className="mt-2 text-3xl font-extrabold text-red-700">
                          {atRiskData?.summary?.high_risk_count ?? 0}
                        </p>
                        <p className="mt-1 text-[11px] text-red-600/90">&lt;60% or &ge;3 absences</p>
                      </div>

                      <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-3.5">
                        <div className="flex items-center justify-between text-xs font-bold text-amber-700">
                          <span>MEDIUM RISK</span>
                          <span className="rounded-full bg-amber-200/80 px-1.5 py-0.5 text-[10px]">WARNING</span>
                        </div>
                        <p className="mt-2 text-3xl font-extrabold text-amber-700">
                          {atRiskData?.summary?.medium_risk_count ?? 0}
                        </p>
                        <p className="mt-1 text-[11px] text-amber-600/90">60-74.9% or &gt;10% drop</p>
                      </div>

                      <div className="rounded-xl border border-emerald-200 bg-emerald-50/70 p-3.5">
                        <div className="flex items-center justify-between text-xs font-bold text-emerald-700">
                          <span>COMPLIANT</span>
                          <span className="rounded-full bg-emerald-200/80 px-1.5 py-0.5 text-[10px]">ON TRACK</span>
                        </div>
                        <p className="mt-2 text-3xl font-extrabold text-emerald-700">
                          {atRiskData?.summary?.low_risk_count ?? 0}
                        </p>
                        <p className="mt-1 text-[11px] text-emerald-600/90">&ge;75% stable</p>
                      </div>

                      <div className="rounded-xl border border-gray-200 bg-gray-50 p-3.5">
                        <div className="flex items-center justify-between text-xs font-bold text-gray-700">
                          <span>EVALUATED</span>
                          <span className="rounded-full bg-gray-200 px-1.5 py-0.5 text-[10px]">TOTAL</span>
                        </div>
                        <p className="mt-2 text-3xl font-extrabold text-gray-800">
                          {atRiskData?.total_students ?? 0}
                        </p>
                        <p className="mt-1 text-[11px] text-gray-500">
                          Across {atRiskData?.total_sessions ?? 0} session(s)
                        </p>
                      </div>
                    </div>

                    {/* Filter Tabs */}
                    <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-gray-100 pt-4 text-xs font-semibold">
                      <span className="text-gray-500">Filter:</span>
                      {["ALL", "AT_RISK", "HIGH", "MEDIUM", "LOW"].map((level) => (
                        <button
                          key={level}
                          type="button"
                          onClick={() => {
                            setAtRiskFilter(level);
                            loadAtRiskData(level, onlyFinalised);
                          }}
                          className={`rounded-lg px-3 py-1.5 transition ${
                            atRiskFilter === level
                              ? "bg-gray-900 text-white"
                              : "border border-gray-200 bg-white text-gray-700 hover:bg-gray-50"
                          }`}
                        >
                          {level === "ALL"
                            ? "All Students"
                            : level === "AT_RISK"
                            ? "All At-Risk"
                            : `${level.charAt(0) + level.slice(1).toLowerCase()} Risk`}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* At-Risk Students Table */}
                  <div className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
                    <div className="overflow-x-auto">
                      <table className="min-w-full text-sm">
                        <thead>
                          <tr className="border-b border-gray-200 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                            <th className="px-3 py-3">Roll No</th>
                            <th className="px-3 py-3">Student Name</th>
                            <th className="px-3 py-3">Attendance</th>
                            <th className="px-3 py-3">Velocity Trend</th>
                            <th className="px-3 py-3">Consecutive Missed</th>
                            <th className="px-3 py-3">Shortage Forecast</th>
                            <th className="px-3 py-3">Risk Level</th>
                            <th className="px-3 py-3">Rule Flags</th>
                            <th className="px-3 py-3 text-right">Action</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                          {atRiskData?.students?.map((s) => (
                            <tr key={s.student_id} className="hover:bg-gray-50/60 transition">
                              <td className="px-3 py-3 font-bold text-[#C10202]">{s.roll_number}</td>
                              <td className="px-3 py-3 font-medium text-gray-900">{s.student_name}</td>
                              <td className="px-3 py-3">
                                <div className="flex items-center gap-2">
                                  <span className="font-bold text-gray-800">{s.attendance_percentage}%</span>
                                  <div className="h-1.5 w-16 overflow-hidden rounded-full bg-gray-100">
                                    <div
                                      className={`h-full ${
                                        s.attendance_percentage < 60
                                          ? "bg-red-500"
                                          : s.attendance_percentage < 75
                                          ? "bg-amber-500"
                                          : "bg-emerald-500"
                                      }`}
                                      style={{ width: `${Math.min(100, s.attendance_percentage)}%` }}
                                    />
                                  </div>
                                </div>
                              </td>
                              <td className="px-3 py-3">
                                {s.attendance_velocity !== null ? (
                                  <span
                                    className={`inline-flex items-center gap-0.5 rounded px-2 py-0.5 text-xs font-bold ${
                                      s.attendance_velocity < -10
                                        ? "bg-red-100 text-red-700"
                                        : s.attendance_velocity < 0
                                        ? "bg-amber-100 text-amber-700"
                                        : "bg-emerald-100 text-emerald-700"
                                    }`}
                                  >
                                    {s.attendance_velocity < 0 ? "↓" : "↑"}{" "}
                                    {Math.abs(s.attendance_velocity)}%
                                  </span>
                                ) : (
                                  <span className="text-xs text-gray-400">N/A</span>
                                )}
                              </td>
                              <td className="px-3 py-3">
                                {s.consecutive_absences > 0 ? (
                                  <span
                                    className={`rounded px-2 py-0.5 text-xs font-semibold ${
                                      s.consecutive_absences >= 3
                                        ? "bg-red-100 font-bold text-red-700"
                                        : "bg-amber-100 text-amber-700"
                                    }`}
                                  >
                                    {s.consecutive_absences} missed
                                  </span>
                                ) : (
                                  <span className="text-xs text-gray-400">0</span>
                                )}
                              </td>
                              <td className="px-3 py-3 text-xs">
                                {s.sessions_needed_to_recover > 0 ? (
                                  <span className="font-semibold text-red-700">
                                    Needs {s.sessions_needed_to_recover} attended
                                  </span>
                                ) : s.buffer_sessions_allowed > 0 ? (
                                  <span className="text-emerald-700">
                                    Can miss up to {s.buffer_sessions_allowed}
                                  </span>
                                ) : (
                                  <span className="text-amber-700">At threshold</span>
                                )}
                              </td>
                              <td className="px-3 py-3">
                                <span
                                  className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-bold ${
                                    s.risk_level === "HIGH"
                                      ? "bg-red-100 text-red-800"
                                      : s.risk_level === "MEDIUM"
                                      ? "bg-amber-100 text-amber-800"
                                      : "bg-emerald-100 text-emerald-800"
                                  }`}
                                >
                                  {s.risk_level}
                                </span>
                              </td>
                              <td className="px-3 py-3">
                                <div className="flex flex-wrap gap-1">
                                  {s.rule_flags?.map((f, fIdx) => (
                                    <span
                                      key={fIdx}
                                      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                                        f.severity === "HIGH"
                                          ? "bg-red-50 text-red-700 border border-red-200"
                                          : f.severity === "MEDIUM"
                                          ? "bg-amber-50 text-amber-700 border border-amber-200"
                                          : "bg-gray-100 text-gray-600"
                                      }`}
                                      title={f.description}
                                    >
                                      {f.code}
                                    </span>
                                  ))}
                                </div>
                              </td>
                              <td className="px-3 py-3 text-right">
                                <button
                                  type="button"
                                  onClick={() => handleViewRiskProfile(s.student_id)}
                                  className="rounded-md border border-gray-300 px-2.5 py-1 text-xs font-semibold text-gray-700 transition hover:border-[#C10202] hover:text-[#C10202]"
                                >
                                  Details
                                </button>
                              </td>
                            </tr>
                          ))}
                          {(!atRiskData?.students || atRiskData.students.length === 0) ? (
                            <tr>
                              <td colSpan={9} className="px-3 py-8 text-center text-gray-500">
                                {atRiskLoading ? "Analyzing attendance..." : "No students match the selected filter."}
                              </td>
                            </tr>
                          ) : null}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </section>
              )}
            </div>
          </>
        ) : null}
      </div>

      {/* Student Risk Profile Modal */}
      <Modal
        open={riskModalOpen}
        onClose={() => {
          setRiskModalOpen(false);
          setSelectedRiskStudent(null);
        }}
        title={`Student Risk Profile: ${selectedRiskStudent?.student_name || "Loading..."}`}
        footer={
          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => {
                setRiskModalOpen(false);
                setSelectedRiskStudent(null);
              }}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 transition hover:bg-gray-50"
            >
              Close
            </button>
          </div>
        }
      >
        {riskProfileLoading ? (
          <div className="py-8 text-center text-sm text-gray-500">Loading risk metrics...</div>
        ) : selectedRiskStudent ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                <span className="text-[11px] font-semibold uppercase text-gray-500">Attendance</span>
                <p className="mt-1 text-xl font-bold text-gray-900">
                  {selectedRiskStudent.attendance_percentage}%
                </p>
                <p className="text-[10px] text-gray-500">
                  {selectedRiskStudent.attended_sessions} / {selectedRiskStudent.total_sessions} sessions
                </p>
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                <span className="text-[11px] font-semibold uppercase text-gray-500">Risk Level</span>
                <p
                  className={`mt-1 text-xl font-bold ${
                    selectedRiskStudent.risk_level === "HIGH"
                      ? "text-red-700"
                      : selectedRiskStudent.risk_level === "MEDIUM"
                      ? "text-amber-700"
                      : "text-emerald-700"
                  }`}
                >
                  {selectedRiskStudent.risk_level}
                </p>
                <p className="text-[10px] text-gray-500">Score: {selectedRiskStudent.risk_score}/100</p>
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                <span className="text-[11px] font-semibold uppercase text-gray-500">Velocity</span>
                <p
                  className={`mt-1 text-xl font-bold ${
                    (selectedRiskStudent.attendance_velocity ?? 0) < 0
                      ? "text-red-700"
                      : "text-emerald-700"
                  }`}
                >
                  {selectedRiskStudent.attendance_velocity !== null
                    ? `${selectedRiskStudent.attendance_velocity}%`
                    : "N/A"}
                </p>
                <p className="text-[10px] text-gray-500">Week-over-week</p>
              </div>

              <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                <span className="text-[11px] font-semibold uppercase text-gray-500">Consecutive Missed</span>
                <p className="mt-1 text-xl font-bold text-gray-900">
                  {selectedRiskStudent.consecutive_absences}
                </p>
                <p className="text-[10px] text-gray-500">
                  Max: {selectedRiskStudent.max_consecutive_absences}
                </p>
              </div>
            </div>

            {/* Explainable Rule Flags */}
            <div className="rounded-xl border border-gray-200 bg-gray-50 p-3.5">
              <h4 className="mb-2 text-xs font-bold uppercase tracking-wider text-gray-700">
                Active Rule Explanations
              </h4>
              <div className="space-y-2">
                {selectedRiskStudent.rule_flags?.map((flag, idx) => (
                  <div
                    key={idx}
                    className={`rounded-lg border p-2.5 text-xs ${
                      flag.severity === "HIGH"
                        ? "border-red-200 bg-red-50/80 text-red-800"
                        : flag.severity === "MEDIUM"
                        ? "border-amber-200 bg-amber-50/80 text-amber-800"
                        : "border-gray-200 bg-white text-gray-700"
                    }`}
                  >
                    <div className="flex items-center justify-between font-bold">
                      <span>{flag.code}</span>
                      <span className="uppercase text-[10px]">{flag.severity}</span>
                    </div>
                    <p className="mt-1 text-gray-600">{flag.description}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Recommendations */}
            <div className="rounded-xl border border-blue-200 bg-blue-50/60 p-3.5">
              <h4 className="mb-2 text-xs font-bold uppercase tracking-wider text-blue-900">
                Recommended Interventions
              </h4>
              <ul className="list-inside list-disc space-y-1 text-xs text-blue-900">
                {selectedRiskStudent.recommendations?.map((rec, rIdx) => (
                  <li key={rIdx}>{rec}</li>
                ))}
              </ul>
            </div>

            {/* Session Timeline */}
            <div>
              <h4 className="mb-2 text-xs font-bold uppercase tracking-wider text-gray-700">
                Session History Timeline
              </h4>
              <div className="max-h-48 overflow-y-auto divide-y divide-gray-100 rounded-xl border border-gray-200 bg-white">
                {selectedRiskStudent.timeline?.map((item) => (
                  <div key={item.session_id} className="flex items-center justify-between p-2.5 text-xs">
                    <div>
                      <span className="font-semibold text-gray-800">{item.session_date}</span>
                      <span className="ml-2 text-gray-400">Session #{item.session_id}</span>
                      {item.is_finalised ? (
                        <span className="ml-2 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600">
                          Finalised
                        </span>
                      ) : null}
                    </div>
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-bold ${
                        item.status === "PRESENT"
                          ? "bg-emerald-100 text-emerald-800"
                          : item.status === "PARTIAL"
                          ? "bg-amber-100 text-amber-800"
                          : "bg-red-100 text-red-800"
                      }`}
                    >
                      {item.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </Modal>


      <Modal
        open={enrollOpen}
        onClose={() => setEnrollOpen(false)}
        title="Enroll Students via ZIP"
        footer={
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setEnrollOpen(false)}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 transition hover:bg-gray-50"
            >
              Close
            </button>
            <button
              type="submit"
              form="enroll-zip-form"
              disabled={enrollBusy || !zipFile}
              className="rounded-md bg-[#C10202] px-3 py-2 text-sm font-semibold text-white transition hover:bg-[#8B1A1A] disabled:opacity-70"
            >
              {enrollBusy ? "Uploading..." : "Upload ZIP"}
            </button>
          </div>
        }
      >
        <form id="enroll-zip-form" className="space-y-3" onSubmit={handleEnrollZip}>
          <p className="text-sm text-gray-600">
            ZIP naming hint: <span className="font-semibold text-[#C10202]">RollNo_Name.jpg</span>
          </p>
          <input
            type="file"
            accept=".zip"
            onChange={(event) => setZipFile(event.target.files?.[0] || null)}
            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900"
            required
          />
        </form>

        {enrollResults.length > 0 ? (
          <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-3">
            <h4 className="mb-2 text-sm font-semibold text-gray-800">Upload Results</h4>
            <div className="max-h-48 overflow-auto space-y-1 text-xs">
              {enrollResults.map((item, index) => (
                <div
                  key={`${item.file}-${index}`}
                  className={`rounded px-2 py-1 ${
                    item.success ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"
                  }`}
                >
                  {item.file} - {item.success ? "Success" : item.reason || "Failed"}
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </Modal>

      <Modal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        title="Upload CCTV Video"
        footer={
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setUploadOpen(false)}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 transition hover:bg-gray-50"
            >
              Close
            </button>

            <button
              type="submit"
              form="upload-video-form"
              disabled={uploadBusy || !videoFile}
              className="rounded-md bg-[#C10202] px-3 py-2 text-sm font-semibold text-white transition hover:bg-[#8B1A1A] disabled:opacity-70"
            >
              {uploadBusy ? "Uploading..." : "Upload"}
            </button>
          </div>
        }
      >
        <form id="upload-video-form" className="space-y-3" onSubmit={handleUploadVideo}>
          <div>
            <label className="mb-1 block text-sm text-gray-700">Video File (MP4/AVI)</label>
            <input
              type="file"
              accept=".mp4,.avi,.mov,.mkv"
              onChange={(event) => setVideoFile(event.target.files?.[0] || null)}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900"
              required
            />
          </div>

        </form>
      </Modal>
    </div>
  );
};

export default ClassDetailPage;
