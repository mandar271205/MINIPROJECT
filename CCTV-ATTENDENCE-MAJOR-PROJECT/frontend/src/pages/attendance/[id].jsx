import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import StatusBadge from "@/components/StatusBadge";
import { downloadPDF, downloadXLSX, getSession } from "@/lib/api";

const AttendanceReportPage = () => {
  const { id } = useParams();
  const sessionId = Number(id);

  const [sessionInfo, setSessionInfo] = useState(null);
  const [classInfo, setClassInfo] = useState(null);
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = async () => {
      if (!Number.isInteger(sessionId)) {
        setError("Invalid session id");
        setLoading(false);
        return;
      }

      setLoading(true);
      setError("");

      try {
        const response = await getSession(sessionId);
        setSessionInfo(response.session);
        setClassInfo(response.class);
        setRecords(response.records || []);
      } catch (requestError) {
        setError(requestError.message);
      } finally {
        setLoading(false);
      }
    };

    load();
  }, [sessionId]);

  const summary = useMemo(() => {
    const present = records.filter((item) => item.status === "PRESENT").length;
    const lateAbsent = records.filter((item) => item.status === "LATE_ABSENT").length;
    const absent = records.filter((item) => item.status === "ABSENT").length;
    return { present, lateAbsent, absent };
  }, [records]);

  const flaggedForReview = useMemo(() => records.filter((item) => item.flagged), [records]);

  const triggerDownload = async (type) => {
    try {
      const payload = type === "xlsx" ? await downloadXLSX(sessionId) : await downloadPDF(sessionId);
      const blobUrl = URL.createObjectURL(payload.blob);
      const anchor = document.createElement("a");
      anchor.href = blobUrl;
      anchor.download = payload.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(blobUrl);
    } catch (downloadError) {
      setError(downloadError.message);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8 text-gray-900">
      <div className="mx-auto max-w-6xl">
        <div className="mb-5 flex items-center justify-between">
          <Link to="/dashboard" className="text-sm font-semibold text-[#C10202] hover:text-[#8B1A1A]">
            &larr; Dashboard
          </Link>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => triggerDownload("xlsx")}
              className="rounded-lg bg-[#C10202] px-3 py-2 text-sm font-semibold text-white transition hover:bg-[#8B1A1A]"
            >
              Download XLSX
            </button>
            <button
              type="button"
              onClick={() => triggerDownload("pdf")}
              className="rounded-lg border border-[#C10202] px-3 py-2 text-sm font-semibold text-[#C10202] transition hover:bg-red-50"
            >
              Download PDF
            </button>
          </div>
        </div>

        {error ? (
          <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
        ) : null}

        {loading ? (
          <div className="rounded-xl border border-gray-200 bg-white p-6 text-gray-600">Loading session report...</div>
        ) : null}

        {!loading && sessionInfo && classInfo ? (
          <>
            <header className="rounded-2xl bg-[#C10202] p-5 text-white shadow-sm">
              <div className="flex flex-wrap items-center gap-4">
                <img src="/assets/image.png" alt="SPIT Logo" className="h-10" />
                <div>
                  <p className="text-xs uppercase tracking-[0.24em] text-white/80">Attendance Session</p>
                  <h1 className="mt-2 text-3xl font-bold">{classInfo.name}</h1>
                  <p className="mt-1 text-white/80">{classInfo.subject}</p>
                </div>
              </div>

              <div className="mt-4 grid gap-3 md:grid-cols-3">
                <div className="rounded-lg border border-gray-200 bg-white p-3 text-gray-900">
                  <p className="text-xs text-gray-500">Session Date</p>
                  <p className="mt-1 font-semibold">{sessionInfo.session_date}</p>
                </div>
                <div className="rounded-lg border border-gray-200 bg-white p-3 text-gray-900">
                  <p className="text-xs text-gray-500">Class Start Time</p>
                  <p className="mt-1 font-semibold">
                    {sessionInfo.class_start_time ? new Date(sessionInfo.class_start_time).toLocaleString() : "-"}
                  </p>
                </div>
                <div className="rounded-lg border border-gray-200 bg-white p-3 text-gray-900">
                  <p className="text-xs text-gray-500">Grace Period</p>
                  <p className="mt-1 font-semibold">{classInfo.grace_period_minutes} min</p>
                </div>
              </div>
            </header>

            <section className="mt-5 grid gap-3 md:grid-cols-3">
              <article className="rounded-xl border border-emerald-200 bg-white p-4 shadow-sm">
                <p className="text-xs uppercase tracking-[0.2em] text-emerald-600">Present</p>
                <p className="mt-2 text-3xl font-bold text-emerald-700">{summary.present}</p>
              </article>
              <article className="rounded-xl border border-amber-200 bg-white p-4 shadow-sm">
                <p className="text-xs uppercase tracking-[0.2em] text-amber-600">Late-Absent</p>
                <p className="mt-2 text-3xl font-bold text-amber-700">{summary.lateAbsent}</p>
              </article>
              <article className="rounded-xl border border-red-200 bg-white p-4 shadow-sm">
                <p className="text-xs uppercase tracking-[0.2em] text-red-600">Absent</p>
                <p className="mt-2 text-3xl font-bold text-red-700">{summary.absent}</p>
              </article>
            </section>

            <section className="mt-5 rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
              <h2 className="mb-3 text-lg font-semibold">Attendance Table</h2>

              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 text-left text-gray-600">
                      <th className="px-3 py-2">Roll No</th>
                      <th className="px-3 py-2">Name</th>
                      <th className="px-3 py-2">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {records.map((record) => (
                      <tr key={record.id} className="border-b border-gray-100">
                        <td className="px-3 py-2 text-[#C10202]">{record.roll_number}</td>
                        <td className="px-3 py-2">{record.name}</td>
                        <td className="px-3 py-2">
                          <StatusBadge status={record.status} />
                        </td>
                      </tr>
                    ))}
                    {records.length === 0 ? (
                      <tr>
                        <td colSpan={3} className="px-3 py-6 text-center text-gray-500">
                          No attendance records generated yet.
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="mt-5 rounded-2xl border border-amber-200 bg-white p-5 shadow-sm">
              <h2 className="mb-3 text-lg font-semibold text-amber-700">Flagged for Review</h2>

              {flaggedForReview.length === 0 ? (
                <p className="text-sm text-amber-700">No borderline matches were flagged.</p>
              ) : (
                <div className="space-y-2 text-sm">
                  {flaggedForReview.map((record) => (
                    <div
                      key={`flag-${record.id}`}
                      className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-700"
                    >
                      {record.roll_number} - {record.name}
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        ) : null}
      </div>
    </div>
  );
};

export default AttendanceReportPage;
