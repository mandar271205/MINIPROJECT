import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { createPolicy, getPolicies, setPolicyStatus, updatePolicy } from "@/lib/api";
import { clearToken } from "@/lib/auth";

const inputClass =
  "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 outline-none transition focus:border-[#C10202] focus:ring-2 focus:ring-[#C10202]";

const EMPTY_FORM = {
  name: "",
  present_threshold_percentage: 75,
  late_grace_seconds: 600,
  early_exit_tolerance_seconds: 600,
  reentry_min_gap_seconds: 300,
  low_confidence_flag_threshold: 0.55,
  minimum_decision_confidence: 0.45,
  minimum_valid_session_ratio: 1,
  is_default: false,
  effective_from: "",
  effective_until: "",
};

const AttendancePoliciesPage = () => {
  const navigate = useNavigate();
  const [policies, setPolicies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [forbidden, setForbidden] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getPolicies();
      setPolicies(data.policies);
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
    load();
  }, []);

  const handleLogout = () => {
    clearToken();
    navigate("/login");
  };

  const resetForm = () => {
    setForm(EMPTY_FORM);
    setEditingId(null);
  };

  const startEdit = (policy) => {
    setEditingId(policy.id);
    setForm({
      name: policy.name,
      present_threshold_percentage: policy.present_threshold_percentage,
      late_grace_seconds: policy.late_grace_seconds,
      early_exit_tolerance_seconds: policy.early_exit_tolerance_seconds,
      reentry_min_gap_seconds: policy.reentry_min_gap_seconds,
      low_confidence_flag_threshold: policy.low_confidence_flag_threshold,
      minimum_decision_confidence: policy.minimum_decision_confidence,
      minimum_valid_session_ratio: policy.minimum_valid_session_ratio,
      is_default: policy.is_default,
      effective_from: policy.effective_from || "",
      effective_until: policy.effective_until || "",
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        ...form,
        present_threshold_percentage: Number(form.present_threshold_percentage),
        late_grace_seconds: Number(form.late_grace_seconds),
        early_exit_tolerance_seconds: Number(form.early_exit_tolerance_seconds),
        reentry_min_gap_seconds: Number(form.reentry_min_gap_seconds),
        low_confidence_flag_threshold: Number(form.low_confidence_flag_threshold),
        minimum_decision_confidence: Number(form.minimum_decision_confidence),
        minimum_valid_session_ratio: Number(form.minimum_valid_session_ratio),
        effective_from: form.effective_from || null,
        effective_until: form.effective_until || null,
      };
      if (editingId) {
        await updatePolicy(editingId, payload);
        toast.success("Policy updated");
      } else {
        await createPolicy(payload);
        toast.success("Policy created");
      }
      resetForm();
      await load();
    } catch (requestError) {
      toast.error(requestError.message);
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (policy) => {
    try {
      await setPolicyStatus(policy.id, !policy.is_active);
      await load();
    } catch (requestError) {
      toast.error(requestError.message);
    }
  };

  if (forbidden) {
    return (
      <div className="min-h-screen bg-gray-50 px-4 py-8 text-gray-900">
        <div className="mx-auto max-w-xl rounded-2xl border border-gray-200 bg-white p-6 text-center">
          <p className="text-gray-700">Only HOD accounts can manage attendance policies.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8 text-gray-900">
      <div className="mx-auto max-w-5xl">
        <header className="mb-8 flex flex-col gap-4 rounded-2xl bg-[#C10202] p-5 text-white shadow-sm md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.28em] text-white/80">CCTV Attendance System</p>
            <h1 className="mt-2 text-2xl font-bold">Attendance Policies</h1>
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

        <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          These thresholds configure the AI attendance-recommendation engine only. They do not finalise attendance -
          faculty review and finalisation is implemented in a later phase.
        </div>

        {error ? (
          <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
        ) : null}

        <div className="grid gap-6 md:grid-cols-[1.4fr_1fr]">
          <div className="rounded-2xl border border-gray-200 bg-white p-6">
            <h2 className="mb-4 text-lg font-semibold">Policies</h2>
            {loading ? (
              <p className="text-gray-600">Loading policies...</p>
            ) : policies.length === 0 ? (
              <p className="text-gray-600">No policies configured yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 text-gray-500">
                      <th className="py-2 pr-3">Name</th>
                      <th className="py-2 pr-3">Scope</th>
                      <th className="py-2 pr-3">Threshold</th>
                      <th className="py-2 pr-3">Status</th>
                      <th className="py-2 pr-3">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {policies.map((p) => (
                      <tr key={p.id} className="border-b border-gray-100">
                        <td className="py-2 pr-3">
                          {p.name}
                          {p.name.includes("Development Default") ? (
                            <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
                              uncalibrated default
                            </span>
                          ) : null}
                        </td>
                        <td className="py-2 pr-3 text-gray-600">
                          {p.subject_id || p.division_id
                            ? `subject=${p.subject_id ?? "-"} division=${p.division_id ?? "-"}`
                            : p.is_default
                              ? "Global default"
                              : "Unscoped"}
                        </td>
                        <td className="py-2 pr-3">{p.present_threshold_percentage}%</td>
                        <td className="py-2 pr-3">
                          <span
                            className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                              p.is_active ? "bg-green-100 text-green-700" : "bg-gray-200 text-gray-600"
                            }`}
                          >
                            {p.is_active ? "Active" : "Inactive"}
                          </span>
                        </td>
                        <td className="py-2 pr-3">
                          <button
                            type="button"
                            className="mr-2 text-[#C10202] hover:underline"
                            onClick={() => startEdit(p)}
                          >
                            Edit
                          </button>
                          <button type="button" className="text-gray-600 hover:underline" onClick={() => toggleActive(p)}>
                            {p.is_active ? "Deactivate" : "Activate"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <form onSubmit={handleSubmit} className="rounded-2xl border border-gray-200 bg-white p-6">
            <h2 className="mb-4 text-lg font-semibold">{editingId ? "Edit Policy" : "New Policy"}</h2>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-semibold text-gray-500">Name</label>
                <input
                  className={inputClass}
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  required
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-gray-500">Present threshold (%)</label>
                <input
                  type="number"
                  step="0.1"
                  className={inputClass}
                  value={form.present_threshold_percentage}
                  onChange={(e) => setForm({ ...form, present_threshold_percentage: e.target.value })}
                  required
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-gray-500">Late grace (seconds)</label>
                <input
                  type="number"
                  className={inputClass}
                  value={form.late_grace_seconds}
                  onChange={(e) => setForm({ ...form, late_grace_seconds: e.target.value })}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-gray-500">Early-exit tolerance (seconds)</label>
                <input
                  type="number"
                  className={inputClass}
                  value={form.early_exit_tolerance_seconds}
                  onChange={(e) => setForm({ ...form, early_exit_tolerance_seconds: e.target.value })}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-gray-500">Re-entry min gap (seconds)</label>
                <input
                  type="number"
                  className={inputClass}
                  value={form.reentry_min_gap_seconds}
                  onChange={(e) => setForm({ ...form, reentry_min_gap_seconds: e.target.value })}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs font-semibold text-gray-500">Low-confidence flag threshold</label>
                  <input
                    type="number"
                    step="0.01"
                    className={inputClass}
                    value={form.low_confidence_flag_threshold}
                    onChange={(e) => setForm({ ...form, low_confidence_flag_threshold: e.target.value })}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-semibold text-gray-500">Minimum decision confidence</label>
                  <input
                    type="number"
                    step="0.01"
                    className={inputClass}
                    value={form.minimum_decision_confidence}
                    onChange={(e) => setForm({ ...form, minimum_decision_confidence: e.target.value })}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-xs font-semibold text-gray-500">Effective from</label>
                  <input
                    type="date"
                    className={inputClass}
                    value={form.effective_from}
                    onChange={(e) => setForm({ ...form, effective_from: e.target.value })}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-semibold text-gray-500">Effective until</label>
                  <input
                    type="date"
                    className={inputClass}
                    value={form.effective_until}
                    onChange={(e) => setForm({ ...form, effective_until: e.target.value })}
                  />
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={form.is_default}
                  onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
                />
                Set as global default (unscoped fallback)
              </label>
            </div>

            <div className="mt-4 flex gap-2">
              <button
                type="submit"
                disabled={saving}
                className="rounded-lg bg-[#C10202] px-4 py-2 font-semibold text-white transition hover:bg-[#a10101] disabled:opacity-60"
              >
                {saving ? "Saving..." : editingId ? "Save Changes" : "Create Policy"}
              </button>
              {editingId ? (
                <button type="button" onClick={resetForm} className="rounded-lg border border-gray-300 px-4 py-2 text-gray-700">
                  Cancel
                </button>
              ) : null}
            </div>
          </form>
        </div>
      </div>
    </div>
  );
};

export default AttendancePoliciesPage;
