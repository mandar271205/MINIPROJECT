const STATUS_CLASSES = {
  PRESENT: "bg-emerald-50 text-emerald-700 border-emerald-200",
  LATE_ABSENT: "bg-amber-50 text-amber-700 border-amber-200",
  ABSENT: "bg-rose-50 text-rose-700 border-rose-200",
  pending: "bg-gray-100 text-gray-700 border-gray-200",
  processing: "bg-amber-50 text-amber-700 border-amber-200",
  done: "bg-emerald-50 text-emerald-700 border-emerald-200",
  error: "bg-rose-50 text-rose-700 border-rose-200",
};

const StatusBadge = ({ status }) => {
  const key = String(status || "pending");
  const classes = STATUS_CLASSES[key] || "bg-gray-100 text-gray-700 border-gray-200";

  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${classes}`}>
      {key.replace("_", " ")}
    </span>
  );
};

export default StatusBadge;
