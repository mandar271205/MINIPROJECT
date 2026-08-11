import { clearToken, getToken } from "@/lib/auth";

const API_BASE_URL = (import.meta.env.NEXT_PUBLIC_API_URL || import.meta.env.VITE_API_URL || "http://localhost:5000").replace(/\/+$/, "");

const parseFilename = (contentDisposition, fallback) => {
  if (!contentDisposition) {
    return fallback;
  }
  const match = contentDisposition.match(/filename=\"?([^\";]+)\"?/i);
  return match ? match[1] : fallback;
};

const request = async (path, options = {}) => {
  const {
    method = "GET",
    body,
    headers = {},
    isMultipart = false,
    responseType = "json",
    fallbackFilename = "download.bin",
  } = options;

  const token = getToken();
  const requestHeaders = { ...headers };

  if (token) {
    requestHeaders.Authorization = `Bearer ${token}`;
  }

  if (!isMultipart) {
    requestHeaders["Content-Type"] = requestHeaders["Content-Type"] || "application/json";
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: requestHeaders,
    body: body ? (isMultipart ? body : JSON.stringify(body)) : undefined,
  });

  if (response.status === 401) {
    clearToken();
  }

  if (!response.ok) {
    let message = "Request failed";
    try {
      const raw = await response.text();
      try {
        const errorBody = JSON.parse(raw);
        message = errorBody.error || errorBody.message || message;
      } catch {
        message = raw || message;
      }
    } catch {
      // body unreadable, keep default message
    }
    throw new Error(message);
  }

  if (responseType === "blob") {
    const blob = await response.blob();
    const filename = parseFilename(response.headers.get("content-disposition"), fallbackFilename);
    return { blob, filename };
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
};

export const login = async ({ email, password, role }) =>
  request("/api/auth/login", { method: "POST", body: { email, password, role } });

export const register = async ({ name, email, password }) =>
  request("/api/auth/register", { method: "POST", body: { name, email, password } });

export const createFaculty = async ({ name, email, password }) =>
  request("/api/auth/faculty", { method: "POST", body: { name, email, password } });

export const getMe = async () => request("/api/auth/me");

export const getClasses = async () => request("/api/classes");

export const createClass = async ({ name, subject, grace_period_minutes }) =>
  request("/api/classes", {
    method: "POST",
    body: { name, subject, grace_period_minutes },
  });

export const getClass = async (id) => request(`/api/classes/${id}`);

export const updateClass = async (id, grace_period_minutes) =>
  request(`/api/classes/${id}`, {
    method: "PUT",
    body: { grace_period_minutes },
  });

export const deleteClass = async (id) =>
  request(`/api/classes/${id}`, {
    method: "DELETE",
  });

export const getStudents = async (classId) => request(`/api/classes/${classId}/students`);

export const enrollZip = async (classId, zipFile) => {
  const formData = new FormData();
  formData.append("file", zipFile);
  return request(`/api/classes/${classId}/enroll-zip`, {
    method: "POST",
    body: formData,
    isMultipart: true,
  });
};

export const deleteStudent = async (classId, studentId) =>
  request(`/api/classes/${classId}/students/${studentId}`, {
    method: "DELETE",
  });

export const uploadVideo = async ({ classId, file, classStartTime }) => {
  const formData = new FormData();
  formData.append("video", file);
  formData.append("class_id", String(classId));
  if (classStartTime) {
    formData.append("class_start_time", classStartTime);
  }

  return request("/api/attendance/upload-video", {
    method: "POST",
    body: formData,
    isMultipart: true,
  });
};

export const setStartTime = async (sessionId, classStartTime) =>
  request(`/api/attendance/sessions/${sessionId}/set-start-time`, {
    method: "POST",
    body: { class_start_time: classStartTime },
  });

export const getSessions = async (classId = null) => {
  const query = classId ? `?class_id=${encodeURIComponent(classId)}` : "";
  return request(`/api/attendance/sessions${query}`);
};

export const getSession = async (sessionId) => request(`/api/attendance/sessions/${sessionId}`);

export const getSessionStatus = async (sessionId) => request(`/api/attendance/sessions/${sessionId}/status`);

export const downloadXLSX = async (sessionId) =>
  request(`/api/reports/${sessionId}/xlsx`, {
    responseType: "blob",
    fallbackFilename: `attendance_session_${sessionId}.xlsx`,
  });

export const downloadPDF = async (sessionId) =>
  request(`/api/reports/${sessionId}/pdf`, {
    responseType: "blob",
    fallbackFilename: `attendance_session_${sessionId}.pdf`,
  });
