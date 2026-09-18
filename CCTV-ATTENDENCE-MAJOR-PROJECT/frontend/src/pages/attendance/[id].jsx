import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import StatusBadge from "@/components/StatusBadge";
import {
  downloadPDF,
  downloadXLSX,
  getRecognitionEvidence,
  getSession,
  getSessionPresence,
  getTrackObservations,
  reconstructPresence,
} from "@/lib/api";
import { getTokenUser } from "@/lib/auth";

const AttendanceReportPage = () => {
  const { id } = useParams();
  const sessionId = Number(id);

  const [sessionInfo, setSessionInfo] = useState(null);
  const [classInfo, setClassInfo] = useState(null);
  const [records, setRecords] = useState([]);
  const [reenrollmentCount, setReenrollmentCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const isStudent = getTokenUser()?.role === "student";

  const [evidence, setEvidence] = useState(null);
  const [evidenceLoading, setEvidenceLoading] = useState(true);
  const [evidenceError, setEvidenceError] = useState("");
  const [expandedTrackId, setExpandedTrackId] = useState(null);
  const [observations, setObservations] = useState([]);
  const [observationsPage, setObservationsPage] = useState(1);
  const [observationsTotal, setObservationsTotal] = useState(0);
  const [observationsLoading, setObservationsLoading] = useState(false);
  const OBSERVATIONS_PER_PAGE = 20;

  const [presence, setPresence] = useState(null);
  const [presenceLoading, setPresenceLoading] = useState(true);
  const [presenceError, setPresenceError] = useState("");
  const [reconstructing, setReconstructing] = useState(false);
  const [expandedPresenceStudentId, setExpandedPresenceStudentId] = useState(null);

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
        setReenrollmentCount(response.students_requiring_reenrollment || 0);
      } catch (requestError) {
        setError(requestError.message);
      } finally {
        setLoading(false);
      }
    };

    load();
  }, [sessionId]);

  useEffect(() => {
    if (!Number.isInteger(sessionId) || isStudent) {
      setEvidenceLoading(false);
      return;
    }

    const loadEvidence = async () => {
      setEvidenceLoading(true);
      setEvidenceError("");
      try {
        const data = await getRecognitionEvidence(sessionId);
        setEvidence(data);
      } catch (requestError) {
        setEvidenceError(requestError.message);
      } finally {
        setEvidenceLoading(false);
      }
    };

    loadEvidence();
  }, [sessionId, isStudent]);

  const loadPresence = async () => {
    if (!Number.isInteger(sessionId) || isStudent) {
      setPresenceLoading(false);
      return;
    }
    setPresenceLoading(true);
    setPresenceError("");
    try {
      const data = await getSessionPresence(sessionId);
      setPresence(data);
    } catch (requestError) {
      setPresenceError(requestError.message);
    } finally {
      setPresenceLoading(false);
    }
  };

  useEffect(() => {
    loadPresence();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, isStudent]);

  const handleReconstructPresence = async () => {
    setReconstructing(true);
    setPresenceError("");
    try {
      await reconstructPresence(sessionId);
      await loadPresence();
    } catch (requestError) {
      setPresenceError(requestError.message);
    } finally {
      setReconstructing(false);
    }
  };

  const toggleTrackObservations = async (trackId) => {
    if (expandedTrackId === trackId) {
      setExpandedTrackId(null);
      return;
    }
    setExpandedTrackId(trackId);
    setObservationsPage(1);
    await loadObservationsPage(trackId, 1);
  };

  const loadObservationsPage = async (trackId, page) => {
    setObservationsLoading(true);
    try {
      const data = await getTrackObservations(sessionId, trackId, { page, perPage: OBSERVATIONS_PER_PAGE });
      setObservations(data.observations || []);
      setObservationsTotal(data.total || 0);
      setObservationsPage(page);
    } catch (requestError) {
      setEvidenceError(requestError.message);
    } finally {
      setObservationsLoading(false);
    }
  };

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

            {reenrollmentCount > 0 ? (
              <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
                Attendance was not generated for {reenrollmentCount} student{reenrollmentCount === 1 ? "" : "s"}{" "}
                because compatible face templates are unavailable. Re-enrolment is required.
              </div>
            ) : null}

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

            {!isStudent ? (
              <section className="mt-5 rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
                <h2 className="mb-3 text-lg font-semibold">Recognition Evidence</h2>
                <p className="mb-3 text-xs text-gray-500">
                  Temporary face tracks and multi-observation voting outcomes for this session -
                  diagnostic evidence, not a final attendance decision.
                </p>

                {evidenceLoading ? (
                  <p className="text-sm text-gray-600">Loading recognition evidence...</p>
                ) : null}

                {!evidenceLoading && evidenceError ? (
                  /permission|forbidden|403|401/i.test(evidenceError) ? (
                    <p className="text-sm text-gray-600">
                      You do not have permission to view recognition evidence for this session.
                    </p>
                  ) : (
                    <p className="text-sm text-red-700">{evidenceError}</p>
                  )
                ) : null}

                {!evidenceLoading && !evidenceError && evidence ? (
                  <>
                    <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
                      <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center">
                        <p className="text-2xl font-bold text-gray-900">{evidence.summary.total_tracks}</p>
                        <p className="text-xs text-gray-500">Total Tracks</p>
                      </div>
                      <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-center">
                        <p className="text-2xl font-bold text-emerald-700">{evidence.summary.confirmed_tracks}</p>
                        <p className="text-xs text-emerald-700">Confirmed</p>
                      </div>
                      <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center">
                        <p className="text-2xl font-bold text-gray-700">{evidence.summary.unknown_tracks}</p>
                        <p className="text-xs text-gray-500">Unknown</p>
                      </div>
                      <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-center">
                        <p className="text-2xl font-bold text-amber-700">{evidence.summary.ambiguous_tracks}</p>
                        <p className="text-xs text-amber-700">Ambiguous</p>
                      </div>
                      <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center">
                        <p className="text-2xl font-bold text-gray-900">{evidence.summary.total_observations}</p>
                        <p className="text-xs text-gray-500">Observations</p>
                      </div>
                    </div>

                    <div className="overflow-x-auto">
                      <table className="min-w-full text-sm">
                        <thead>
                          <tr className="border-b border-gray-200 text-left text-gray-600">
                            <th className="px-3 py-2">Track</th>
                            <th className="px-3 py-2">State</th>
                            <th className="px-3 py-2">Confirmed Student</th>
                            <th className="px-3 py-2">Mean Confidence</th>
                            <th className="px-3 py-2">First / Last Seen</th>
                            <th className="px-3 py-2">Conflict</th>
                            <th className="px-3 py-2">Observations</th>
                          </tr>
                        </thead>
                        <tbody>
                          {evidence.tracks.map((track) => (
                            <>
                              <tr key={track.track_id} className="border-b border-gray-100">
                                <td className="px-3 py-2 text-gray-500">{track.track_key}</td>
                                <td className="px-3 py-2">
                                  <StatusBadge status={track.state} />
                                </td>
                                <td className="px-3 py-2">
                                  {track.confirmed_student_id ? `#${track.confirmed_student_id}` : "-"}
                                </td>
                                <td className="px-3 py-2">
                                  {track.mean_confidence != null ? track.mean_confidence.toFixed(2) : "-"}
                                </td>
                                <td className="px-3 py-2 text-xs text-gray-500">
                                  {track.first_seen_seconds.toFixed(1)}s - {track.last_seen_seconds.toFixed(1)}s
                                </td>
                                <td className="px-3 py-2">
                                  {track.identity_conflict ? (
                                    <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
                                      Conflict
                                    </span>
                                  ) : (
                                    <span className="text-xs text-gray-400">-</span>
                                  )}
                                </td>
                                <td className="px-3 py-2">
                                  <button
                                    type="button"
                                    onClick={() => toggleTrackObservations(track.track_id)}
                                    className="rounded-md border border-[#C10202] px-2 py-1 text-xs font-semibold text-[#C10202] transition hover:bg-red-50"
                                  >
                                    {expandedTrackId === track.track_id ? "Hide" : `View (${track.observation_count})`}
                                  </button>
                                </td>
                              </tr>
                              {expandedTrackId === track.track_id ? (
                                <tr key={`${track.track_id}-observations`}>
                                  <td colSpan={7} className="bg-gray-50 px-3 py-3">
                                    {observationsLoading ? (
                                      <p className="text-xs text-gray-500">Loading observations...</p>
                                    ) : (
                                      <>
                                        <div className="max-h-64 overflow-auto">
                                          <table className="min-w-full text-xs">
                                            <thead>
                                              <tr className="text-left text-gray-500">
                                                <th className="px-2 py-1">Timestamp</th>
                                                <th className="px-2 py-1">Evidence State</th>
                                                <th className="px-2 py-1">Top-1</th>
                                                <th className="px-2 py-1">Top-1 Sim</th>
                                                <th className="px-2 py-1">Margin</th>
                                              </tr>
                                            </thead>
                                            <tbody>
                                              {observations.map((obs) => (
                                                <tr key={obs.id} className="border-t border-gray-200">
                                                  <td className="px-2 py-1">{obs.timestamp_seconds.toFixed(1)}s</td>
                                                  <td className="px-2 py-1">{obs.evidence_state}</td>
                                                  <td className="px-2 py-1">
                                                    {obs.top1_student_id ? `#${obs.top1_student_id}` : "-"}
                                                  </td>
                                                  <td className="px-2 py-1">
                                                    {obs.top1_similarity != null ? obs.top1_similarity.toFixed(3) : "-"}
                                                  </td>
                                                  <td className="px-2 py-1">
                                                    {obs.similarity_margin != null ? obs.similarity_margin.toFixed(3) : "-"}
                                                  </td>
                                                </tr>
                                              ))}
                                              {observations.length === 0 ? (
                                                <tr>
                                                  <td colSpan={5} className="px-2 py-3 text-center text-gray-500">
                                                    No observations recorded.
                                                  </td>
                                                </tr>
                                              ) : null}
                                            </tbody>
                                          </table>
                                        </div>
                                        <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
                                          <span>
                                            Page {observationsPage} of{" "}
                                            {Math.max(1, Math.ceil(observationsTotal / OBSERVATIONS_PER_PAGE))}
                                          </span>
                                          <div className="flex gap-2">
                                            <button
                                              type="button"
                                              disabled={observationsPage <= 1}
                                              onClick={() => loadObservationsPage(track.track_id, observationsPage - 1)}
                                              className="rounded border border-gray-300 px-2 py-1 disabled:opacity-40"
                                            >
                                              Prev
                                            </button>
                                            <button
                                              type="button"
                                              disabled={observationsPage * OBSERVATIONS_PER_PAGE >= observationsTotal}
                                              onClick={() => loadObservationsPage(track.track_id, observationsPage + 1)}
                                              className="rounded border border-gray-300 px-2 py-1 disabled:opacity-40"
                                            >
                                              Next
                                            </button>
                                          </div>
                                        </div>
                                      </>
                                    )}
                                  </td>
                                </tr>
                              ) : null}
                            </>
                          ))}
                          {evidence.tracks.length === 0 ? (
                            <tr>
                              <td colSpan={7} className="px-3 py-6 text-center text-gray-500">
                                No face tracks recorded for this session yet.
                              </td>
                            </tr>
                          ) : null}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : null}
              </section>
            ) : null}

            {!isStudent ? (
              <section className="mt-5 rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-lg font-semibold">Presence Reconstruction</h2>
                  <button
                    type="button"
                    onClick={handleReconstructPresence}
                    disabled={reconstructing}
                    className="rounded-lg border border-[#C10202] px-3 py-2 text-sm font-semibold text-[#C10202] transition hover:bg-red-50 disabled:opacity-60"
                  >
                    {reconstructing ? "Reconstructing..." : "Reconstruct Presence"}
                  </button>
                </div>

                <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                  Presence percentage is reconstructed from confirmed recognition evidence. Final
                  attendance status will be assigned in a later verification phase.
                </div>

                {presenceLoading ? (
                  <p className="text-sm text-gray-600">Loading presence reconstruction...</p>
                ) : null}

                {!presenceLoading && presenceError ? (
                  /permission|forbidden|403|401/i.test(presenceError) ? (
                    <p className="text-sm text-gray-600">
                      You do not have permission to view presence data for this session.
                    </p>
                  ) : (
                    <p className="text-sm text-red-700">{presenceError}</p>
                  )
                ) : null}

                {!presenceLoading && !presenceError && presence ? (
                  <>
                    <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                      <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center">
                        <p className="text-sm font-semibold text-gray-900">{presence.reconstruction_status}</p>
                        <p className="text-xs text-gray-500">Status</p>
                      </div>
                      <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center">
                        <p className="text-sm font-semibold text-gray-900">
                          {presence.actual_duration_seconds != null
                            ? `${presence.actual_duration_seconds.toFixed(0)}s`
                            : "-"}
                        </p>
                        <p className="text-xs text-gray-500">Video Duration</p>
                      </div>
                      <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center">
                        <p className="text-sm font-semibold text-gray-900">
                          {presence.valid_duration_seconds != null
                            ? `${presence.valid_duration_seconds.toFixed(0)}s`
                            : "-"}
                        </p>
                        <p className="text-xs text-gray-500">Valid Session Duration</p>
                      </div>
                      <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center">
                        <p className="text-sm font-semibold text-gray-900">{presence.algorithm_version || "-"}</p>
                        <p className="text-xs text-gray-500">Algorithm Version</p>
                      </div>
                    </div>

                    {presence.reconstruction_error ? (
                      <p className="mb-3 text-xs text-red-700">{presence.reconstruction_error}</p>
                    ) : null}

                    {presence.students.length === 0 && presence.ineligible_students.length === 0 ? (
                      <p className="text-sm text-gray-500">
                        No presence data yet. Use "Reconstruct Presence" once video processing has
                        completed.
                      </p>
                    ) : (
                      <div className="overflow-x-auto">
                        <table className="min-w-full text-sm">
                          <thead>
                            <tr className="border-b border-gray-200 text-left text-gray-600">
                              <th className="px-3 py-2">Student</th>
                              <th className="px-3 py-2">Windows</th>
                              <th className="px-3 py-2">Observed</th>
                              <th className="px-3 py-2">Inferred</th>
                              <th className="px-3 py-2">Total</th>
                              <th className="px-3 py-2">Percentage</th>
                              <th className="px-3 py-2">First / Last</th>
                              <th className="px-3 py-2">Mean Confidence</th>
                            </tr>
                          </thead>
                          <tbody>
                            {presence.students.map((s) => (
                              <>
                                <tr key={s.student_id} className="border-b border-gray-100">
                                  <td className="px-3 py-2">#{s.student_id}</td>
                                  <td className="px-3 py-2">
                                    <button
                                      type="button"
                                      onClick={() =>
                                        setExpandedPresenceStudentId(
                                          expandedPresenceStudentId === s.student_id ? null : s.student_id,
                                        )
                                      }
                                      className="text-[#C10202] underline"
                                    >
                                      {s.window_count}
                                    </button>
                                  </td>
                                  <td className="px-3 py-2">{s.observed_presence_seconds.toFixed(1)}s</td>
                                  <td className="px-3 py-2">{s.inferred_gap_seconds.toFixed(1)}s</td>
                                  <td className="px-3 py-2">{s.total_presence_seconds.toFixed(1)}s</td>
                                  <td className="px-3 py-2">
                                    {s.presence_percentage != null ? `${s.presence_percentage.toFixed(1)}%` : "-"}
                                  </td>
                                  <td className="px-3 py-2 text-xs text-gray-500">
                                    {s.first_confirmed_presence_seconds != null
                                      ? `${s.first_confirmed_presence_seconds.toFixed(1)}s - ${s.last_confirmed_presence_seconds.toFixed(1)}s`
                                      : "-"}
                                  </td>
                                  <td className="px-3 py-2">
                                    {s.mean_confidence != null ? s.mean_confidence.toFixed(2) : "-"}
                                  </td>
                                </tr>
                                {expandedPresenceStudentId === s.student_id && s.windows ? (
                                  <tr key={`${s.student_id}-windows`}>
                                    <td colSpan={8} className="bg-gray-50 px-3 py-3">
                                      <table className="min-w-full text-xs">
                                        <thead>
                                          <tr className="text-left text-gray-500">
                                            <th className="px-2 py-1">Window</th>
                                            <th className="px-2 py-1">Start</th>
                                            <th className="px-2 py-1">End</th>
                                            <th className="px-2 py-1">Observed</th>
                                            <th className="px-2 py-1">Inferred</th>
                                            <th className="px-2 py-1">Total</th>
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {s.windows.map((w) => (
                                            <tr key={w.window_index} className="border-t border-gray-200">
                                              <td className="px-2 py-1">{w.window_index}</td>
                                              <td className="px-2 py-1">{w.start_seconds.toFixed(1)}s</td>
                                              <td className="px-2 py-1">{w.end_seconds.toFixed(1)}s</td>
                                              <td className="px-2 py-1">{w.observed_duration_seconds.toFixed(1)}s</td>
                                              <td className="px-2 py-1">{w.inferred_gap_seconds.toFixed(1)}s</td>
                                              <td className="px-2 py-1">{w.total_duration_seconds.toFixed(1)}s</td>
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                    </td>
                                  </tr>
                                ) : null}
                              </>
                            ))}
                            {presence.ineligible_students.map((s) => (
                              <tr key={`ineligible-${s.student_id}`} className="border-b border-gray-100 bg-amber-50">
                                <td className="px-3 py-2">#{s.student_id}</td>
                                <td className="px-3 py-2 text-xs text-amber-700" colSpan={7}>
                                  Re-enrolment required ({s.reason_code}) - presence not calculated.
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                ) : null}
              </section>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
};

export default AttendanceReportPage;
