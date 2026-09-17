import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import Modal from "@/components/Modal";
import StatusBadge from "@/components/StatusBadge";
import {
  deleteStudent,
  enrollZip,
  getClass,
  getSessionStatus,
  getSessions,
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
              <div className="mb-4 flex gap-2">
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
              ) : (
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
              )}
            </div>
          </>
        ) : null}
      </div>

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
