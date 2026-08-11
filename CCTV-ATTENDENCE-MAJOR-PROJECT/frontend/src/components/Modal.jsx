import { X } from "lucide-react";

const Modal = ({ open, onClose, title, children, footer }) => {
  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
      <div className="w-full max-w-xl rounded-xl border border-gray-200 bg-white shadow-xl">
        <div className="flex items-center justify-between rounded-t-xl bg-[#C10202] px-6 py-4 text-white">
          <h3 className="text-lg font-semibold">{title}</h3>
          <button
            type="button"
            className="rounded-full p-1 text-white/80 transition hover:bg-white/10 hover:text-white"
            onClick={onClose}
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        <div className="max-h-[70vh] overflow-auto px-6 py-4">{children}</div>

        {footer ? <div className="border-t border-gray-200 px-6 py-4">{footer}</div> : null}
      </div>
    </div>
  );
};

export default Modal;
