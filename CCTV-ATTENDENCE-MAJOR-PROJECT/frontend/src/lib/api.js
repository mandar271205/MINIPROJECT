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
        // Phase 1 routes use {"error": "text"}; Phase 2 routes use the
        // standardized {"error": {"code", "message"}} envelope.
        message =
          (errorBody.error && errorBody.error.message) ||
          (typeof errorBody.error === "string" ? errorBody.error : null) ||
          errorBody.message ||
          message;
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

// Public self-registration can only ever create a "student" account -
// the backend rejects any other role outright, so it is sent explicitly
// here for clarity even though the server also defaults to it.
export const register = async ({ name, email, password }) =>
  request("/api/auth/register", { method: "POST", body: { name, email, password, role: "student" } });

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

// --- Phase 4: recognition evidence (tracks/observations) ------------------

export const getRecognitionEvidence = async (sessionId) =>
  (await request(`/api/attendance/sessions/${sessionId}/recognition-evidence`)).data;

export const getTrackObservations = async (sessionId, trackId, { page = 1, perPage = 50 } = {}) =>
  (
    await request(
      `/api/attendance/sessions/${sessionId}/tracks/${trackId}/observations?page=${page}&per_page=${perPage}`,
    )
  ).data;

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

// --- Phase 2: academic hierarchy (HOD-managed) ---------------------------
// These endpoints return the standardized {success, data, message} /
// {success, error: {code, message}} envelope, unlike the Phase 1 routes
// above. `request()` already throws on non-2xx with a readable message.

export const getAcademicYears = async () => (await request("/api/academic/years")).data;
export const createAcademicYear = async (payload) =>
  (await request("/api/academic/years", { method: "POST", body: payload })).data;
export const updateAcademicYear = async (id, payload) =>
  (await request(`/api/academic/years/${id}`, { method: "PUT", body: payload })).data;
export const deleteAcademicYear = async (id) => request(`/api/academic/years/${id}`, { method: "DELETE" });

export const getSemesters = async (academicYearId) => {
  const query = academicYearId ? `?academic_year_id=${encodeURIComponent(academicYearId)}` : "";
  return (await request(`/api/academic/semesters${query}`)).data;
};
export const createSemester = async (payload) =>
  (await request("/api/academic/semesters", { method: "POST", body: payload })).data;
export const updateSemester = async (id, payload) =>
  (await request(`/api/academic/semesters/${id}`, { method: "PUT", body: payload })).data;
export const deleteSemester = async (id) => request(`/api/academic/semesters/${id}`, { method: "DELETE" });

export const getDivisions = async (semesterId) => {
  const query = semesterId ? `?semester_id=${encodeURIComponent(semesterId)}` : "";
  return (await request(`/api/academic/divisions${query}`)).data;
};
export const createDivision = async (payload) =>
  (await request("/api/academic/divisions", { method: "POST", body: payload })).data;
export const updateDivision = async (id, payload) =>
  (await request(`/api/academic/divisions/${id}`, { method: "PUT", body: payload })).data;
export const deleteDivision = async (id) => request(`/api/academic/divisions/${id}`, { method: "DELETE" });

export const getSubjects = async (semesterId) => {
  const query = semesterId ? `?semester_id=${encodeURIComponent(semesterId)}` : "";
  return (await request(`/api/academic/subjects${query}`)).data;
};
export const createSubject = async (payload) =>
  (await request("/api/academic/subjects", { method: "POST", body: payload })).data;
export const updateSubject = async (id, payload) =>
  (await request(`/api/academic/subjects/${id}`, { method: "PUT", body: payload })).data;
export const deleteSubject = async (id) => request(`/api/academic/subjects/${id}`, { method: "DELETE" });

export const getFacultyAssignments = async () => (await request("/api/academic/faculty-assignments")).data;
export const createFacultyAssignment = async (payload) =>
  (await request("/api/academic/faculty-assignments", { method: "POST", body: payload })).data;
export const deleteFacultyAssignment = async (id) =>
  request(`/api/academic/faculty-assignments/${id}`, { method: "DELETE" });

export const getMyFacultyAssignments = async () => (await request("/api/faculty/me/assignments")).data;

export const getStudentProfile = async () => (await request("/api/student/me/profile")).data;

// --- Phase 2 correction: HOD-only account management ----------------------

export const getFacultyAccounts = async () => (await request("/api/admin/faculty")).data;
export const createFaculty = async ({ name, email, password }) =>
  (await request("/api/admin/faculty", { method: "POST", body: { name, email, password } })).data;
export const updateFacultyAccount = async (id, payload) =>
  (await request(`/api/admin/faculty/${id}`, { method: "PUT", body: payload })).data;
export const setFacultyAccountStatus = async (id, isActive) =>
  (await request(`/api/admin/faculty/${id}/status`, { method: "PUT", body: { is_active: isActive } })).data;

export const linkStudentAccount = async (studentId, userId) =>
  (await request(`/api/admin/students/${studentId}/account`, { method: "POST", body: { user_id: userId } })).data;
export const relinkStudentAccount = async (studentId, userId) =>
  (await request(`/api/admin/students/${studentId}/account`, { method: "PUT", body: { user_id: userId } })).data;
export const setStudentAccountStatus = async (studentId, isActive) =>
  (
    await request(`/api/admin/students/${studentId}/account/status`, {
      method: "PUT",
      body: { is_active: isActive },
    })
  ).data;
